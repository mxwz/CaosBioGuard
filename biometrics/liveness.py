"""活体检测（PAD）统一门禁，重点解决「与人脸识别的兼容性」。

旧实现的问题：
1. 直接把 bbox 裁成矩形喂给 224×224 模型 → 长宽比失真，模型分布漂移；
2. 阈值写死 0.75，且假设 ``probability[1]`` 一定是真人概率；
3. 模型缺失时直接跳过活体，攻击面完全敞开；
4. 没有时间维度，单帧误判就会导致一次错误放行/拒绝。

本模块提供：
- ``crop_face``：方形扩边裁剪 + 关键点对齐（112/224 参考点），保证与训练分布一致；
- ``FaceLivenessDetector``：模型优先，缺失时启发式降级，并显式标注 ``mode``；
- ``TemporalGuard``：EMA 平滑 + 连续帧确认 + 人脸框稳定性；
- ``FacePadGate``：把上述能力组合成「先活体、后比对」的硬门禁，并提供三种策略
  （strict / degraded / off），由配置决定缺模型时是拒绝还是降级放行。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .types import LivenessReport

EPS = 1e-9

# ArcFace 5 点参考坐标（112×112），放大到 224 时乘 2
ARC_REF_112 = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float32)


@dataclass
class LivenessPolicy:
    mode: str = 'degraded'            # strict / degraded / off
    passive_threshold: float = 0.72
    heuristic_threshold: float = 0.55
    require_active: bool = False
    ema_alpha: float = 0.35
    consecutive: int = 3
    bbox_jitter_max: float = 0.18     # 相对人脸宽度的抖动上限
    active_timeout: float = 8.0

    def to_dict(self) -> dict:
        return {
            'mode': self.mode, 'passive_threshold': self.passive_threshold,
            'heuristic_threshold': self.heuristic_threshold,
            'require_active': self.require_active, 'consecutive': self.consecutive,
        }


# ---------------------------------------------------------------------------
# 人脸裁剪 / 对齐
# ---------------------------------------------------------------------------


def crop_face(frame: np.ndarray, bbox: Sequence[float],
              landmarks: Optional[np.ndarray] = None,
              margin: float = 0.28, size: int = 224, align: bool = True) -> np.ndarray:
    """把人脸裁成正方形并（可选）按 5 点做相似变换对齐。

    ``margin`` 为相对人脸边长的扩边比例，保留额头/下巴/耳侧上下文，
    与 Silent-Face 等 PAD 模型的训练裁剪保持一致。
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    side = max(x2 - x1, y2 - y1) * (1.0 + 2 * margin)
    half = side / 2.0
    sx1, sy1 = int(max(0, cx - half)), int(max(0, cy - half))
    sx2, sy2 = int(min(w, cx + half)), int(min(h, cy + half))
    patch = frame[sy1:sy2, sx1:sx2]
    if patch.size == 0:
        return np.zeros((size, size, 3), dtype=np.uint8)

    if align and landmarks is not None:
        pts = np.asarray(landmarks, dtype=np.float32)
        if pts.shape[0] >= 5:
            src = pts[:5]
            dst = ARC_REF_112 * (size / 112.0)
            try:
                import cv2
                mat, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
                if mat is not None:
                    return cv2.warpAffine(frame, mat, (size, size), borderMode=cv2.BORDER_REPLICATE)
            except Exception:
                pass

    try:
        import cv2
        return cv2.resize(patch, (size, size), interpolation=cv2.INTER_LINEAR)
    except Exception:
        ys = np.linspace(0, patch.shape[0] - 1, size).astype(int)
        xs = np.linspace(0, patch.shape[1] - 1, size).astype(int)
        return patch[np.ix_(ys, xs)]


# ---------------------------------------------------------------------------
# 被动活体
# ---------------------------------------------------------------------------


