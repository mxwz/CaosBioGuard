"""步态模态引擎：剪影序列 → 步态能量图（GEI）→ HOG 特征 → 余弦比对。

步态适合**远距离、非配合**场景（社区门禁、园区周界）。本实现假定输入为
已对齐的剪影序列；若给 RGB 帧，会用「边框背景估计 + Otsu」做一次轻量抠图。

质量要求：至少 12 帧、覆盖约 1.5 个步态周期，且剪影高度稳定。
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from ..base import ImageEngine, clip01, cosine_score, ensure_gray, image_quality, l2norm
from ..types import BioSample, BioTemplate, LivenessReport, ModalitySpec, QualityReport

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


GAIT_SPEC = ModalitySpec(
    name='gait',
    label='步态',
    kind='frames',
    description='GEI + HOG 步态特征，适合远距离非配合通行。',
    hardware='广角监控相机（建议 15~30fps，侧面或 45° 视角）',
    supports_liveness=False,
    default_threshold=0.78,
    security_level=3,
)


class GaitEngine(ImageEngine):
    spec = GAIT_SPEC

    def __init__(self, canvas: Tuple[int, int] = (48, 64), min_frames: int = 12):
        self.canvas_w, self.canvas_h = canvas
        self.min_frames = min_frames

    def check_available(self) -> Tuple[bool, str]:
        if cv2 is None:
            return False, '缺少 opencv-python'
        return True, ''

    # ------------------------------------------------------------------
    def _silhouette(self, frame: np.ndarray) -> np.ndarray:
        gray = ensure_gray(frame)
        # 边框均值估计背景亮度，决定前景极性
        border = np.concatenate([gray[:4, :].reshape(-1), gray[-4:, :].reshape(-1),
                                 gray[:, :4].reshape(-1), gray[:, -4:].reshape(-1)])
        bg = float(border.mean())
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        fg = th if abs(float(th.mean()) - bg) > abs(255 - float(th.mean()) - bg) else 255 - th
        # 修正：Otsu 后若前景占比过大则取反
        if (fg > 0).mean() > 0.65:
            fg = 255 - fg
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return np.zeros_like(gray)
        big = max(contours, key=cv2.contourArea)
        mask = np.zeros_like(gray)
        cv2.drawContours(mask, [big], -1, 255, -1)
        return mask

    def _normalize_silhouette(self, sil: np.ndarray) -> np.ndarray:
        ys, xs = np.where(sil > 0)
        out = np.zeros((self.canvas_h, self.canvas_w), dtype=np.float32)
        if len(xs) == 0:
            return out
        x1, x2, y1, y2 = xs.min(), xs.max(), ys.min(), ys.max()
        crop = sil[y1:y2 + 1, x1:x2 + 1]
        h, w = crop.shape[:2]
        new_h = self.canvas_h - 4
        new_w = max(2, int(round(w * new_h / max(h, 1))))
        new_w = min(new_w, self.canvas_w - 4)
        resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)
        ox = (self.canvas_w - new_w) // 2
        out[2:2 + new_h, ox:ox + new_w] = (resized > 0).astype(np.float32)
        return out

    def _gei(self, frames: List[np.ndarray]) -> Tuple[np.ndarray, List[float], List[float]]:
        silhouettes = [self._normalize_silhouette(self._silhouette(f)) for f in frames]
        gei = np.mean(np.stack(silhouettes, axis=0), axis=0)
        # 周期估计用**下半身（腿部）宽度**；归一化后宽度被固定，无法反映步幅
        raw = [self._silhouette(f) for f in frames]
        widths = []
        for m in raw:
            h = m.shape[0]
            lower = m[int(h * 0.55):, :]
            widths.append(float((lower.sum(axis=0) > 0).sum()))
        heights = [float((m.sum(axis=1) > 0).sum()) for m in raw]
        return gei, widths, heights

    @staticmethod
    def _hog(gei: np.ndarray, cells: int = 8, bins: int = 9) -> np.ndarray:
        gx = cv2.Sobel(gei, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gei, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.hypot(gx, gy)
        ang = np.mod(np.arctan2(gy, gx), math.pi * 2)
        h, w = gei.shape
        ch, cw = h // cells, w // cells
        feats = []
        for cy in range(cells):
            for cx in range(cells):
                m = mag[cy * ch:(cy + 1) * ch, cx * cw:(cx + 1) * cw].reshape(-1)
                a = ang[cy * ch:(cy + 1) * ch, cx * cw:(cx + 1) * cw].reshape(-1)
                hist, _ = np.histogram(a, bins=bins, range=(0, math.pi * 2), weights=m)
                feats.append(hist)
        return l2norm(np.concatenate(feats, axis=0).astype(np.float32))

    def _period_score(self, widths: List[float], fps: float = 25.0) -> float:
        """宽度序列自相关，估计是否存在稳定步态周期。"""
        if len(widths) < 6:
            return 0.0
        x = np.asarray(widths, dtype=np.float32)
        x = x - x.mean()
        if x.std() < 1e-6:
            return 0.0
        ac = np.correlate(x, x, mode='full')[len(x) - 1:]
        ac = ac / (ac[0] + 1e-9)
        lag_min = max(2, int(len(x) * 0.10))
        lag_max = max(lag_min + 1, int(len(x) * 0.75))
        return float(np.max(ac[lag_min:lag_max])) if lag_max > lag_min else 0.0

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        if sample.kind != 'frames' or not isinstance(sample.data, (list, tuple)):
            return QualityReport(0.0, False, {}, ['步态需要帧序列'])
        frames = sample.data
        if len(frames) < self.min_frames:
            return QualityReport(0.0, False, {'frames': len(frames)}, [f'帧数不足({len(frames)}/{self.min_frames})'])
        base = image_quality(ensure_gray(frames[0]))
        try:
            gei, widths, heights = self._gei(list(frames))
        except Exception as exc:
            return QualityReport(0.0, False, base.metrics, [f'步态处理失败: {exc}'])
        period = self._period_score(widths)
        height_std = float(np.std(heights) / max(np.mean(heights), 1.0))
        coverage = float((gei > 0.1).mean())
        metrics = dict(base.metrics)
        metrics.update({'frames': len(frames), 'period_score': period,
                        'height_stability': 1.0 - min(height_std, 1.0), 'gei_coverage': coverage})
        issues = list(base.issues)
        if period < 0.15:
            issues.append('未检测到稳定步态周期')
        if height_std > 0.25:
            issues.append('人体尺度跳变过大（可能是多人/镜头抖动）')
        score = 0.4 * (1.0 - min(height_std, 1.0)) + 0.35 * clip01(period / 0.6) + 0.25 * clip01(coverage / 0.3)
        return QualityReport(score=clip01(score), passed=bool(score >= 0.45 and period >= 0.15),
                             metrics=metrics, issues=issues)

    def extract(self, sample: BioSample) -> BioTemplate:
        report = self.quality(sample)
        if not report.passed:
            raise ValueError('步态质量不合格：' + '；'.join(report.issues or ['序列不足']))
        gei, widths, heights = self._gei(list(sample.data))
        hog = self._hog(gei)
        small = cv2.resize(gei, (16, 16), interpolation=cv2.INTER_AREA).reshape(-1)
        w = np.asarray(widths, dtype=np.float32)
        h = np.asarray(heights, dtype=np.float32)
        stride = float((w.max() - w.min()) / max(h.mean(), 1.0))
        aspect = float(w.mean() / max(h.mean(), 1.0))
        period = self._period_score(widths)
        stats = np.array([stride, aspect, period, float(w.std() / max(w.mean(), 1.0))], dtype=np.float32)
        feat = l2norm(np.concatenate([hog, small * 0.5], axis=0))
        return BioTemplate(
            modality=self.name, version=2,
            arrays={'embedding': feat.reshape(1, -1),
                    'stats': stats.reshape(1, -1),
                    'gei': cv2.resize(gei, (16, 16), interpolation=cv2.INTER_AREA).reshape(1, -1)},
            meta={'frames': len(sample.data), 'period_score': period, 'stride': stride, 'aspect': aspect},
            quality=report.score,
        )

    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        if 'embedding' not in a.arrays or 'embedding' not in b.arrays:
            return 0.0
        emb = cosine_score(a.arrays['embedding'].reshape(-1), b.arrays['embedding'].reshape(-1))
        stats_sim = 1.0
        if 'stats' in a.arrays and 'stats' in b.arrays:
            sa = np.asarray(a.arrays['stats'], dtype=np.float32).reshape(-1)
            sb = np.asarray(b.arrays['stats'], dtype=np.float32).reshape(-1)
            if sa.size == sb.size:
                # 体型/步幅这类正数特征用对数比，差异比余弦更敏感
                stats_sim = float(np.exp(-3.0 * np.mean(np.abs(np.log((np.abs(sa) + 1e-3) / (np.abs(sb) + 1e-3))))))
        ga = np.asarray(a.arrays.get('gei', np.zeros((1, 256))), dtype=np.float32).reshape(-1)
        gb = np.asarray(b.arrays.get('gei', np.zeros((1, 256))), dtype=np.float32).reshape(-1)
        gei_sim = 0.0
        if ga.size == gb.size and ga.size > 0:
            ba, bb = ga > 0.2, gb > 0.2
            union = float(np.logical_or(ba, bb).sum())
            gei_sim = float(np.logical_and(ba, bb).sum()) / union if union > 0 else 0.0
        return clip01(0.45 * emb + 0.40 * clip01(stats_sim) + 0.15 * gei_sim)

    def liveness(self, sample: BioSample) -> LivenessReport:
        report = self.quality(sample)
        return LivenessReport(
            passed=bool(report.passed), score=clip01(0.4 + 0.5 * report.score),
            mode='heuristic',
            reasons=['步态本身难以伪造，但视频回放可复现；需检测画面闪烁与镜头运动'],
        )
