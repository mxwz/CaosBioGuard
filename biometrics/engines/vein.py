"""静脉模态引擎（指静脉 / 掌静脉，近红外图像）。

算法链：CLAHE → 多尺度 Hessian 管状结构增强（Frangi vesselness）→ 血管图 →
网格密度 + 方向直方图 + 径向分布 + LBP 纹理 → 余弦比对。

静脉属于「皮下特征」，比掌纹更难伪造；但活体判定仍建议由近红外传感器
（血红蛋白吸收特性）承担，软件只做图像连续性检查。
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from ..base import ImageEngine, clip01, cosine_score, ensure_gray, image_quality, l2norm, resize_gray
from ..types import BioSample, BioTemplate, LivenessReport, ModalitySpec, QualityReport

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


VEIN_SPEC = ModalitySpec(
    name='vein',
    label='静脉',
    kind='image',
    description='Frangi 管状增强 + 多视角纹理特征，适配指静脉/掌静脉近红外图。',
    hardware='850nm 近红外指静脉/掌静脉模块',
    supports_liveness=True,
    default_threshold=0.58,
    security_level=4,
)


class VeinEngine(ImageEngine):
    spec = VEIN_SPEC

    def __init__(self, size: int = 96, sigmas: Tuple[float, ...] = (1.2, 2.0, 3.0)):
        self.size = size
        self.sigmas = sigmas

    def check_available(self) -> Tuple[bool, str]:
        if cv2 is None:
            return False, '缺少 opencv-python'
        return True, ''

    # ------------------------------------------------------------------
    def _vesselness(self, gray: np.ndarray) -> np.ndarray:
        img = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
        base = img.astype(np.float32) / 255.0
        best = np.zeros_like(base)
        for sigma in self.sigmas:
            blur = cv2.GaussianBlur(base, (0, 0), sigma)
            dxx = cv2.Sobel(blur, cv2.CV_32F, 2, 0, ksize=3)
            dyy = cv2.Sobel(blur, cv2.CV_32F, 0, 2, ksize=3)
            dxy = cv2.Sobel(blur, cv2.CV_32F, 1, 1, ksize=3)
            tmp = np.sqrt(np.maximum((dxx - dyy) ** 2 + 4 * dxy ** 2, 0))
            l1 = 0.5 * (dxx + dyy + tmp)
            l2 = 0.5 * (dxx + dyy - tmp)
            # 约定：|l1| <= |l2|；亮脊（血管）对应 l2 < 0
            swap = np.abs(l1) > np.abs(l2)
            l1, l2 = np.where(swap, l2, l1), np.where(swap, l1, l2)
            rb = np.abs(l1) / (np.abs(l2) + 1e-6)
            s = np.sqrt(l1 ** 2 + l2 ** 2)
            # 暗血管在反转图中表现为亮脊：要求 l2 < 0
            resp = np.exp(-(rb ** 2) / (2 * 0.5 ** 2)) * (1 - np.exp(-(s ** 2) / (2 * 0.6 ** 2)))
            resp = np.where(l2 < 0, resp, 0)
            best = np.maximum(best, resp)
        best = cv2.normalize(best, None, 0, 1, cv2.NORM_MINMAX)
        return best.astype(np.float32)

    def _binary(self, vessel: np.ndarray) -> np.ndarray:
        # 血管响应在背景上接近 0，绝对阈值比高分位更稳
        thr = max(float(np.percentile(vessel, 90)), 0.18 * float(vessel.max()))
        binary = (vessel >= thr).astype(np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        return binary

    @staticmethod
    def _lbp_hist(binary: np.ndarray, bins: int = 16) -> np.ndarray:
        b = binary.astype(np.int32)
        h, w = b.shape
        code = np.zeros((h - 2, w - 2), dtype=np.int32)
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]
        for k, (dy, dx) in enumerate(offsets):
            code |= (b[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx] >= b[1:h - 1, 1:w - 1]) << k
        hist, _ = np.histogram(code, bins=bins, range=(0, 256))
        hist = hist.astype(np.float32) / max(hist.sum(), 1.0)
        return hist

    def _features(self, img: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        gray = ensure_gray(img)
        h, w = gray.shape[:2]
        scale = self.size / float(max(h, w))
        if scale < 1.0:
            gray = resize_gray(gray, (int(w * scale), int(h * scale)))
        vessel = self._vesselness(gray)
        binary = self._binary(vessel)
        coverage = float(binary.mean())

        # 1) 8x8 网格密度
        grid = cv2.resize(binary.astype(np.float32), (8, 8), interpolation=cv2.INTER_AREA).reshape(-1)
        # 2) 方向直方图（血管走向）
        gx = cv2.Sobel(vessel, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(vessel, cv2.CV_32F, 0, 1, ksize=3)
        ang = np.arctan2(gy, gx) % math.pi
        hist, _ = np.histogram(ang[binary > 0], bins=8, range=(0, math.pi))
        hist = hist.astype(np.float32) / max(hist.sum(), 1.0)
        # 3) 以质心为中心的径向密度（16 环）
        ys, xs = np.where(binary > 0)
        if len(xs):
            cy, cx = ys.mean(), xs.mean()
            r = np.hypot(xs - cx, ys - cy) / (0.5 * max(h, w) + 1e-6)
            rad, _ = np.histogram(r, bins=16, range=(0, 1))
            rad = rad.astype(np.float32) / max(rad.sum(), 1.0)
        else:
            rad = np.zeros(16, dtype=np.float32)
        # 4) LBP 纹理
        lbp = self._lbp_hist(binary)
        feat = np.concatenate([grid, hist, rad, lbp], axis=0)
        return l2norm(feat), vessel, coverage

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        base = image_quality(self._image(sample))
        if cv2 is None:
            return base
        try:
            feat, vessel, coverage = self._features(self._image(sample))
        except Exception as exc:
            return QualityReport(0.0, False, base.metrics, [f'静脉处理失败: {exc}'])
        metrics = dict(base.metrics)
        metrics.update({'vessel_coverage': coverage, 'vessel_contrast': float(vessel.std())})
        issues = list(base.issues)
        if coverage < 0.035:
            issues.append('血管纹理过少')
        if coverage > 0.55:
            issues.append('二值化过度（噪声/过曝）')
        score = (0.30 * base.metrics.get('sharpness', 0.0)
                 + 0.28 * min(metrics['vessel_contrast'] / 0.25, 1.0)
                 + 0.42 * float(np.clip((coverage - 0.03) / 0.12, 0, 1)))
        return QualityReport(score=clip01(score), passed=bool(score >= 0.42 and 0.03 <= coverage <= 0.55),
                             metrics=metrics, issues=issues)

    def extract(self, sample: BioSample) -> BioTemplate:
        report = self.quality(sample)
        if not report.passed:
            raise ValueError('静脉质量不合格：' + '；'.join(report.issues or ['血管纹理不足']))
        feat, vessel, coverage = self._features(self._image(sample))
        small = cv2.resize(vessel, (32, 32), interpolation=cv2.INTER_AREA).reshape(1, -1)
        return BioTemplate(
            modality=self.name, version=1,
            arrays={'embedding': feat.reshape(1, -1), 'map': small.astype(np.float32)},
            meta={'coverage': coverage},
            quality=report.score,
        )

    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        if 'embedding' not in a.arrays or 'embedding' not in b.arrays:
            return 0.0
        emb = cosine_score(a.arrays['embedding'].reshape(-1), b.arrays['embedding'].reshape(-1))
        ma = np.asarray(a.arrays.get('map', np.zeros((1, 1024))), dtype=np.float32).reshape(-1)
        mb = np.asarray(b.arrays.get('map', np.zeros((1, 1024))), dtype=np.float32).reshape(-1)
        if ma.size == mb.size and ma.size > 0:
            ba, bb = ma > 0.2, mb > 0.2
            union = float(np.logical_or(ba, bb).sum())
            iou = float(np.logical_and(ba, bb).sum()) / union if union > 0 else 0.0
            return clip01(0.55 * emb + 0.45 * iou)
        return emb

    def liveness(self, sample: BioSample) -> LivenessReport:
        report = self.quality(sample)
        # 近红外图应满足：背景暗、血管连续、无可见光下的皮肤反光
        gray = self._image(sample)
        mean = float(gray.mean()) / 255.0
        reasons = ['静脉 PAD 建议由近红外传感器做血氧/血流验证']
        score = 0.55 + 0.35 * report.score
        if mean > 0.85:
            score -= 0.2
            reasons.append('整体过亮，疑似可见光翻拍')
        return LivenessReport(passed=bool(report.passed and score >= 0.6), score=clip01(score),
                              mode='heuristic', reasons=reasons)
