"""模态引擎基类与通用数学/图像工具。

所有引擎只需实现 4 个方法：``quality`` / ``extract`` / ``compare`` / ``liveness``，
其余（注册、存储、融合、同步、UI）由框架统一处理。
"""

from __future__ import annotations

import abc
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .types import BioSample, BioTemplate, LivenessReport, MatchResult, ModalitySpec, QualityReport


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


EPS = 1e-9


def l2norm(vec: np.ndarray) -> np.ndarray:
    """L2 归一化（0 向量安全）。"""
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(arr))
    if n < EPS:
        return arr
    return arr / n


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度，返回 [-1, 1]。"""
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    if a.size != b.size or a.size == 0:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < EPS:
        return 0.0
    return float(np.clip(np.dot(a, b) / denom, -1.0, 1.0))


def cosine_score(a: np.ndarray, b: np.ndarray) -> float:
    """把余弦相似度映射到 [0, 1]，供融合层统一使用。"""
    return float(np.clip(cosine_similarity(a, b), 0.0, 1.0))


def clip01(value: float) -> float:
    return float(np.clip(float(value), 0.0, 1.0))


def sigmoid(x: float, center: float = 0.0, scale: float = 1.0) -> float:
    return float(1.0 / (1.0 + math.exp(-(x - center) / max(scale, EPS))))


def ensure_gray(img: Any) -> np.ndarray:
    """转为 uint8 灰度图，兼容 BGR / BGRA / 灰度 / float。"""
    if img is None:
        raise ValueError('空图像')
    arr = np.asarray(img)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        if arr.shape[2] == 1:
            return arr[:, :, 0]
        return _cvt(arr, arr.shape[2])
    raise ValueError(f'不支持的图像维度: {arr.shape}')


def _cvt(arr: np.ndarray, channels: int) -> np.ndarray:
    """不依赖 cv2 的灰度转换（BT.601 加权），避免核心包强绑定 OpenCV。"""
    if channels >= 3:
        b, g, r = arr[:, :, 0].astype(np.float32), arr[:, :, 1].astype(np.float32), arr[:, :, 2].astype(np.float32)
        return np.clip(0.114 * b + 0.587 * g + 0.299 * r, 0, 255).astype(np.uint8)
    return arr[:, :, 0]


def resize_gray(img: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    """缩放灰度图（优先 cv2，缺失时用最近邻）。``size`` 为 (w, h)。"""
    try:
        import cv2
        return cv2.resize(img, size, interpolation=cv2.INTER_AREA if img.shape[1] > size[0] else cv2.INTER_LINEAR)
    except Exception:
        h, w = size[1], size[0]
        ys = np.linspace(0, img.shape[0] - 1, h).astype(int)
        xs = np.linspace(0, img.shape[1] - 1, w).astype(int)
        return img[np.ix_(ys, xs)]


def normalize_minmax(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    lo, hi = float(np.min(arr)), float(np.max(arr))
    if hi - lo < EPS:
        return np.zeros_like(arr)
    return (arr - lo) / (hi - lo)


def entropy(gray: np.ndarray) -> float:
    hist = np.bincount(np.asarray(gray, dtype=np.uint8).reshape(-1), minlength=256).astype(np.float64)
    p = hist / max(hist.sum(), 1.0)
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum() / 8.0)


def blur_score(gray: np.ndarray) -> float:
    """拉普拉斯方差归一化到 0~1（越大越清晰）。"""
    try:
        import cv2
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        var = float(lap.var())
    except Exception:
        g = gray.astype(np.float32)
        lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
        var = float(lap.var())
    # 经验尺度：方差 0~800 覆盖「糊 → 清晰」
    return clip01(math.log1p(var) / math.log1p(800.0))


def image_quality(gray: np.ndarray, min_side: int = 64) -> QualityReport:
    """通用图像质量：清晰度、曝光、对比度、信息熵、尺寸。"""
    g = ensure_gray(gray)
    h, w = g.shape[:2]
    metrics = {
        'width': float(w),
        'height': float(h),
        'sharpness': blur_score(g),
        'brightness': float(g.mean()) / 255.0,
        'contrast': float(g.std()) / 128.0,
        'entropy': entropy(g),
    }
    issues: List[str] = []
    score = 0.0
    score += 0.34 * metrics['sharpness']
    # 亮度以 0.5 为最优，偏离越多扣分
    score += 0.22 * clip01(1.0 - abs(metrics['brightness'] - 0.5) * 2.2)
    score += 0.20 * clip01(metrics['contrast'])
    score += 0.24 * clip01(metrics['entropy'])
    if min(h, w) < min_side:
        issues.append(f'分辨率过低({w}x{h})')
        score *= 0.5
    if metrics['sharpness'] < 0.22:
        issues.append('图像模糊')
    if metrics['brightness'] < 0.12:
        issues.append('曝光不足')
    elif metrics['brightness'] > 0.92:
        issues.append('曝光过度')
    if metrics['contrast'] < 0.12:
        issues.append('对比度过低')
    return QualityReport(score=clip01(score), passed=bool(score >= 0.45 and not issues), metrics=metrics, issues=issues)


def aggregate_vectors(vectors: Sequence[np.ndarray], weights: Optional[Sequence[float]] = None) -> np.ndarray:
    """多帧/多样本向量聚合：加权平均后重新归一化，抑制单帧噪声。"""
    arrs = [np.asarray(v, dtype=np.float32).reshape(-1) for v in vectors if v is not None]
    if not arrs:
        return np.zeros(0, dtype=np.float32)
    dim = arrs[0].size
    arrs = [a for a in arrs if a.size == dim]
    if weights is None:
        weights = [1.0] * len(arrs)
    w = np.asarray(weights, dtype=np.float32)[: len(arrs)]
    if w.sum() < EPS:
        w = np.ones_like(w)
    stacked = np.stack(arrs, axis=0)
    out = (stacked * w[:, None]).sum(axis=0) / w.sum()
    return l2norm(out)


# ---------------------------------------------------------------------------
# 引擎基类
# ---------------------------------------------------------------------------


class ModalityEngine(abc.ABC):
    """生物特征模态引擎抽象基类。"""

    spec: ModalitySpec

    # -- 能力 -----------------------------------------------------------
    def check_available(self) -> Tuple[bool, str]:
        """返回 (是否可用, 原因)。默认可用；缺少模型/硬件的引擎应覆盖。"""
        return True, ''

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    def threshold(self) -> float:
        return self.spec.default_threshold

    # -- 核心四件事 -----------------------------------------------------
    @abc.abstractmethod
    def quality(self, sample: BioSample) -> QualityReport:
        """评估采集质量。"""

    @abc.abstractmethod
    def extract(self, sample: BioSample) -> BioTemplate:
        """提取不可逆模板。"""

    @abc.abstractmethod
    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        """返回 0~1 相似度（越大越像）。"""

    def liveness(self, sample: BioSample) -> LivenessReport:
        """活体检测。硬件级模态默认交由采集端保证，这里返回 disabled。"""
        return LivenessReport(
            passed=True, score=1.0, mode='disabled',
            reasons=['该模态由采集硬件保证活体，软件层未启用 PAD'],
        )

    # -- 多模板聚合 -----------------------------------------------------
    def aggregate(self, templates: Sequence[BioTemplate]) -> BioTemplate:
        """默认实现：对同名数组做加权平均，返回聚合模板。"""
        valid = [t for t in templates if t is not None]
        if not valid:
            raise ValueError('没有可用模板')
        keys = set(valid[0].arrays.keys())
        for t in valid[1:]:
            keys &= set(t.arrays.keys())
        arrays: Dict[str, np.ndarray] = {}
        for key in sorted(keys):
            arrays[key] = aggregate_vectors(
                [t.arrays[key] for t in valid],
                [max(t.quality, 0.01) for t in valid],
            ).reshape(valid[0].arrays[key].shape)
        best = max(valid, key=lambda t: t.quality)
        return BioTemplate(
            modality=self.name,
            version=best.version,
            arrays=arrays,
            meta={'samples': len(valid), 'aggregated': True},
            quality=float(np.mean([t.quality for t in valid])),
        )

    def match(self, probe: BioTemplate, gallery: BioTemplate, subject: str = '',
              threshold: Optional[float] = None) -> MatchResult:
        thr = self.threshold if threshold is None else float(threshold)
        score = float(self.compare(probe, gallery))
        return MatchResult(
            modality=self.name, score=score, threshold=thr,
            passed=bool(score >= thr), subject=subject, quality=probe.quality,
        )


class ImageEngine(ModalityEngine):
    """图像类模态的公共实现：统一做灰度化与质量评估。"""

    def quality(self, sample: BioSample) -> QualityReport:
        img = self._image(sample)
        return image_quality(img)

    def _image(self, sample: BioSample) -> np.ndarray:
        if sample.kind != 'image':
            raise ValueError(f'{self.label}需要图像样本，收到 {sample.kind}')
        return ensure_gray(sample.data)


# ---------------------------------------------------------------------------
# 人脸模板的通用工具（供 face engine / gallery / 融合使用）
# ---------------------------------------------------------------------------


class TemplateGallery:
    """通用 1:N 模板库匹配器。

    除了「最高分」，还返回「与第二名的分差（margin）」，用于降低撞脸误放行：
    真实用户通常与自己的模板明显高于其他人，攻击者/陌生人分数分布更平坦。
    """

    def __init__(self, entries: Iterable[Tuple[str, BioTemplate]]):
        self.entries: List[Tuple[str, BioTemplate]] = list(entries)

    def match(self, probe: BioTemplate, compare_fn, threshold: float,
              margin_threshold: float = 0.0) -> MatchResult:
        scores = []
        for subject, tmpl in self.entries:
            scores.append((float(compare_fn(probe, tmpl)), subject))
        if not scores:
            return MatchResult(probe.modality, 0.0, threshold, False, '', probe.quality)
        scores.sort(key=lambda x: x[0], reverse=True)
        best_score, best_subject = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        margin = best_score - second
        passed = best_score >= threshold and margin >= margin_threshold
        return MatchResult(
            modality=probe.modality, score=best_score, threshold=threshold,
            passed=bool(passed), subject=best_subject, quality=probe.quality,
            margin=margin,
            details={'runner_up': scores[1][1] if len(scores) > 1 else '', 'candidates': len(scores)},
        )


# ---------------------------------------------------------------------------
# 分数校准
# ---------------------------------------------------------------------------


class ScoreCalibrator:
    """把原始分数拉成「可读概率」，用于 UI 展示与跨模态融合。

    采用 Platt scaling 的简化形式：``p = sigmoid((score - center) / scale)``，
    ``center`` 默认取阈值，``scale`` 越小曲线越陡。没有标注数据时这是安全的
    单调映射，不会改变排序与阈值判定。
    """

    def __init__(self, center: float = 0.6, scale: float = 0.12):
        self.center = float(center)
        self.scale = max(float(scale), EPS)

    def __call__(self, score: float) -> float:
        return sigmoid(float(score), self.center, self.scale)

    def describe(self) -> Dict[str, float]:
        return {'center': self.center, 'scale': self.scale}
