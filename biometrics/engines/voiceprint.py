"""声纹模态引擎。

- **基线**：MFCC(20) + Δ + ΔΔ 的统计池化（均值/标准差）+ 对数梅尔谱均值，
  经 CMVN 后 L2 归一化，余弦比对。零模型文件即可运行。
- **可插拔**：``VoiceprintEngine(backend=...)`` 可注入 ECAPA-TDNN / WeSpeaker /
  Resemblyzer 等后端（输入 waveform, sr，输出定长向量），框架其余部分不变。
- **防录音重放**：频谱平坦度、高频能量、循环自相关三项启发式，仅作辅助信号，
  不替代专用 CM 系统。
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from ..base import ModalityEngine, clip01, cosine_score, l2norm
from ..types import BioSample, BioTemplate, LivenessReport, ModalitySpec, QualityReport
from . import audio_utils


VOICE_SPEC = ModalitySpec(
    name='voiceprint',
    label='声纹',
    kind='audio',
    description='MFCC 统计池化基线，支持注入 ECAPA-TDNN 等深度说话人嵌入后端。',
    hardware='驻极体麦克风阵列、USB 会议麦',
    supports_liveness=True,
    default_threshold=0.75,
    security_level=2,
)

SpeakerBackend = Callable[[np.ndarray, int], np.ndarray]


class VoiceprintEngine(ModalityEngine):
    spec = VOICE_SPEC

    def __init__(self, backend: Optional[SpeakerBackend] = None,
                 sample_rate: int = 16000, min_seconds: float = 1.0):
        self.backend = backend
        self.sample_rate = sample_rate
        self.min_seconds = min_seconds

    # ------------------------------------------------------------------
    def _load(self, sample: BioSample) -> Tuple[np.ndarray, int]:
        if sample.kind == 'audio':
            wav, sr = audio_utils.read_wav(sample.data)
        elif sample.kind == 'image':
            raise ValueError('声纹需要音频样本')
        else:
            wav, sr = audio_utils.read_wav(sample.data)
        wav, sr = audio_utils.resample(wav, sr, self.sample_rate)
        return wav, sr

    @staticmethod
    def _trim_silence(wav: np.ndarray, sr: int) -> np.ndarray:
        """按帧能量裁掉首尾静音，保留中间停顿。"""
        frame_len, hop = int(0.025 * sr), int(0.010 * sr)
        mask = audio_utils.vad_mask(wav, frame_len, hop)
        if not mask.any():
            return wav
        idx = np.where(mask)[0]
        start = max(int(idx[0] * hop) - frame_len // 2, 0)
        end = min(int(idx[-1] * hop) + frame_len, len(wav))
        return wav[start:end]

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        try:
            wav, sr = self._load(sample)
        except Exception as exc:
            return QualityReport(0.0, False, {}, [f'音频读取失败: {exc}'])
        report = audio_utils.audio_quality(wav, sr, self.min_seconds)
        if report.metrics.get('voiced_ratio', 0) < 0.12:
            report.passed = False
            report.issues.append('几乎无人声')
        return report

    def extract(self, sample: BioSample) -> BioTemplate:
        wav, sr = self._load(sample)
        wav = self._trim_silence(wav, sr)
        report = audio_utils.audio_quality(wav, sr, self.min_seconds)
        if not report.passed:
            raise ValueError('音频质量不合格：' + '；'.join(report.issues or ['未通过质量门控']))

        if self.backend is not None:
            emb = np.asarray(self.backend(wav, sr), dtype=np.float32)
            meta = {'backend': 'custom', 'duration': len(wav) / sr}
        else:
            frame_len, hop = int(0.025 * sr), int(0.010 * sr)
            mask = audio_utils.vad_mask(wav, frame_len, hop)
            feat = audio_utils.mfcc(wav, sr, n_mfcc=20, with_delta=True)
            if mask.size != len(feat):
                n = min(mask.size, len(feat))
                feat, mask = feat[:n], mask[:n]
            voiced = feat[mask] if mask.any() else feat
            # 统计池化：均值 + 标准差，兼顾音色（均值）与动态（方差）
            mean = voiced.mean(axis=0)
            std = voiced.std(axis=0)
            spec = audio_utils.power_spectrogram(wav, sr)
            bank = audio_utils.mel_filterbank(sr, 400, 26)
            logmel = np.log(np.maximum(spec @ bank.T, 1e-10))
            logmel_mean = logmel.mean(axis=0)
            pitch = audio_utils.pitch_stats(wav, sr)
            # 基频做对数压缩，避免赫兹量纲压过倒谱特征
            pitch = np.array([math.log1p(max(pitch[0], 0)), math.log1p(max(pitch[1], 0)),
                              math.log1p(max(pitch[2], 0)), math.log1p(max(pitch[3], 0)), pitch[4]],
                             dtype=np.float32)
            emb = np.concatenate([mean, std, logmel_mean, pitch], axis=0)
            meta = {'backend': 'mfcc-stats+pitch', 'frames': int(len(voiced)),
                    'f0_mean': float(pitch[0]), 'duration': len(wav) / sr}

        emb = l2norm(emb)
        return BioTemplate(
            modality=self.name,
            version=1,
            arrays={'embedding': emb.reshape(1, -1)},
            meta=meta,
            quality=report.score,
        )

    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        if 'embedding' not in a.arrays or 'embedding' not in b.arrays:
            return 0.0
        return cosine_score(a.arrays['embedding'].reshape(-1), b.arrays['embedding'].reshape(-1))

    # ------------------------------------------------------------------
    def liveness(self, sample: BioSample) -> LivenessReport:
        """录音重放启发式：过于平坦的频谱、缺失高频、强循环周期都提示可疑。"""
        try:
            wav, sr = self._load(sample)
        except Exception as exc:
            return LivenessReport(False, 0.0, 'heuristic', [f'音频读取失败: {exc}'])

        flatness = audio_utils.spectral_flatness(wav, sr)
        hf = audio_utils.high_freq_ratio(wav, sr, 3500.0)
        # 自相关找 0.4s 以上的强周期（循环播放特征）
        max_lag = min(len(wav) - 1, int(sr * 2.0))
        min_lag = int(sr * 0.4)
        periodicity = 0.0
        if max_lag > min_lag:
            x = wav - wav.mean()
            ac = np.correlate(x, x, mode='full')[len(x) - 1:]
            denom = ac[0] + 1e-9
            lag_range = ac[min_lag:max_lag]
            if lag_range.size:
                periodicity = float(np.max(lag_range) / denom)

        reasons = []
        score = 1.0
        if flatness > 0.55:
            score -= 0.25
            reasons.append('频谱过于平坦，疑似合成/回放')
        if hf < 0.08:
            score -= 0.20
            reasons.append('高频能量缺失，疑似扬声器回放')
        if periodicity > 0.55:
            score -= 0.35
            reasons.append('检测到强循环周期，疑似录音重放')
        if len(wav) / sr < 0.8:
            score -= 0.20
            reasons.append('语音过短，无法可靠判断')

        passed = score >= 0.55
        return LivenessReport(
            passed=passed, score=clip01(score), mode='heuristic',
            reasons=reasons + ['声纹 PAD 为启发式，生产环境建议叠加文本相关挑战'],
            spoof_type='replay' if periodicity > 0.55 else '',
        )

    @staticmethod
    def default_backend_hint() -> Dict[str, Any]:
        return {
            'recommended': 'ECAPA-TDNN / WeSpeaker / Resemblyzer',
            'env': 'CAOS_SPEAKER_ONNX（可选，指向导出的 ONNX 说话人模型）',
        }
