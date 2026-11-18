"""签名模态引擎：静态笔迹 + 动态书写过程双通道。

- **静态**：二值化 → 归一化画布 → HOG + 投影 + 密度网格 + 笔宽/倾斜特征；
- **动态**：轨迹重采样 → 速度/加速度/曲率/压力统计 + DTW 轨迹距离；
- 动态签名包含「书写节奏与压力」这类难以模仿的行为特征，安全等级高于静态签名。

输入约定：``BioSample.strokes(strokes, image=None)``，``strokes`` 可为
``[{'x':..,'y':..,'t':..,'pressure':..}, ...]`` 或 ``(N,4)`` 数组。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..base import ImageEngine, clip01, cosine_score, ensure_gray, image_quality, l2norm
from ..types import BioSample, BioTemplate, LivenessReport, ModalitySpec, QualityReport

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


SIGN_SPEC = ModalitySpec(
    name='signature',
    label='签名',
    kind='strokes',
    description='静态笔迹 + 动态书写过程（速度/压力/DTW），支持签字板与纸面扫描。',
    hardware='电磁式签字板（推荐，带压感）、高拍仪',
    supports_liveness=True,
    default_threshold=0.60,
    security_level=3,
)


class SignatureEngine(ImageEngine):
    spec = SIGN_SPEC

    def __init__(self, canvas: Tuple[int, int] = (128, 64), resample_points: int = 32):
        self.canvas_w, self.canvas_h = canvas
        self.resample_points = resample_points

    # ------------------------------------------------------------------
    # 输入解析
    # ------------------------------------------------------------------
    @staticmethod
    def _points(sample: BioSample) -> Optional[np.ndarray]:
        data = sample.data
        if sample.kind == 'strokes' and isinstance(data, dict):
            raw = data.get('strokes')
        else:
            raw = data
        if raw is None:
            return None
        if isinstance(raw, dict):
            raw = raw.get('points')
        if raw is None:
            return None
        try:
            if isinstance(raw, np.ndarray):
                pts = raw.astype(np.float32)
            else:
                rows = []
                for p in raw:
                    if isinstance(p, dict):
                        rows.append([p.get('x', 0), p.get('y', 0), p.get('t', len(rows) * 0.01),
                                     p.get('pressure', 0.5), p.get('stroke', 0)])
                    else:
                        rows.append(list(p)[:5])
                pts = np.asarray(rows, dtype=np.float32)
        except Exception:
            return None
        if pts.ndim != 2 or pts.shape[0] < 5:
            return None
        if pts.shape[1] < 4:
            pts = np.pad(pts, ((0, 0), (0, 4 - pts.shape[1])), constant_values=0.5)
        return pts

    def _static_image(self, sample: BioSample) -> Optional[np.ndarray]:
        if sample.kind == 'strokes' and isinstance(sample.data, dict):
            img = sample.data.get('image')
            if img is not None:
                return ensure_gray(img)
            return None
        if sample.kind == 'image':
            return ensure_gray(sample.data)
        return None

    # ------------------------------------------------------------------
    # 静态特征
# ------------------------------------------------------------------
    def _normalize_static(self, gray: np.ndarray) -> Tuple[np.ndarray, float]:
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        thr = int(np.percentile(blur, 30))
        ink = (blur < thr).astype(np.uint8)
        # 若墨迹占比过大，说明是浅底深字/反相，取反
        if ink.mean() > 0.55:
            ink = 1 - ink
        ys, xs = np.where(ink > 0)
        if len(xs) == 0:
            raise ValueError('未检测到笔迹')
        x1, x2, y1, y2 = xs.min(), xs.max(), ys.min(), ys.max()
        crop = ink[y1:y2 + 1, x1:x2 + 1]
        h, w = crop.shape
        scale = min((self.canvas_h - 6) / max(h, 1), (self.canvas_w - 6) / max(w, 1))
        nw, nh = max(2, int(w * scale)), max(2, int(h * scale))
        resized = cv2.resize(crop.astype(np.float32), (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((self.canvas_h, self.canvas_w), dtype=np.float32)
        ox, oy = (self.canvas_w - nw) // 2, (self.canvas_h - nh) // 2
        canvas[oy:oy + nh, ox:ox + nw] = (resized > 0.35).astype(np.float32)
        return canvas, float(crop.mean())

    @staticmethod
    def _hog_static(ink: np.ndarray, cells: int = 8, bins: int = 9) -> np.ndarray:
        gx = cv2.Sobel(ink, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(ink, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.hypot(gx, gy)
        ang = np.mod(np.arctan2(gy, gx), math.pi * 2)
        h, w = ink.shape
        ch, cw = max(h // cells, 1), max(w // cells, 1)
        feats = []
        for cy in range(cells):
            for cx in range(cells):
                y0, y1 = cy * ch, min((cy + 1) * ch, h)
                x0, x1 = cx * cw, min((cx + 1) * cw, w)
                m = mag[y0:y1, x0:x1].reshape(-1)
                a = ang[y0:y1, x0:x1].reshape(-1)
                hist, _ = np.histogram(a, bins=bins, range=(0, math.pi * 2), weights=m)
                feats.append(hist)
        return l2norm(np.concatenate(feats, axis=0).astype(np.float32))

    def _static_features(self, canvas: np.ndarray, ink_ratio: float) -> np.ndarray:
        hog = self._hog_static(canvas)
        hproj = canvas.sum(axis=1)
        vproj = canvas.sum(axis=0)
        hproj = np.interp(np.linspace(0, len(hproj) - 1, 16), np.arange(len(hproj)), hproj)
        vproj = np.interp(np.linspace(0, len(vproj) - 1, 16), np.arange(len(vproj)), vproj)
        hproj = hproj / (hproj.sum() + 1e-6)
        vproj = vproj / (vproj.sum() + 1e-6)
        grid = cv2.resize(canvas, (8, 4), interpolation=cv2.INTER_AREA).reshape(-1)
        # 倾斜：二阶中心矩
        ys, xs = np.where(canvas > 0)
        if len(xs) > 2:
            cx, cy = xs.mean(), ys.mean()
            mu20 = np.mean((xs - cx) ** 2)
            mu02 = np.mean((ys - cy) ** 2)
            mu11 = np.mean((xs - cx) * (ys - cy))
            slant = mu11 / math.sqrt(max(mu20 * mu02, 1e-6))
        else:
            slant = 0.0
        width = float(cv2.distanceTransform(canvas.astype(np.uint8), cv2.DIST_L2, 3)[canvas > 0].mean()) \
            if canvas.sum() > 0 else 0.0
        stats = np.array([ink_ratio, slant, width / 4.0, canvas.mean()], dtype=np.float32)
        return l2norm(np.concatenate([hog, hproj, vproj, grid, stats], axis=0))

    # ------------------------------------------------------------------
    # 动态特征
    # ------------------------------------------------------------------
    def _resample(self, pts: np.ndarray) -> np.ndarray:
        xy = pts[:, :2].astype(np.float32)
        xy = xy - xy.min(axis=0)
        span = np.maximum(xy.max(axis=0), 1.0)
        xy = xy / span
        dist = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        if dist[-1] < 1e-6:
            raise ValueError('轨迹长度为 0')
        target = np.linspace(0, dist[-1], self.resample_points)
        rx = np.interp(target, dist, xy[:, 0])
        ry = np.interp(target, dist, xy[:, 1])
        pressure = pts[:, 3] if pts.shape[1] > 3 else np.full(len(pts), 0.5)
        rp = np.interp(target, dist, pressure.astype(np.float32))
        return np.stack([rx, ry, rp], axis=1).astype(np.float32)

    def _dynamic_features(self, pts: np.ndarray, traj: np.ndarray) -> np.ndarray:
        t = pts[:, 2].astype(np.float32) if pts.shape[1] > 2 else np.arange(len(pts)) * 0.01
        dt = np.diff(t)
        dt[dt <= 0] = np.median(dt[dt > 0]).item() if np.any(dt > 0) else 0.01
        dxy = np.diff(pts[:, :2], axis=0)
        speed = np.linalg.norm(dxy, axis=1) / np.maximum(dt, 1e-3)
        acc = np.diff(speed) / np.maximum(dt[1:], 1e-3) if len(speed) > 1 else np.array([0.0])
        ang = np.unwrap(np.arctan2(dxy[:, 1], dxy[:, 0]))
        curv = np.abs(np.diff(ang) / np.maximum(dt[1:], 1e-3)) if len(ang) > 1 else np.array([0.0])
        pressure = pts[:, 3] if pts.shape[1] > 3 else np.full(len(pts), 0.5)
        strokes = pts[:, 4] if pts.shape[1] > 4 else np.zeros(len(pts))
        stroke_count = len(np.unique(strokes)) if strokes.any() else 1
        stats = np.array([
            float(np.mean(speed)), float(np.std(speed)),
            float(np.mean(acc)), float(np.std(acc)),
            float(np.mean(curv)), float(np.std(curv)),
            float(np.mean(pressure)), float(np.std(pressure)),
            float(t[-1] - t[0]), float(len(pts)), float(stroke_count),
            float(np.std(traj[:, 0])), float(np.std(traj[:, 1])),
            float(np.mean(np.abs(dxy[:, 1])) / (np.mean(np.abs(dxy[:, 0])) + 1e-6)),
        ], dtype=np.float32)
        # 对数压缩量纲差异
        stats = np.sign(stats) * np.log1p(np.abs(stats))
        return l2norm(stats)

    @staticmethod
    def _dtw(a: np.ndarray, b: np.ndarray) -> float:
        n, m = len(a), len(b)
        cost = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
        cost[0, 0] = 0.0
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                d = float(np.linalg.norm(a[i - 1] - b[j - 1]))
                cost[i, j] = d + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])
        return float(cost[n, m] / max(n + m, 1))

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        pts = self._points(sample)
        img = self._static_image(sample)
        if pts is not None:
            duration = float(pts[-1, 2] - pts[0, 2]) if pts.shape[1] > 2 else len(pts) * 0.01
            pressure_std = float(np.std(pts[:, 3])) if pts.shape[1] > 3 else 0.0
            metrics = {'points': float(len(pts)), 'duration': duration, 'pressure_std': pressure_std}
            issues = []
            if len(pts) < 15:
                issues.append('轨迹点过少')
            if duration < 0.3:
                issues.append('书写时长过短')
            score = clip01(0.45 * min(len(pts) / 80.0, 1.0) + 0.35 * min(duration / 1.5, 1.0) + 0.2 * min(pressure_std / 0.25, 1.0))
            return QualityReport(score=score, passed=bool(score >= 0.45 and not issues), metrics=metrics, issues=issues)
        if img is None:
            return QualityReport(0.0, False, {}, ['缺少笔迹图像或轨迹点'])
        base = image_quality(img)
        try:
            canvas, ink_ratio = self._normalize_static(img)
        except Exception as exc:
            return QualityReport(0.0, False, base.metrics, [f'签名处理失败: {exc}'])
        metrics = dict(base.metrics)
        metrics['ink_ratio'] = ink_ratio
        issues = list(base.issues)
        if ink_ratio < 0.02:
            issues.append('墨迹过少')
        elif ink_ratio > 0.5:
            issues.append('墨迹过重/背景干扰')
        score = 0.6 * base.score + 0.4 * clip01(1.0 - abs(ink_ratio - 0.08) / 0.2)
        return QualityReport(score=clip01(score), passed=bool(score >= 0.45 and not issues), metrics=metrics, issues=issues)

    def extract(self, sample: BioSample) -> BioTemplate:
        report = self.quality(sample)
        if not report.passed:
            raise ValueError('签名质量不合格：' + '；'.join(report.issues or ['笔迹不足']))
        pts = self._points(sample)
        arrays: Dict[str, np.ndarray] = {}
        meta: Dict[str, Any] = {'dynamic': pts is not None}
        if pts is not None:
            traj = self._resample(pts)
            arrays['traj'] = traj.reshape(-1, 3)
            arrays['dynamic_feat'] = self._dynamic_features(pts, traj).reshape(1, -1)
        img = self._static_image(sample)
        if img is not None:
            canvas, ink_ratio = self._normalize_static(img)
            arrays['embedding'] = self._static_features(canvas, ink_ratio).reshape(1, -1)
            arrays['image'] = cv2.resize(canvas, (32, 16), interpolation=cv2.INTER_AREA).reshape(1, -1)
        if not arrays:
            raise ValueError('没有可用的签名特征')
        return BioTemplate(modality=self.name, version=2, arrays=arrays, meta=meta, quality=report.score)

    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        scores = []
        if 'dynamic_feat' in a.arrays and 'dynamic_feat' in b.arrays:
            cos = cosine_score(a.arrays['dynamic_feat'].reshape(-1), b.arrays['dynamic_feat'].reshape(-1))
            dtw_score = 1.0
            if 'traj' in a.arrays and 'traj' in b.arrays:
                d = self._dtw(a.arrays['traj'], b.arrays['traj'])
                # 轨迹已归一化到 [0,1]，平均点距 0.05 以内视为高度一致
                dtw_score = clip01(math.exp(-d / 0.12))
            scores.append(0.55 * cos + 0.45 * dtw_score)
        if 'embedding' in a.arrays and 'embedding' in b.arrays:
            cos = cosine_score(a.arrays['embedding'].reshape(-1), b.arrays['embedding'].reshape(-1))
            img_corr = 0.0
            if 'image' in a.arrays and 'image' in b.arrays:
                ia = a.arrays['image'].reshape(-1)
                ib = b.arrays['image'].reshape(-1)
                if ia.size == ib.size and ia.std() > 1e-6 and ib.std() > 1e-6:
                    img_corr = clip01((float(np.corrcoef(ia, ib)[0, 1]) + 1) / 2)
            scores.append(0.8 * cos + 0.2 * img_corr)
        return clip01(float(np.mean(scores))) if scores else 0.0

    def liveness(self, sample: BioSample) -> LivenessReport:
        pts = self._points(sample)
        if pts is not None:
            pressure = pts[:, 3] if pts.shape[1] > 3 else np.zeros(len(pts))
            variability = float(np.std(pressure))
            return LivenessReport(
                passed=bool(len(pts) >= 15 and variability >= 0.02),
                score=clip01(0.6 + 0.4 * min(variability / 0.2, 1.0)),
                mode='active',
                reasons=['动态签名包含压力/节奏等行为特征，可有效抵抗静态复制'],
            )
        return LivenessReport(
            passed=True, score=0.55, mode='heuristic',
            reasons=['静态签名无法验证书写过程，建议使用压感签字板'],
        )
