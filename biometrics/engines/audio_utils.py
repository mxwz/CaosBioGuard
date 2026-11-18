"""音频读取与声纹前端（纯 numpy 实现，不依赖 librosa）。

生产环境建议接入 ECAPA-TDNN / WeSpeaker 等说话人嵌入模型；本模块提供的
MFCC + 统计池化是**零依赖基线**，保证没有模型文件时系统仍可跑通全链路，
有模型时通过 ``SpeakerBackend`` 直接替换嵌入。
"""

from __future__ import annotations

import io
import math
import os
import wave
from typing import Optional, Tuple

import numpy as np

EPS = 1e-10


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------


def read_wav(source) -> Tuple[np.ndarray, int]:
    """读取 WAV 为单声道 float32（[-1, 1]）。

    ``source`` 可以是路径、bytes、文件对象，或 ``(waveform, sr)`` 元组。
    """
    if isinstance(source, tuple) and len(source) == 2:
        wav, sr = source
        wav = np.asarray(wav, dtype=np.float32)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        return wav, int(sr)

    if isinstance(source, (bytes, bytearray)):
        fh = io.BytesIO(source)
        should_close = True
    elif hasattr(source, 'read'):
        fh = source
        should_close = False
    else:
        path = os.fspath(source)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        fh = open(path, 'rb')
        should_close = True

    try:
        with wave.open(fh, 'rb') as wf:
            sr = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
    finally:
        if should_close:
            fh.close()

    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype='<i4').astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f'不支持的 WAV 位深: {width * 8} bit')

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(data, dtype=np.float32), int(sr)


def resample(wav: np.ndarray, sr: int, target: int = 16000) -> Tuple[np.ndarray, int]:
    """线性重采样（语音带宽足够；高保真场景请换 soxr）。"""
    if sr == target or len(wav) == 0:
        return wav.astype(np.float32), target
    n_out = int(round(len(wav) * target / float(sr)))
    if n_out <= 1:
        return np.zeros(max(n_out, 0), dtype=np.float32), target
    x_old = np.linspace(0, 1, len(wav), endpoint=False)
    x_new = np.linspace(0, 1, n_out, endpoint=False)
    return np.interp(x_new, x_old, wav).astype(np.float32), target


# ---------------------------------------------------------------------------
# 基础信号处理
# ---------------------------------------------------------------------------


def frame_signal(wav: np.ndarray, frame_len: int, hop: int) -> np.ndarray:
    if len(wav) < frame_len:
        wav = np.pad(wav, (0, frame_len - len(wav)))
    n = 1 + (len(wav) - frame_len) // hop
    idx = np.arange(frame_len)[None, :] + hop * np.arange(n)[:, None]
    return wav[idx]


def power_spectrogram(wav: np.ndarray, sr: int, n_fft: int = 400, hop: int = 160) -> np.ndarray:
    frames = frame_signal(wav, n_fft, hop) * np.hanning(n_fft)[None, :]
    spec = np.fft.rfft(frames, n=n_fft, axis=1)
    return (np.abs(spec) ** 2).astype(np.float32)


def hz_to_mel(hz):
    return 2595.0 * np.log10(1.0 + np.asarray(hz, dtype=np.float32) / 700.0)


def mel_to_hz(mel):
    return 700.0 * (10.0 ** (np.asarray(mel, dtype=np.float32) / 2595.0) - 1.0)


