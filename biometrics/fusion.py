"""多模态分数融合与阈值评估。

支持的融合规则：
- ``weighted``：质量加权平均，适合「人脸 + 声纹」这类连续分数；
- ``any``：任一模态通过即可（便捷通行，安全性最低）；
- ``all``：全部模态通过（高安全场景，如金库/机房）；
- ``sequential``：按安全等级从低到高依次验证，前序失败立即拒绝（体验与安全的折中）。

同时提供 FAR/FRR/EER 评估函数，便于用真实采集数据校准阈值，而不是凭感觉写死。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

from .types import MatchResult


@dataclass
class FusionPolicy:
    rule: str = 'weighted'
    threshold: float = 0.60
    weights: Dict[str, float] = field(default_factory=dict)
    min_factors: int = 1
    quality_power: float = 1.0       # 质量权重指数：0 表示忽略质量
    require_liveness: bool = True
    liveness_threshold: float = 0.60

    def to_dict(self) -> dict:
        return {
            'rule': self.rule, 'threshold': self.threshold, 'weights': dict(self.weights),
            'min_factors': self.min_factors, 'quality_power': self.quality_power,
            'require_liveness': self.require_liveness,
        }


@dataclass
class FusionResult:
    score: float
    passed: bool
    rule: str
    threshold: float
    factors: List[dict] = field(default_factory=list)
    reason: str = ''
    liveness_ok: bool = True

    def to_dict(self) -> dict:
        return {
            'score': round(float(self.score), 4),
            'passed': bool(self.passed),
            'rule': self.rule,
            'threshold': round(float(self.threshold), 4),
            'reason': self.reason,
            'liveness_ok': bool(self.liveness_ok),
            'factors': self.factors,
        }


_RULES = ('weighted', 'any', 'all', 'sequential')


def fuse(results: Sequence[MatchResult], policy: Optional[FusionPolicy] = None,
         liveness_ok: bool = True) -> FusionResult:
    """把多个模态的比对结果融合成一个最终判决。"""
    policy = policy or FusionPolicy()
    if policy.rule not in _RULES:
        raise ValueError(f'未知融合规则: {policy.rule}')

    valid = [r for r in results if r is not None]
    factors = [r.to_dict() for r in valid]
    if not valid:
        return FusionResult(0.0, False, policy.rule, policy.threshold, factors, '没有有效模态结果', liveness_ok)

    if policy.require_liveness and not liveness_ok:
        return FusionResult(0.0, False, policy.rule, policy.threshold, factors, '活体检测未通过', liveness_ok)

    scores = np.asarray([r.score for r in valid], dtype=np.float32)
    if policy.rule == 'any':
        score = float(scores.max())
        passed = bool(score >= policy.threshold)
        reason = '任一模态通过' if passed else '所有模态均未通过'
    elif policy.rule == 'all':
        score = float(scores.min())
        passed = bool(np.all(scores >= policy.threshold))
        reason = '全部模态通过' if passed else '存在未通过模态'
    elif policy.rule == 'sequential':
        score = float(scores[-1])
        passed = bool(np.all(scores >= policy.threshold))
        reason = '顺序验证通过' if passed else '顺序验证中断'
    else:  # weighted
        weights = np.asarray([
            float(policy.weights.get(r.modality, 1.0)) * max(float(r.quality), 0.05) ** policy.quality_power
            for r in valid
        ], dtype=np.float32)
        if weights.sum() <= 0:
            weights = np.ones_like(weights)
        score = float((scores * weights).sum() / weights.sum())
        passed_count = int(np.sum(scores >= policy.threshold * 0.9))
        passed = bool(score >= policy.threshold and passed_count >= policy.min_factors)
        reason = f'加权融合 {passed_count}/{len(valid)} 个模态达标'

    return FusionResult(
        score=float(np.clip(score, 0.0, 1.0)), passed=passed, rule=policy.rule,
        threshold=policy.threshold, factors=factors, reason=reason, liveness_ok=liveness_ok,
    )


# ---------------------------------------------------------------------------
# 阈值评估
# ---------------------------------------------------------------------------


def evaluate_thresholds(genuine_scores: Iterable[float], impostor_scores: Iterable[float],
                        steps: int = 200) -> dict:
    """在给定分数分布上扫描阈值，返回 FAR/FRR 曲线与 EER。

    真实上线前应采集至少几百对同人/异人样本，用本函数选阈值，而不是拍脑袋。
    """
    genuine = np.asarray(list(genuine_scores), dtype=np.float32)
    impostor = np.asarray(list(impostor_scores), dtype=np.float32)
    if genuine.size == 0 or impostor.size == 0:
        return {'error': '需要同时提供 genuine 与 impostor 分数'}

    thresholds = np.linspace(0.0, 1.0, steps)
    far = np.array([float(np.mean(impostor >= t)) for t in thresholds])
    frr = np.array([float(np.mean(genuine < t)) for t in thresholds])
    eer_idx = int(np.argmin(np.abs(far - frr)))
    eer = float((far[eer_idx] + frr[eer_idx]) / 2)
    best_idx = int(np.argmin(np.abs(far - frr)))
    # 等错误率对应的阈值
    eer_threshold = float(thresholds[best_idx])
    # 满足 FAR <= 1% 的最低阈值（门禁常用工作点）
    target = np.where(far <= 0.01)[0]
    far1_threshold = float(thresholds[target[0]]) if target.size else 1.0
    return {
        'eer': eer,
        'eer_threshold': eer_threshold,
        'far_at_1pct': float(far[target[0]]) if target.size else 0.0,
        'threshold_at_far_1pct': far1_threshold,
        'genuine_mean': float(genuine.mean()),
        'impostor_mean': float(impostor.mean()),
        'thresholds': thresholds.tolist(),
        'far': far.tolist(),
        'frr': frr.tolist(),
    }


def quality_weighted_average(scores: Sequence[float], qualities: Sequence[float]) -> float:
    w = np.asarray(qualities, dtype=np.float32)
    s = np.asarray(scores, dtype=np.float32)
    if w.sum() <= 0:
        return float(s.mean()) if s.size else 0.0
    return float((s * w).sum() / w.sum())
