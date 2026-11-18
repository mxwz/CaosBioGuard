"""虹膜模态引擎：Daugman 风格「定位 → 极坐标归一化 → Log-Gabor 相位编码 → 汉明距离」。

实现要点：
- 瞳孔用暗区 + 最小外接圆定位，虹膜外边界用径向梯度积分（简化 integro-differential）；
- 极坐标 rubber-sheet 归一化，消除尺度与平移差异；
- 1D Log-Gabor 多尺度相位量化，生成 2 bit/点的虹膜码，并用掩码排除眼睑/反光；
- 比对时对 ±8 像素角度旋转做最优汉明距离搜索，容忍轻微头部转动。
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np

from ..base import ImageEngine, clip01, ensure_gray, image_quality, resize_gray
from ..types import BioSample, BioTemplate, LivenessReport, ModalitySpec, QualityReport

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


IRIS_SPEC = ModalitySpec(
    name='iris',
    label='虹膜',
    kind='image',
    description='Daugman 式虹膜定位与 Log-Gabor 相位编码，支持旋转容忍比对。',
    hardware='近红外虹膜摄像头（850nm 波段最佳）',
    supports_liveness=True,
    default_threshold=0.70,
    security_level=5,
)


class IrisEngine(ImageEngine):
    spec = IRIS_SPEC

    def __init__(self, rows: int = 8, cols: int = 128, work_size: int = 480):
        self.rows = rows
        self.cols = cols
        self.work_size = work_size

    def check_available(self) -> Tuple[bool, str]:
        if cv2 is None:
            return False, '缺少 opencv-python'
        return True, ''

    # ------------------------------------------------------------------
    # 定位
    # ------------------------------------------------------------------
    def _locate(self, gray: np.ndarray) -> Tuple[float, float, float, float]:
        h, w = gray.shape[:2]
        # 瞳孔：中央区域暗像素
        cy0, cx0 = h // 2, w // 2
        roi = gray[int(h * 0.15):int(h * 0.85), int(w * 0.15):int(w * 0.85)]
        thr = max(int(np.percentile(roi, 5)) + 8, 25)
        dark = (roi <= thr).astype(np.uint8) * 255
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            big = max(contours, key=cv2.contourArea)
            (px, py), pr = cv2.minEnclosingCircle(big)
            px += int(w * 0.15)
            py += int(h * 0.15)
            if pr < 4:
                pr = min(h, w) * 0.06
        else:
            px, py, pr = float(cx0), float(cy0), min(h, w) * 0.08

        # 外边界：沿 360 条射线做径向梯度积分
        max_r = min(px, py, w - px, h - py) - 3
        r_min = max(pr * 1.35, pr + 4)
        r_max = max(r_min + 8, max_r)
        radii = np.arange(int(r_min), int(min(r_max, max_r)), 1)
        if radii.size == 0:
            return px, py, pr, pr * 2.5
        angles = np.linspace(0, 2 * math.pi, 360, endpoint=False)
        cos_a, sin_a = np.cos(angles), np.sin(angles)
        blur = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1.2)
        scores = []
        for r in radii:
            xs = px + r * cos_a
            ys = py + r * sin_a
            xs = np.clip(xs, 0, w - 1)
            ys = np.clip(ys, 0, h - 1)
            # 内外各 1px 差分
            inner = cv2.remap(blur, (xs - cos_a).astype(np.float32)[None, :], (ys - sin_a).astype(np.float32)[None, :],
                              cv2.INTER_LINEAR).reshape(-1)
            outer = cv2.remap(blur, (xs + cos_a).astype(np.float32)[None, :], (ys + sin_a).astype(np.float32)[None, :],
                              cv2.INTER_LINEAR).reshape(-1)
            scores.append(float(np.mean(np.abs(outer - inner))))
        scores = np.asarray(scores, dtype=np.float32)
        # 平滑后取峰，且半径至少为瞳孔 1.4 倍
        smooth = np.convolve(scores, np.ones(5) / 5.0, mode='same')
        best = int(np.argmax(smooth))
        r_iris = float(radii[best])
        if r_iris <= pr * 1.2:
            r_iris = pr * 2.2
        r_iris = min(r_iris, max_r)
        return float(px), float(py), float(pr), float(r_iris)

    # ------------------------------------------------------------------
    # 归一化
    # ------------------------------------------------------------------
    def _normalize(self, gray: np.ndarray, cx: float, cy: float,
                   r_pupil: float, r_iris: float) -> Tuple[np.ndarray, np.ndarray]:
        rows, cols = self.rows, self.cols
        radii = np.linspace(r_pupil, r_iris, rows, dtype=np.float32)
        angles = np.linspace(0, 2 * math.pi, cols, endpoint=False, dtype=np.float32)
        xs = cx + radii[:, None] * np.cos(angles)[None, :]
        ys = cy + radii[:, None] * np.sin(angles)[None, :]
        polar = cv2.remap(gray.astype(np.float32), xs, ys, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
        # 掩码：过暗/过亮、外圈眼睑、低局部对比
        mask = np.ones((rows, cols), dtype=np.uint8)
        mask[(polar < 18) | (polar > 248)] = 0
        mask[: max(1, rows // 8), :] = 0
        mask[-max(1, rows // 6):, :] = 0
        local_std = cv2.blur(polar ** 2, (5, 5)) - cv2.blur(polar, (5, 5)) ** 2
        mask[local_std < 6.0] = 0
        return polar, mask

    @staticmethod
    def _log_gabor(rows: np.ndarray, wavelength: float, sigma_onf: float = 0.55) -> np.ndarray:
        """对每行做 1D Log-Gabor 滤波，返回复数响应。``rows`` 形状 (R, C)。"""
        n = rows.shape[1]
        u = np.fft.fftfreq(n)
        u[0] = 1.0 / n
        f0 = 1.0 / max(wavelength, 1.0)
        log_u = np.log(np.maximum(np.abs(u), 1e-6) / f0)
        transfer = np.exp(-(log_u ** 2) / (2 * (math.log(max(sigma_onf, 1.01)) ** 2)))
        transfer[0] = 0
        # 保持共轭对称，保证 ifft 为实数
        transfer = np.fft.fftshift(transfer)
        spec = np.fft.fftshift(np.fft.fft(rows, axis=1), axes=1)
        resp = np.fft.ifft(np.fft.ifftshift(spec * transfer[None, :], axes=1), axis=1)
        return resp

    def _encode(self, polar: np.ndarray, mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        codes = []
        masks = []
        for wavelength in (4.0, 8.0, 16.0):
            resp = self._log_gabor(polar, wavelength)
            energy = np.abs(resp)
            valid = (mask > 0) & (energy > np.percentile(energy[mask > 0], 25) if (mask > 0).any() else energy > 0)
            bits = np.stack([(resp.real >= 0).astype(np.uint8), (resp.imag >= 0).astype(np.uint8)], axis=0)
            codes.append(bits)
            masks.append(np.stack([valid.astype(np.uint8)] * 2, axis=0))
        return np.stack(codes, axis=0), np.stack(masks, axis=0)

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        base = image_quality(self._image(sample))
        if cv2 is None:
            return base
        gray = self._prep(self._image(sample))
        try:
            cx, cy, rp, ri = self._locate(gray)
            polar, mask = self._normalize(gray, cx, cy, rp, ri)
        except Exception as exc:
            return QualityReport(0.0, False, base.metrics, [f'虹膜定位失败: {exc}'])
        usable = float(mask.mean()) if mask.size else 0.0
        ratio = ri / max(rp, 1.0)
        metrics = dict(base.metrics)
        metrics.update({'pupil_radius': rp, 'iris_radius': ri, 'iris_pupil_ratio': ratio, 'usable_ratio': usable})
        issues = list(base.issues)
        if ratio < 1.7:
            issues.append('虹膜环过窄，定位不可靠')
        if usable < 0.45:
            issues.append('眼睑/反光遮挡过多')
        if min(gray.shape) < 120:
            issues.append('分辨率过低')
        score = 0.45 * base.score + 0.30 * float(np.clip((ratio - 1.4) / 1.4, 0, 1)) + 0.25 * float(np.clip(usable / 0.7, 0, 1))
        return QualityReport(score=clip01(score), passed=bool(score >= 0.48 and ratio >= 1.7 and usable >= 0.45),
                             metrics=metrics, issues=issues)

    def _prep(self, img: np.ndarray) -> np.ndarray:
        gray = ensure_gray(img)
        h, w = gray.shape[:2]
        scale = self.work_size / float(max(h, w))
        if scale < 1.0:
            gray = resize_gray(gray, (int(w * scale), int(h * scale)))
        return cv2.equalizeHist(gray)

    def extract(self, sample: BioSample) -> BioTemplate:
        report = self.quality(sample)
        if not report.passed:
            raise ValueError('虹膜质量不合格：' + '；'.join(report.issues or ['定位失败']))
        gray = self._prep(self._image(sample))
        cx, cy, rp, ri = self._locate(gray)
        polar, mask = self._normalize(gray, cx, cy, rp, ri)
        code, cmask = self._encode(polar, mask)
        return BioTemplate(
            modality=self.name,
            version=1,
            arrays={'code': code, 'mask': cmask},
            meta={'rows': self.rows, 'cols': self.cols, 'scales': 3,
                  'iris_pupil_ratio': ri / max(rp, 1.0),
                  'usable_ratio': float(mask.mean())},
            quality=report.score,
        )

    # ------------------------------------------------------------------
    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        ca = np.asarray(a.arrays.get('code'))
        cb = np.asarray(b.arrays.get('code'))
        ma = np.asarray(a.arrays.get('mask'))
        mb = np.asarray(b.arrays.get('mask'))
        if ca is None or cb is None or ca.shape != cb.shape:
            return 0.0
        best_hd = 1.0
        for shift in range(-8, 9):
            cb_s = np.roll(cb, shift, axis=-1)
            mb_s = np.roll(mb, shift, axis=-1)
            valid = (ma > 0) & (mb_s > 0)
            if valid.sum() < 16:
                continue
            xor = np.logical_xor(ca > 0, cb_s > 0)
            hd = float((xor & valid).sum()) / float(valid.sum())
            best_hd = min(best_hd, hd)
        # 类内 HD 通常 <0.32，类间 ≈0.5；映射成 [0,1] 相似度
        return clip01(1.0 - best_hd)

    def liveness(self, sample: BioSample) -> LivenessReport:
        report = self.quality(sample)
        # 单帧只能看「瞳孔边界锐度 + 镜面反光」，接触镜/打印虹膜需专用模型
        score = 0.5 + 0.4 * report.score
        return LivenessReport(
            passed=bool(report.passed and score >= 0.62),
            score=clip01(score), mode='heuristic',
            reasons=['虹膜 PAD 依赖近红外活体特征（瞳孔收缩、红外反射）', '建议采集端做双帧瞳孔缩放挑战'],
        )