def mel_filterbank(sr: int, n_fft: int, n_mels: int = 26, fmin: float = 20.0,
                   fmax: Optional[float] = None) -> np.ndarray:
    fmax = fmax or sr / 2.0
    mel_pts = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
    hz_pts = mel_to_hz(mel_pts)
    bins = np.floor((n_fft + 1) * hz_pts / sr).astype(int)
    bins = np.clip(bins, 0, n_fft // 2)
    bank = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(1, n_mels + 1):
        left, center, right = bins[m - 1], bins[m], bins[m + 1]
        if center <= left:
            center = left + 1
        if right <= center:
            right = center + 1
        for k in range(left, min(center, bank.shape[1])):
            bank[m - 1, k] = (k - left) / max(center - left, 1)
        for k in range(center, min(right, bank.shape[1])):
            bank[m - 1, k] = (right - k) / max(right - center, 1)
    return bank


def dct_matrix(n_out: int, n_in: int) -> np.ndarray:
    k = np.arange(n_out)[:, None]
    n = np.arange(n_in)[None, :]
    mat = np.cos(np.pi * k * (2 * n + 1) / (2.0 * n_in)) * np.sqrt(2.0 / n_in)
    mat[0, :] = np.sqrt(1.0 / n_in)
    return mat.astype(np.float32)


def mfcc(wav: np.ndarray, sr: int, n_mfcc: int = 20, n_mels: int = 26,
         n_fft: int = 400, hop: int = 160, with_delta: bool = True) -> np.ndarray:
    """返回 (帧数, n_mfcc[+2*n_mfcc]) 的 MFCC 特征。"""
    spec = power_spectrogram(wav, sr, n_fft, hop)
    bank = mel_filterbank(sr, n_fft, n_mels)
    mel = spec @ bank.T
    logmel = np.log(np.maximum(mel, EPS))
    ceps = logmel @ dct_matrix(n_mfcc, n_mels).T
    # 倒谱均值归一化（CMVN），抵消通道/增益差异
    ceps = ceps - ceps.mean(axis=0, keepdims=True)
    if not with_delta:
        return ceps.astype(np.float32)
    delta = _delta(ceps)
    delta2 = _delta(delta)
    return np.concatenate([ceps, delta, delta2], axis=1).astype(np.float32)


def _delta(feat: np.ndarray, width: int = 2) -> np.ndarray:
    if len(feat) < 2:
        return np.zeros_like(feat)
    pad = np.pad(feat, ((width, width), (0, 0)), mode='edge')
    out = np.zeros_like(feat)
    denom = 2 * sum(i * i for i in range(1, width + 1))
    for i in range(1, width + 1):
        out += i * (pad[width + i: width + i + len(feat)] - pad[width - i: width - i + len(feat)])
    return out / max(denom, 1)


# ---------------------------------------------------------------------------
# 质量 / 活体辅助
# ---------------------------------------------------------------------------


def frame_energy(wav: np.ndarray, frame_len: int = 400, hop: int = 160) -> np.ndarray:
    frames = frame_signal(wav, frame_len, hop)
    return np.mean(frames ** 2, axis=1)


def vad_mask(wav: np.ndarray, frame_len: int = 400, hop: int = 160,
             rel_threshold: float = 0.25) -> np.ndarray:
    energy = frame_energy(wav, frame_len, hop)
    if energy.size == 0 or energy.max() < EPS:
        return np.zeros(len(energy), dtype=bool)
    thr = max(float(energy.max()) * rel_threshold, 1e-6)
    return energy >= thr


def spectral_flatness(wav: np.ndarray, sr: int) -> float:
    spec = power_spectrogram(wav, sr) + EPS
    geo = np.exp(np.mean(np.log(spec), axis=1))
    arith = np.mean(spec, axis=1)
    ratio = geo / np.maximum(arith, EPS)
    return float(np.clip(np.mean(ratio), 0, 1))


def high_freq_ratio(wav: np.ndarray, sr: int, cut_hz: float = 4000.0) -> float:
    spec = power_spectrogram(wav, sr)
    freqs = np.fft.rfftfreq(400, 1.0 / sr)
    total = spec.sum() + EPS
    high = spec[:, freqs >= min(cut_hz, sr / 2.0)].sum()
    return float(np.clip(high / total, 0, 1))


def pitch_stats(wav: np.ndarray, sr: int, fmin: float = 60.0, fmax: float = 400.0) -> np.ndarray:
    """基频统计（均值/标准差/范围/浊音比例），补充 MFCC 缺失的说话人音高信息。"""
    frame_len = int(0.040 * sr)
    hop = int(0.020 * sr)
    frames = frame_signal(wav, frame_len, hop)
    if frames.shape[0] == 0:
        return np.zeros(5, dtype=np.float32)
    lag_min = max(2, int(sr / fmax))
    lag_max = min(frame_len - 1, int(sr / fmin))
    f0s = []
    for frame in frames:
        frame = frame - frame.mean()
        if float(np.sqrt(np.mean(frame ** 2))) < 1e-4:
            continue
        ac = np.correlate(frame, frame, mode='full')[frame_len - 1:]
        if ac[0] < EPS:
            continue
        seg = ac[lag_min:lag_max]
        if seg.size == 0:
            continue
        peak = float(seg.max() / (ac[0] + EPS))
        if peak < 0.28:
            continue
        lag = lag_min + int(np.argmax(seg))
        f0s.append(sr / float(lag))
    if not f0s:
        return np.zeros(5, dtype=np.float32)
    arr = np.asarray(f0s, dtype=np.float32)
    return np.array([arr.mean(), arr.std(), arr.min(), arr.max(), len(f0s) / max(frames.shape[0], 1)],
                    dtype=np.float32)


def audio_quality(wav: np.ndarray, sr: int, min_seconds: float = 1.2) -> 'QualityReport':
    from ..types import QualityReport

    duration = len(wav) / float(sr) if sr else 0.0
    rms = float(np.sqrt(np.mean(wav ** 2))) if len(wav) else 0.0
    peak = float(np.max(np.abs(wav))) if len(wav) else 0.0
    clip_ratio = float(np.mean(np.abs(wav) >= 0.985)) if len(wav) else 0.0
    voiced = float(np.mean(vad_mask(wav, int(0.025 * sr), int(0.010 * sr)))) if len(wav) else 0.0
    flatness = spectral_flatness(wav, sr) if len(wav) else 0.0
    hf = high_freq_ratio(wav, sr) if len(wav) else 0.0
    snr = 20 * math.log10(max(rms, EPS) / max(peak * (1 - voiced) * 0.05 + EPS, EPS) + 1.0)

    metrics = {
        'duration': duration, 'rms': rms, 'peak': peak,
        'clip_ratio': clip_ratio, 'voiced_ratio': voiced,
        'flatness': flatness, 'high_freq_ratio': hf, 'snr_db': snr,
    }
    issues = []
    score = 0.0
    score += 0.30 * float(np.clip(duration / max(min_seconds * 3.0, 1.0), 0, 1))
    score += 0.22 * float(np.clip(voiced / 0.55, 0, 1))
    score += 0.22 * float(np.clip(rms / 0.12, 0, 1))
    score += 0.14 * float(np.clip((snr - 5) / 25.0, 0, 1))
    score += 0.12 * float(np.clip(1.0 - clip_ratio * 8.0, 0, 1))
    if duration < min_seconds:
        issues.append('语音过短')
    if rms < 0.01:
        issues.append('音量过低')
    if clip_ratio > 0.08:
        issues.append('音频削波')
    if voiced < 0.15:
        issues.append('有效语音过少')
    return QualityReport(score=float(np.clip(score, 0, 1)), passed=bool(score >= 0.45 and not issues),
                         metrics=metrics, issues=issues)
