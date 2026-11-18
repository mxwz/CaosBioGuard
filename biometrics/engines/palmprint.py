"""掌纹模态引擎：Gabor 竞争编码（CompCode）+ 角度距离比对。

掌纹的主线（生命线/感情线/智慧线）在 Gabor 多方向响应中表现为稳定的方向主导，
竞争编码只保留每个像素的最强方向，对光照变化不敏感，模板也很小。
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from ..base import ImageEngine, clip01, cosine_score, ensure_gray, image_quality, resize_gray
from ..types import BioSample, BioTemplate, LivenessReport, ModalitySpec, QualityReport

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


PALM_SPEC = ModalitySpec(
    name='palmprint',
    label='掌纹',
    kind='image',
    description='Gabor 竞争编码提取掌纹主线方向，支持 ±4 像素平移容忍。',
    hardware='可见光掌纹采集仪 / 高拍仪',
    supports_liveness=False,
    default_threshold=0.60,
    security_level=3,
)


class PalmprintEngine(ImageEngine):
    spec = PALM_SPEC

    def __init__(self, size: int = 128, code_size: int = 64, orientations: int = 6):
        self.size = size
        self.code_size = code_size
        self.orientations = orientations
        self._bank = self._build_bank()

    def check_available(self) -> Tuple[bool, str]:
        if cv2 is None:
            return False, '缺少 opencv-python'
        return True, ''

    def _build_bank(self) -> np.ndarray:
        kernels = []
        for i in range(self.orientations):
            theta = i * math.pi / self.orientations
            sigma, lambd = 4.2, 12.0
            half = 17
            y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float32)
            xr = x * math.cos(theta) + y * math.sin(theta)
            yr = -x * math.sin(theta) + y * math.cos(theta)
            g = np.exp(-(xr ** 2 + yr ** 2) / (2 * sigma ** 2))
            k = g * np.cos(2 * math.pi * xr / lambd)
            k -= k.mean()
            kernels.append(k)
        return np.stack(kernels, axis=0).astype(np.float32)

    # ------------------------------------------------------------------
    def _roi(self, gray: np.ndarray) -> np.ndarray:
        """优先抠手掌区域；失败则取中心正方形，兼容已裁剪的掌纹图。"""
        h, w = gray.shape[:2]
        blur = cv2.GaussianBlur(gray, (7, 7), 0)
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            big = max(contours, key=cv2.contourArea)
            if cv2.contourArea(big) > 0.25 * h * w:
                rect = cv2.minAreaRect(big)
                (cx, cy), (rw, rh), ang = rect
                side = int(min(max(rw, rh), min(h, w)))
                if side > 64:
                    x1 = int(np.clip(cx - side / 2, 0, w - side))
                    y1 = int(np.clip(cy - side / 2, 0, h - side))
                    patch = gray[y1:y1 + side, x1:x1 + side]
                    return cv2.resize(patch, (self.size, self.size), interpolation=cv2.INTER_AREA)
        side = min(h, w)
        x1, y1 = (w - side) // 2, (h - side) // 2
        return cv2.resize(gray[y1:y1 + side, x1:x1 + side], (self.size, self.size), interpolation=cv2.INTER_AREA)

    def _features(self, img: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        gray = ensure_gray(img)
        roi = self._roi(gray)
        roi = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(roi)
        roi_f = roi.astype(np.float32) / 255.0
        responses = np.stack([cv2.filter2D(roi_f, cv2.CV_32F, k) for k in self._bank], axis=0)
        strength = np.abs(responses)
        code = np.argmax(strength, axis=0).astype(np.int8)
        magnitude = np.max(strength, axis=0)
        # 以幅度加权，弱纹理区域不参与距离统计
        weight = (magnitude > np.percentile(magnitude, 30)).astype(np.float32)
        code_small = cv2.resize(code.astype(np.float32), (self.code_size, self.code_size),
                               interpolation=cv2.INTER_NEAREST).astype(np.int8)
        weight_small = cv2.resize(weight, (self.code_size, self.code_size), interpolation=cv2.INTER_AREA)
        return code_small, weight_small

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        base = image_quality(self._image(sample))
        if cv2 is None:
            return base
        try:
            code, weight = self._features(self._image(sample))
        except Exception as exc:
            return QualityReport(0.0, False, base.metrics, [f'掌纹处理失败: {exc}'])
        valid = float((weight > 0.25).mean())
        metrics = dict(base.metrics)
        metrics['valid_ratio'] = valid
        issues = list(base.issues)
        if valid < 0.4:
            issues.append('有效掌纹区域不足')
        score = 0.6 * base.score + 0.4 * clip01(valid / 0.75)
        return QualityReport(score=clip01(score), passed=bool(score >= 0.46 and valid >= 0.4),
                             metrics=metrics, issues=issues)

    def extract(self, sample: BioSample) -> BioTemplate:
        report = self.quality(sample)
        if not report.passed:
            raise ValueError('掌纹质量不合格：' + '；'.join(report.issues or ['有效区域不足']))
        code, weight = self._features(self._image(sample))
        return BioTemplate(
            modality=self.name, version=1,
            arrays={'code': code, 'weight': weight},
            meta={'orientation_bins': self.orientations, 'code_size': self.code_size},
            quality=report.score,
        )

    # ------------------------------------------------------------------
    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        ca = np.asarray(a.arrays.get('code'), dtype=np.int16)
        cb = np.asarray(b.arrays.get('code'), dtype=np.int16)
        wa = np.asarray(a.arrays.get('weight'), dtype=np.float32)
        wb = np.asarray(b.arrays.get('weight'), dtype=np.float32)
        if ca is None or cb is None or ca.shape != cb.shape:
            return 0.0
        bins = int(a.meta.get('orientation_bins', self.orientations))
        best = 0.0
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                cb_s = np.roll(np.roll(cb, dy, axis=0), dx, axis=1)
                wb_s = np.roll(np.roll(wb, dy, axis=0), dx, axis=1)
                valid = (wa > 0.25) & (wb_s > 0.25)
                if valid.sum() < 64:
                    continue
                diff = np.abs(ca - cb_s)
                diff = np.minimum(diff, bins - diff)  # 方向是环形的
                sim = 1.0 - (diff / (bins / 2.0))
                score = float(np.mean(sim[valid]))
                best = max(best, score)
        return clip01(best)

    def liveness(self, sample: BioSample) -> LivenessReport:
        base = self.quality(sample)
        # 打印掌纹常见特征：高频网点/墨迹过于均匀；只能做弱判断
        score = 0.5 + 0.4 * base.score
        return LivenessReport(
            passed=bool(base.passed and score >= 0.6),
            score=clip01(score), mode='heuristic',
            reasons=['掌纹 PAD 建议结合掌静脉（近红外）双模态', '单可见光图像无法可靠区分打印/真实手掌'],
        )
