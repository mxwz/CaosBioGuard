"""合成生物特征样本，用于无采集硬件环境下的自动化测试与演示。

注意：合成图只验证「算法链路能跑通、同源样本比异源更相似」，不代表真实场景精度。
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def iris_image(seed: int = 0, size: int = 256, shift: Tuple[int, int] = (0, 0),
               noise: float = 3.0) -> np.ndarray:
    cx, cy = size // 2 + shift[0], size // 2 + shift[1]
    rp, ri = size * 0.10, size * 0.25
    img = np.full((size, size), 190, np.uint8)
    if cv2 is None:
        return img
    cv2.circle(img, (cx, cy), int(ri * 1.6), 225, -1)
    rng = _rng(seed)
    # 虹膜纹理：放射状纤维 + 同心环
    for k in range(90):
        ang = rng.uniform(0, 2 * math.pi)
        r0 = rng.uniform(rp * 1.05, ri * 0.95)
        r1 = min(ri, r0 + rng.uniform(2, 10))
        p0 = (int(cx + r0 * math.cos(ang)), int(cy + r0 * math.sin(ang)))
        p1 = (int(cx + r1 * math.cos(ang)), int(cy + r1 * math.sin(ang)))
        cv2.line(img, p0, p1, int(rng.integers(40, 120)), 1)
    for r in np.linspace(rp * 1.15, ri * 0.92, 7):
        cv2.circle(img, (cx, cy), int(r), int(90 + rng.integers(0, 45)), 1)
    cv2.circle(img, (cx, cy), int(rp), 18, -1)
    cv2.circle(img, (cx, cy), int(ri), 70, 2)
    img = np.clip(img.astype(np.float32) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (3, 3), 0.8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def palmprint_image(seed: int = 0, size: int = 160, noise: float = 4.0) -> np.ndarray:
    rng = _rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    theta = rng.uniform(0, math.pi)
    freq = rng.uniform(7.0, 12.0)
    phase = rng.uniform(0, 2 * math.pi)
    ridge = np.cos(2 * math.pi * (x * np.cos(theta) + y * np.sin(theta)) / freq + phase)
    img = 120 + 45 * ridge
    gray = np.clip(img + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    if cv2 is not None:
        gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        # 主线：三条不同曲率的弧
        for i in range(3):
            pts = np.array([[int(size * 0.1) + t,
                             int(size * (0.25 + 0.18 * i + 0.04 * math.sin(t / 8))) +
                             int(18 * math.sin(t / 10 + i))] for t in range(0, size, 4)], np.int32)
            cv2.polylines(gray_bgr, [pts], False, (45, 45, 45), 2)
        return gray_bgr
    return gray


def vein_image(seed: int = 0, size: int = 160, noise: float = 3.0) -> np.ndarray:
    rng = _rng(seed)
    img = np.full((size, size), 28, np.float32)

    def branch(x, y, ang, length, depth):
        if depth <= 0 or length < 6:
            return
        x2 = x + length * math.cos(ang)
        y2 = y + length * math.sin(ang)
        if cv2 is not None:
            cv2.line(img, (int(x), int(y)), (int(x2), int(y2)), 150, 2)
        branch(x2, y2, ang + rng.normal(0, 0.35), length * 0.76, depth - 1)
        if rng.random() < 0.7:
            branch(x2, y2, ang - rng.normal(0.5, 0.2), length * 0.6, depth - 1)

    branch(size * (0.3 + 0.1 * (seed % 4)), size * 0.95, -math.pi / 2 + 0.15 * seed, size * 0.35, 5)
    branch(size * (0.6 - 0.05 * (seed % 3)), size * 0.95, -math.pi / 2 - 0.4 + 0.2 * seed, size * 0.25, 4)
    for k in range(seed % 3 + 1):
        branch(size * 0.5, size * (0.15 + 0.08 * k), math.pi / 2, size * 0.18, 3)
    img = cv2.GaussianBlur(img, (3, 3), 1.0) + rng.normal(0, noise, img.shape)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def retina_image(seed: int = 0, size: int = 220, noise: float = 2.0) -> np.ndarray:
    rng = _rng(seed)
    img = np.full((size, size, 3), (40, 70, 90), np.uint8)  # 橙红眼底
    if cv2 is None:
        return img
    cv2.circle(img, (size // 2, size // 2), int(size * 0.45), (60, 100, 130), -1)
    disc_x = int(size * (0.62 + 0.06 * (seed % 4)))
    disc_y = int(size * (0.42 + 0.04 * (seed % 3)))
    cv2.circle(img, (disc_x, disc_y), int(size * (0.09 + 0.01 * (seed % 3))), (200, 210, 190), -1)  # 视盘
    for k in range(8 + seed % 6):
        ang = rng.uniform(0, 2 * math.pi)
        x, y = disc_x, disc_y
        length = size * rng.uniform(0.03, 0.07)
        for step in range(rng.integers(4, 10)):
            nx = x + math.cos(ang) * length
            ny = y + math.sin(ang) * length
            if not (0 <= nx < size and 0 <= ny < size):
                break
            cv2.line(img, (int(x), int(y)), (int(nx), int(ny)), (35, 55, 60), 2)
            if rng.random() < 0.6:
                cv2.line(img, (int(nx), int(ny)),
                         (int(nx + rng.normal(0, 12)), int(ny + rng.normal(0, 12))), (35, 55, 60), 1)
            x, y = nx, ny
            ang += rng.normal(0, 0.25)
    noise_arr = rng.normal(0, noise, img.shape)
    return np.clip(img.astype(np.float32) + noise_arr, 0, 255).astype(np.uint8)


def fingerprint_image(seed: int = 0, size: int = 300, noise: float = 3.0) -> np.ndarray:
    rng = _rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    cx, cy = size / 2, size / 2
    dist = np.hypot(x - cx, y - cy)
    ang = np.arctan2(y - cy, x - cx)
    period = 9.0 + rng.uniform(-1, 1)
    pattern = seed % 3
    if pattern == 0:      # whorl
        phase_field = dist / period + 0.9 * ang
    elif pattern == 1:    # arch
        phase_field = (0.75 * x + 0.25 * y) / period + 0.0008 * (x - cx) ** 2 / period
    else:                 # loop
        phase_field = (0.5 * dist + 0.08 * x) / period + 0.4 * ang
    ridge = np.cos(2 * math.pi * phase_field + rng.uniform(0, 1))
    mask = dist < size * 0.44
    img = np.full((size, size), 235, np.float32)
    img[mask] = 120 + 55 * ridge[mask]
    # 断点/细节点
    for _ in range(12):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(size * 0.1, size * 0.4)
        px, py = int(cx + r * math.cos(a)), int(cy + r * math.sin(a))
        cv2.circle(img, (px, py), int(rng.integers(3, 6)), 200, -1)
    img = cv2.GaussianBlur(img, (3, 3), 0.6) + rng.normal(0, noise, img.shape)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def gait_frames(seed: int = 0, count: int = 32, size: Tuple[int, int] = (96, 128),
                phase: float = 0.0, width_scale: float = 1.0,
                cycles: float = 1.0) -> List[np.ndarray]:
    """生成正面走路剪影序列（左右腿交替、身体上下起伏）。"""
    w, h = size
    rng = _rng(seed)
    frames = []
    for i in range(count):
        img = np.full((h, w), 245, np.uint8)
        if cv2 is None:
            frames.append(img)
            continue
        t = i / count * 2 * math.pi * cycles + phase
        cx = w // 2 + int(6 * math.sin(t))
        cy = int(h * 0.45 + 4 * abs(math.cos(t)))
        body_w = int(w * 0.22 * width_scale)
        body_h = int(h * 0.30)
        cv2.ellipse(img, (cx, cy), (body_w, body_h), 0, 0, 360, 20, -1)
        head_r = int(w * 0.09 * width_scale)
        cv2.circle(img, (cx, cy - body_h - head_r), head_r, 20, -1)
        leg_spread = 0.9 + 0.55 * abs(math.sin(t))
        for side in (-1, 1):
            hip = (cx + side * int(body_w * 0.35), cy + body_h)
            knee = (cx + side * int(body_w * 0.62 * leg_spread), cy + body_h + int(h * 0.20))
            foot = (cx + side * int(body_w * 1.15 * leg_spread), h - 12)
            cv2.line(img, hip, knee, 20, 6)
            cv2.line(img, knee, foot, 20, 5)
        img = np.clip(img.astype(np.float32) + rng.normal(0, 1.5, img.shape), 0, 255).astype(np.uint8)
        frames.append(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    return frames


def signature_strokes(seed: int = 0, points: int = 60) -> Tuple[List[dict], np.ndarray]:
    """生成一段连笔签名轨迹与对应静态图。"""
    rng = _rng(seed)
    strokes = []
    t = 0.0
    pts = []
    x, y = 30.0, 60.0
    angle = -0.3
    for i in range(points):
        angle += rng.normal(0, 0.28)
        speed = rng.uniform(1.0, 6.0)
        x += speed * math.cos(angle)
        y += speed * math.sin(angle) * 0.6
        x = float(np.clip(x, 10, 230))
        y = float(np.clip(y, 10, 120))
        t += rng.uniform(0.006, 0.02)
        pressure = float(np.clip(0.5 + 0.3 * math.sin(i / 6) + rng.normal(0, 0.06), 0.05, 0.95))
        strokes.append({'x': x, 'y': y, 't': t, 'pressure': pressure, 'stroke': i // 20})
        pts.append((int(x), int(y)))
    img = np.full((140, 250), 250, np.uint8)
    if cv2 is not None:
        for i in range(1, len(pts)):
            if i % 20 == 0:
                continue
            cv2.line(img, pts[i - 1], pts[i], 20, 2)
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if cv2 is not None else img
    return strokes, img


def voice_wave(seed: int = 0, seconds: float = 2.0, sr: int = 16000, speaker: int = 0) -> np.ndarray:
    """用谐波+共振峰模拟一段元音。

    ``speaker`` 决定音高/共振峰（身份），``seed`` 只决定噪声与初相（同人不同次采集）。
    """
    rng = _rng(seed * 1000 + 17)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    base_f0 = 92.0 + 23.0 * speaker
    f0 = base_f0 * (1 + 0.03 * np.sin(2 * math.pi * 0.8 * t)) + rng.normal(0, 0.4, n)
    f0_mean = float(np.mean(f0))
    formants = [620 + 120 * speaker, 1100 + 180 * speaker, 2400 + 260 * speaker]
    sig = np.zeros(n, np.float32)
    for k in range(1, 40):
        if k * f0_mean > sr / 2:
            break
        amp = 1.0 / k
        for f in formants:
            if abs(k * f0_mean - f) < 180:
                amp *= 2.4
        sig += amp * np.sin(2 * math.pi * k * f0_mean * t + rng.uniform(0, 2 * math.pi))
    sig *= (0.6 + 0.4 * np.sin(2 * math.pi * 2.5 * t))
    sig += rng.normal(0, 0.01, n)
    sig = sig / (np.max(np.abs(sig)) + 1e-6) * 0.8
    return sig.astype(np.float32)
