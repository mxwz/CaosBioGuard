"""指纹模态引擎：方向场增强 + 细化 + 细节点（端点/分叉）匹配。

流程与工业 AFIS 的轻量版一致：
1. 前景分割（块方差）→ 2. 方向场（结构张量）→ 3. Gabor 增强 →
4. 二值化 + 细化 → 5. 交叉数提取细节点 → 6. 平移投票 + 几何一致性匹配。

说明：这是**图像级**指纹算法，适用于光学/电容传感器导出的 500dpi 图像；
采集端若直接输出 ISO 19794-2 模板，可绕过本引擎，直接把模板交给比对层。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import numpy as np

from ..base import ImageEngine, clip01, cosine_score, ensure_gray, image_quality, resize_gray
from ..types import BioSample, BioTemplate, LivenessReport, ModalitySpec, QualityReport

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


FP_SPEC = ModalitySpec(
    name='fingerprint',
    label='指纹',
    kind='image',
    description='方向场增强 + 细节点匹配，支持 500dpi 指纹图像。',
    hardware='光学/电容指纹模块（推荐 500dpi，符合 ISO 19794-2）',
    supports_liveness=False,
    default_threshold=0.55,
    security_level=4,
)


class FingerprintEngine(ImageEngine):
    spec = FP_SPEC

    def __init__(self, work_size: int = 384, min_minutiae: int = 10):
        self.work_size = work_size
        self.min_minutiae = min_minutiae

    def check_available(self) -> Tuple[bool, str]:
        if cv2 is None:
            return False, '缺少 opencv-python'
        return True, ''

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    def _prepare(self, img: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        gray = ensure_gray(img)
        h, w = gray.shape[:2]
        scale = self.work_size / float(max(h, w))
        if scale < 1.0:
            gray = resize_gray(gray, (int(w * scale), int(h * scale)))
        gray = cv2.equalizeHist(gray) if cv2 is not None else gray

        # 1) 块方差分割
        block = 16
        hh, ww = gray.shape[0] // block * block, gray.shape[1] // block * block
        blocks = gray[:hh, :ww].astype(np.float32).reshape(hh // block, block, ww // block, block)
        var = blocks.var(axis=(1, 3))
        mean = blocks.mean(axis=(1, 3))
        valid = (var > 12.0) & (mean > 18.0) & (mean < 245.0)
        mask_small = np.repeat(np.repeat(valid, block, axis=0), block, axis=1)
        mask = np.zeros_like(gray)
        mask[:hh, :ww] = mask_small.astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            big = max(contours, key=cv2.contourArea)
            fill = np.zeros_like(mask)
            cv2.drawContours(fill, [big], -1, 255, -1)
            mask = fill
        return gray, mask, self._orientation_field(gray, mask)

    @staticmethod
    def _orientation_field(gray: np.ndarray, mask: np.ndarray) -> np.ndarray:
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        gxx = cv2.GaussianBlur(gx * gx, (0, 0), 4.0)
        gyy = cv2.GaussianBlur(gy * gy, (0, 0), 4.0)
        gxy = cv2.GaussianBlur(gx * gy, (0, 0), 4.0)
        theta = 0.5 * np.arctan2(2 * gxy, gxx - gyy + 1e-9)
        theta = np.where(mask > 0, theta, 0)
        return theta.astype(np.float32)

    def _enhance(self, gray: np.ndarray, mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """8 方向 Gabor 竞争增强，返回增强图与主方向索引。"""
        enhanced = np.full_like(gray, 0, dtype=np.float32)
        best = np.zeros_like(gray, dtype=np.int8)
        best_response = np.full_like(gray, -1.0, dtype=np.float32)
        for i in range(8):
            theta = i * math.pi / 8
            kern = self._gabor_kernel(theta, 31, 4.2, 9.0)
            resp = np.abs(cv2.filter2D(gray.astype(np.float32), cv2.CV_32F, kern))
            sel = resp > best_response
            best_response[sel] = resp[sel]
            enhanced[sel] = resp[sel]
            best[sel] = i
        enhanced = cv2.normalize(enhanced, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        enhanced = cv2.bitwise_and(enhanced, enhanced, mask=(mask > 0).astype(np.uint8))
        return enhanced, best

    @staticmethod
    def _gabor_kernel(theta: float, ksize: int, sigma: float, lambd: float) -> np.ndarray:
        half = ksize // 2
        y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float32)
        xr = x * math.cos(theta) + y * math.sin(theta)
        yr = -x * math.sin(theta) + y * math.cos(theta)
        g = np.exp(-(xr ** 2 + 0.35 * yr ** 2) / (2 * sigma ** 2))
        kern = g * np.cos(2 * math.pi * xr / lambd)
        kern -= kern.mean()
        return kern.astype(np.float32)

    @staticmethod
    def _thin(binary: np.ndarray) -> np.ndarray:
        try:
            return cv2.ximgproc.thinning(binary)
        except Exception:
            img = (binary > 0).astype(np.uint8)
            skel = np.zeros_like(img)
            element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
            for _ in range(80):
                erode = cv2.erode(img, element)
                opening = cv2.dilate(erode, element)
                skel |= (img - opening)
                img = erode
                if img.sum() == 0:
                    break
            return skel * 255

    # ------------------------------------------------------------------
    # 细节点
    # ------------------------------------------------------------------
    def _minutiae(self, enhanced: np.ndarray, mask: np.ndarray,
                  theta: np.ndarray) -> np.ndarray:
        binary = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 31, 5)
        binary = cv2.bitwise_and(binary, binary, mask=(mask > 0).astype(np.uint8))
        skel = self._thin(binary)
        skel_bin = (skel > 0).astype(np.uint8)
        p = np.pad(skel_bin, 1)
        c = p[1:-1, 1:-1]
        neigh = [p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:],
                 p[2:, 2:], p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2]]
        cn = sum(np.abs(neigh[i].astype(np.int8) - neigh[i + 1].astype(np.int8)) for i in range(8)) / 2.0
        ends = (c == 1) & (cn == 1)
        bifs = (c == 1) & (cn >= 3)
        pts_mask = (ends | bifs) & (mask > 0)
        # 去边界
        border = 12
        pts_mask[:border, :] = False
        pts_mask[-border:, :] = False
        pts_mask[:, :border] = False
        pts_mask[:, -border:] = False

        ys, xs = np.where(pts_mask)
        if len(xs) == 0:
            return np.zeros((0, 4), dtype=np.float32)
        order = np.argsort(-enhanced[ys, xs].astype(np.float32))
        kept: List[Tuple[float, float, float, int]] = []
        min_dist = max(6.0, min(enhanced.shape) / 64.0)
        for idx in order:
            x, y = float(xs[idx]), float(ys[idx])
            if any((x - kx) ** 2 + (y - ky) ** 2 < min_dist ** 2 for kx, ky, _, _ in kept):
                continue
            ang = float(theta[ys[idx], xs[idx]])
            kind = 1 if bifs[ys[idx], xs[idx]] else 0
            kept.append((x, y, ang, kind))
        if not kept:
            return np.zeros((0, 4), dtype=np.float32)
        h, w = enhanced.shape[:2]
        arr = np.asarray(kept, dtype=np.float32)
        arr[:, 0] /= max(w - 1, 1)
        arr[:, 1] /= max(h - 1, 1)
        return arr

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        base = image_quality(self._image(sample))
        if cv2 is None:
            return base
        try:
            gray, mask, theta = self._prepare(self._image(sample))
            enhanced, _ = self._enhance(gray, mask)
            minutiae = self._minutiae(enhanced, mask, theta)
        except Exception as exc:
            return QualityReport(0.0, False, base.metrics, [f'指纹处理失败: {exc}'])
        area = float((mask > 0).mean())
        coherence = float(np.abs(np.exp(1j * 2 * theta[mask > 0])).mean()) if area > 0 else 0.0
        metrics = dict(base.metrics)
        metrics.update({'foreground_ratio': area, 'minutiae': float(len(minutiae)), 'ridge_clarity': coherence})
        issues = list(base.issues)
        if area < 0.18:
            issues.append('指纹有效区域过小')
        if len(minutiae) < self.min_minutiae:
            issues.append(f'细节点不足({len(minutiae)})')
        score = 0.52 * base.score + 0.24 * coherence + 0.24 * float(np.clip(len(minutiae) / 35.0, 0, 1))
        return QualityReport(score=clip01(score), passed=bool(score >= 0.45 and len(minutiae) >= self.min_minutiae),
                             metrics=metrics, issues=issues)

    def extract(self, sample: BioSample) -> BioTemplate:
        img = self._image(sample)
        report = self.quality(sample)
        if not report.passed:
            raise ValueError('指纹质量不合格：' + '；'.join(report.issues or ['细节点不足']))
        gray, mask, theta = self._prepare(img)
        enhanced, _ = self._enhance(gray, mask)
        minutiae = self._minutiae(enhanced, mask, theta)
        # 方向直方图（8 维）作为全局辅助特征
        hist, _ = np.histogram(theta[mask > 0], bins=8, range=(-math.pi / 2, math.pi / 2), density=False)
        hist = hist.astype(np.float32) / max(hist.sum(), 1.0)
        return BioTemplate(
            modality=self.name,
            version=1,
            arrays={'minutiae': minutiae, 'orient_hist': hist.reshape(1, -1)},
            meta={'count': int(len(minutiae)), 'work_size': int(enhanced.shape[0])},
            quality=report.score,
        )

    # ------------------------------------------------------------------
    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        ma = np.asarray(a.arrays.get('minutiae', np.zeros((0, 4))), dtype=np.float32)
        mb = np.asarray(b.arrays.get('minutiae', np.zeros((0, 4))), dtype=np.float32)
        if len(ma) == 0 or len(mb) == 0:
            return 0.0

        # 1) 平移投票：角度一致的细节点对投票到同一个位移格
        max_dist = 0.16
        angle_tol = 0.55
        bin_size = 0.025
        votes: Dict[Tuple[int, int], int] = {}
        for (xa, ya, ta, ka) in ma:
            da = mb[:, 0] - xa
            db = mb[:, 1] - ya
            dist = np.hypot(da, db)
            dang = np.abs(_angle_diff(mb[:, 2], ta))
            ok = (dist < max_dist) & (dang < angle_tol) & (mb[:, 3] == ka)
            if not ok.any():
                continue
            for dx, dy in zip(da[ok], db[ok]):
                key = (int(round(dx / bin_size)), int(round(dy / bin_size)))
                votes[key] = votes.get(key, 0) + 1
        if not votes:
            return 0.0
        best_bin = max(votes, key=votes.get)
        tx, ty = best_bin[0] * bin_size, best_bin[1] * bin_size

        # 2) 在最佳平移下做唯一配对
        used = set()
        matched = 0
        for i, (xa, ya, ta, ka) in enumerate(ma):
            best_j, best_d = -1, 1e9
            for j, (xb, yb, tb, kb) in enumerate(mb):
                if j in used or kb != ka:
                    continue
                d = math.hypot((xb - xa) - tx, (yb - ya) - ty)
                if d < 0.045 and abs(_angle_diff(tb, ta)) < 0.5 and d < best_d:
                    best_j, best_d = j, d
            if best_j >= 0:
                used.add(best_j)
                matched += 1
        overlap = 2.0 * matched / max(len(ma) + len(mb), 1)
        hist_score = cosine_score(a.arrays.get('orient_hist', np.zeros((1, 8))).reshape(-1),
                                  b.arrays.get('orient_hist', np.zeros((1, 8))).reshape(-1))
        density_ratio = min(len(ma), len(mb)) / max(len(ma), len(mb))
        # 细节点重合率是主证据；方向直方图近似均匀，只做弱辅助，避免虚高
        return clip01(0.92 * overlap + 0.05 * hist_score + 0.03 * density_ratio)

    def liveness(self, sample: BioSample) -> LivenessReport:
        report = self.quality(sample)
        # 图像级只能判断「像不像一张好指纹」，无法识别导电假指/硅胶膜
        score = 0.55 + 0.35 * report.score
        return LivenessReport(
            passed=bool(report.passed and score >= 0.6),
            score=clip01(score), mode='heuristic',
            reasons=['指纹活体需依赖传感器（电容/光学/超声）硬件能力', '软件层仅做图像质量与纹理连续性检查'],
        )


def _angle_diff(a, b):
    d = np.asarray(a) - np.asarray(b)
    return (d + math.pi) % (2 * math.pi) - math.pi