class FaceLivenessDetector:
    """模型优先的被动活体检测器。"""

    def __init__(self, model: Any = None, policy: Optional[LivenessPolicy] = None):
        self.model = model
        self.policy = policy or LivenessPolicy()

    @property
    def has_model(self) -> bool:
        return self.model is not None

    def _model_score(self, patch: np.ndarray) -> Tuple[float, str]:
        """兼容不同模型的输出：二分类 softmax / 单 logit。"""
        label, prob = self.model.predict_frame(patch)
        arr = np.asarray(prob).reshape(-1).astype(np.float32)
        if arr.size >= 2:
            # 约定 index=1 为真人；若标签与概率方向矛盾则按标签修正
            score = float(arr[1])
            if str(label).lower() in ('genuine', 'real', 'live', '1') and score < 0.5:
                score = 1.0 - score
        else:
            score = float(1.0 / (1.0 + math.exp(-float(arr[0]))))
        score = float(np.clip(score, 0, 1))
        return score, ('Genuine' if score >= self.policy.passive_threshold else 'Spoofing')

    @staticmethod
    def _heuristic_score(patch: np.ndarray) -> Tuple[float, Dict[str, float], List[str]]:
        """无模型时的弱检测：清晰度 + 屏幕摩尔纹 + 色彩/高光 + 边界。

        只作为「降级信号」，不能当成强保证；调用方必须看 ``mode``。
        """
        try:
            import cv2
        except Exception:
            return 0.5, {}, ['缺少 opencv，无法做启发式活体']
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if patch.ndim == 3 else patch
        lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        sharp = float(np.clip(math.log1p(lap) / math.log1p(1200), 0, 1))

        # FFT 高频占比 + 周期峰（屏幕像素栅格/摩尔纹）
        spec = np.abs(np.fft.fftshift(np.fft.fft2(gray.astype(np.float32))))
        h, w = spec.shape
        cy, cx = h // 2, w // 2
        r = max(6, min(h, w) // 12)
        spec[cy - r:cy + r, cx - r:cx + r] = 0
        total = float(spec.sum()) + EPS
        high = float(spec.sum()) / total
        # 排除低频后，最高单峰占比越高越像屏幕栅格
        peak = float(spec.max()) / total

        color = 0.0
        if patch.ndim == 3:
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            color = float(hsv[:, :, 1].mean()) / 255.0

        spec_ratio = float(np.clip((high - 0.55) / 0.4, 0, 1))
        peak_ratio = float(np.clip((peak - 0.02) / 0.08, 0, 1))
        score = 0.42 * sharp + 0.30 * (1.0 - spec_ratio) + 0.20 * (1.0 - peak_ratio) + 0.08 * min(color / 0.5, 1.0)
        reasons = []
        if peak_ratio > 0.5:
            reasons.append('频谱出现强周期峰，疑似屏幕翻拍')
        if sharp < 0.25:
            reasons.append('画面过于平滑，疑似纸质打印')
        return float(np.clip(score, 0, 1)), {
            'sharpness': sharp, 'high_freq_ratio': spec_ratio, 'spectral_peak': peak_ratio, 'saturation': color,
        }, reasons

    def evaluate(self, frame: np.ndarray, bbox: Sequence[float],
                 landmarks: Optional[np.ndarray] = None) -> LivenessReport:
        t0 = time.perf_counter()
        patch = crop_face(frame, bbox, landmarks, margin=0.28, size=224)
        if self.model is not None:
            try:
                score, label = self._model_score(patch)
                passed = score >= self.policy.passive_threshold
                report = LivenessReport(
                    passed=passed, score=score, mode='model',
                    reasons=[f'PAD 模型判定 {label}'],
                    spoof_type='' if passed else 'print/screen',
                )
            except Exception as exc:
                score, metrics, reasons = self._heuristic_score(patch)
                passed = score >= self.policy.heuristic_threshold
                report = LivenessReport(passed=passed, score=score, mode='heuristic',
                                        reasons=reasons + [f'模型推理失败，降级启发式: {exc}'])
        else:
            score, metrics, reasons = self._heuristic_score(patch)
            passed = score >= self.policy.heuristic_threshold
            report = LivenessReport(passed=passed, score=score, mode='heuristic', reasons=reasons)
        report.latency_ms = (time.perf_counter() - t0) * 1000.0
        return report


# ---------------------------------------------------------------------------
# 时间一致性
# ---------------------------------------------------------------------------


class TemporalGuard:
    """对连续帧的活体分数做 EMA 与「连续通过」确认，抑制单帧抖动。"""

    def __init__(self, policy: Optional[LivenessPolicy] = None):
        self.policy = policy or LivenessPolicy()
        self.ema = 0.0
        self.streak = 0
        self.last_box: Optional[np.ndarray] = None

    def reset(self) -> None:
        self.ema = 0.0
        self.streak = 0
        self.last_box = None

    def update(self, report: LivenessReport, bbox: Optional[Sequence[float]] = None) -> LivenessReport:
        alpha = self.policy.ema_alpha
        self.ema = alpha * report.score + (1 - alpha) * self.ema if self.ema else report.score
        stable = True
        if bbox is not None:
            box = np.asarray(bbox, dtype=np.float32)
            if self.last_box is not None and self.last_box.shape == box.shape:
                width = max(box[2] - box[0], 1.0)
                jitter = float(np.max(np.abs(box - self.last_box)) / width)
                stable = jitter <= self.policy.bbox_jitter_max
            self.last_box = box

        if report.passed and stable:
            self.streak += 1
        else:
            self.streak = 0

        # 降级模式按启发式阈值确认；否则 EMA 会被 0.72 的模型阈值永久否决
        gate = self.policy.passive_threshold if report.mode.startswith('model') else self.policy.heuristic_threshold
        smoothed = LivenessReport(
            passed=bool(self.ema >= gate * 0.95 and self.streak >= self.policy.consecutive),
            score=float(self.ema),
            mode=report.mode + '+temporal',
            reasons=list(report.reasons) + [
                f'连续通过 {self.streak}/{self.policy.consecutive}',
                '人脸框稳定' if stable else '人脸框抖动过大',
            ],
            spoof_type=report.spoof_type,
            latency_ms=report.latency_ms,
        )
        return smoothed


# ---------------------------------------------------------------------------
# 主动挑战（转头）
# ---------------------------------------------------------------------------


def _yaw_from_landmarks(landmarks: np.ndarray) -> float:
    pts = np.asarray(landmarks, dtype=np.float32)
    if pts.shape[0] < 5:
        return 0.0
    left, right, nose = pts[0], pts[1], pts[2]
    eye_mid = (left + right) / 2
    eye_dist = float(np.linalg.norm(right - left)) + EPS
    return float((nose[0] - eye_mid[0]) / eye_dist)


class ActiveChallenge:
    """转头挑战状态机（无需眨眼模型，5 点关键点即可）。

    流程：正脸 → 左转 → 右转 → 完成。每步有超时，UI 可读取 ``progress_text``
    显示引导语，避免用户不知道要做什么。
    """

    STEPS = ('center', 'turn_left', 'turn_right', 'done')

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self.reset()

    def reset(self) -> None:
        self.step = 0
        self.started_at = time.time()
        self.last_yaw = 0.0
        self.done = False

    @property
    def progress_text(self) -> str:
        return {
            'center': '请正对镜头',
            'turn_left': '请向左转头',
            'turn_right': '请向右转头',
            'done': '验证完成',
        }[self.STEPS[min(self.step, len(self.STEPS) - 1)]]

    def update(self, landmarks: Optional[np.ndarray]) -> bool:
        if self.done:
            return True
        if time.time() - self.started_at > self.timeout:
            self.reset()
            return False
        if landmarks is None:
            return False
        yaw = _yaw_from_landmarks(landmarks)
        self.last_yaw = yaw
        current = self.STEPS[self.step]
        if current == 'center' and abs(yaw) < 0.12:
            self.step += 1
            self.started_at = time.time()
        elif current == 'turn_left' and yaw < -0.20:
            self.step += 1
            self.started_at = time.time()
        elif current == 'turn_right' and yaw > 0.20:
            self.step += 1
            self.done = True
        return self.done


# ---------------------------------------------------------------------------
# 门禁
# ---------------------------------------------------------------------------


class FacePadGate:
    """人脸识别前的活体硬门禁。

    ``mode``：
    - ``strict``：无模型/未通过 → 直接拒绝；
    - ``degraded``（默认）：无模型 → 启发式 + 时间一致性，并在日志中标记降级；
    - ``off``：只记录不拦截（仅建议在调试环境使用）。
    """

    def __init__(self, detector: FaceLivenessDetector, policy: Optional[LivenessPolicy] = None):
        self.detector = detector
        self.policy = policy or LivenessPolicy()
        self.temporal = TemporalGuard(self.policy)
        self.active = ActiveChallenge(self.policy.active_timeout) if self.policy.require_active else None

    def reset(self) -> None:
        self.temporal.reset()
        if self.active:
            self.active.reset()

    def check(self, frame: np.ndarray, bbox: Sequence[float],
              landmarks: Optional[np.ndarray] = None) -> LivenessReport:
        if self.policy.mode == 'off':
            return LivenessReport(True, 1.0, 'disabled', ['活体检测已关闭'])

        report = self.detector.evaluate(frame, bbox, landmarks)
        report = self.temporal.update(report, bbox)

        if self.active is not None:
            ok = self.active.update(landmarks)
            report.reasons.append(self.active.progress_text)
            if not ok and self.active.step < 3:
                report.passed = False
            elif ok:
                report.passed = True
                report.mode = 'hybrid'

        # 模型缺失时的策略裁决
        if not self.detector.has_model and report.mode.startswith('heuristic'):
            if self.policy.mode == 'strict':
                report.passed = False
                report.reasons.append('未加载 PAD 模型，严格模式拒绝放行')
            elif self.policy.mode == 'degraded':
                report.reasons.append('未加载 PAD 模型，降级模式放行（需记录审计）')
                report.score = max(report.score, 0.55)
        return report


def liveness_compatibility(model_available: bool, face_model_available: bool) -> Dict[str, Any]:
    """给运维/UI 的兼容性自检结果。"""
    issues: List[str] = []
    if not face_model_available:
        issues.append('人脸特征模型不可用：无法进行 1:N 比对')
    if not model_available:
        issues.append('PAD 模型缺失：仅能使用启发式活体，建议尽快补齐 _14_best.pth.tar')
    return {
        'face_model': bool(face_model_available),
        'pad_model': bool(model_available),
        'compatible': bool(face_model_available),
        'issues': issues,
        'recommended_crop': 'square + 0.28 margin + 5-point align @224',
    }
