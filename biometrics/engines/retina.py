"""视网膜模态引擎：血管分割 + 结构特征比对。

眼底视网膜血管图案终身稳定、不可复制，是安全等级最高的模态之一。
本实现面向已配准的眼底彩照/绿通道图：

1. 绿通道 + CLAHE；2. 多方向匹配滤波增强血管；3. 自适应阈值得到血管图；
4. 以视盘为中心的 8x8 密度、方向直方图、分叉数、平均宽度、盒维数作为特征。

生产环境若已有深度学习血管分割模型（如 U-Net/DDSA），把二值图直接替换
``_vessel_map`` 即可，其余特征与比对逻辑保持不变。
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


RETINA_SPEC = ModalitySpec(
    name='retina',
    label='视网膜',
    kind='image',
    description='眼底血管分割 + 密度/方向/分叉/盒维数特征，安全等级最高。',
    hardware='眼底相机（免散瞳推荐）、近红外眼底模块',
    supports_liveness=False,
    default_threshold=0.65,
    security_level=5,
)


class RetinaEngine(ImageEngine):
    spec = RETINA_SPEC

    def __init__(self, size: int = 256):
        self.size = size

    def check_available(self) -> Tuple[bool, str]:
        if cv2 is None:
            return False, '缺少 opencv-python'
        return True, ''

    @staticmethod
    def _green(img: np.ndarray) -> np.ndarray:
        arr = np.asarray(img)
        if arr.ndim == 3 and arr.shape[2] >= 3:
            return arr[:, :, 1]
        return ensure_gray(arr)

    def _vessel_map(self, gray: np.ndarray) -> np.ndarray:
        gray = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
        base = gray.astype(np.float32) / 255.0
        responses = []
        for i in range(12):
            theta = i * math.pi / 12
            kern = self._matched_kernel(theta, length=9, sigma=1.6)
            responses.append(cv2.filter2D(base, cv2.CV_32F, kern))
        resp = np.max(np.stack(responses, axis=0), axis=0)
        resp = cv2.GaussianBlur(resp, (0, 0), 1.0)
        resp_n = cv2.normalize(resp, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        binary = cv2.adaptiveThreshold(resp_n, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 15, -2)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        return resp, (binary > 0).astype(np.uint8)

    @staticmethod
    def _matched_kernel(theta: float, length: int = 9, sigma: float = 1.6) -> np.ndarray:
        half = length // 2
        y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float32)
        xr = x * math.cos(theta) + y * math.sin(theta)
        yr = -x * math.sin(theta) + y * math.cos(theta)
        k = np.exp(-(yr ** 2) / (2 * sigma ** 2))
        k = k - k.mean()
        return k.astype(np.float32)

    def _features(self, gray: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        vessel, binary = self._vessel_map(gray)
        # 8x8 密度
        grid = cv2.resize(binary.astype(np.float32), (8, 8), interpolation=cv2.INTER_AREA).reshape(-1)
        # 方向直方图
        gx = cv2.Sobel(vessel, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(vessel, cv2.CV_32F, 0, 1, ksize=3)
        ang = np.arctan2(gy, gx) % math.pi
        hist, _ = np.histogram(ang[binary > 0], bins=12, range=(0, math.pi))
        hist = hist.astype(np.float32) / max(hist.sum(), 1)
        # 分叉数（骨架交叉数）
        skel = self._skeleton(binary)
        p = np.pad(skel, 1)
        c = p[1:-1, 1:-1]
        neigh = [p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:],
                 p[2:, 2:], p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2]]
        cn = sum(np.abs(neigh[i].astype(np.int8) - neigh[i + 1].astype(np.int8)) for i in range(8)) / 2.0
        branches = float(np.sum((c > 0) & (cn >= 3)))
        area = float(binary.sum()) + 1e-6
        branches_n = branches / (area / 1000.0)
        # 平均宽度
        width = float(cv2.distanceTransform(binary.astype(np.uint8), cv2.DIST_L2, 3)[binary > 0].mean()) \
            if binary.sum() > 0 else 0.0
        # 盒维数
        fd = self._box_dimension(binary)
        stats = np.array([branches_n, width, fd, float(binary.mean())], dtype=np.float32)
        feat = l2norm(np.concatenate([grid, hist, stats], axis=0))
        return feat, binary, stats

    @staticmethod
    def _skeleton(binary: np.ndarray) -> np.ndarray:
        img = binary.astype(np.uint8)
        skel = np.zeros_like(img)
        element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        for _ in range(60):
            erode = cv2.erode(img, element)
            opening = cv2.dilate(erode, element)
            skel |= (img - opening)
            img = erode
            if img.sum() == 0:
                break
        return skel

    @staticmethod
    def _box_dimension(binary: np.ndarray) -> float:
        sizes = [2, 4, 8, 16, 32]
        counts = []
        for s in sizes:
            h, w = binary.shape[0] // s, binary.shape[1] // s
            if h == 0 or w == 0:
                continue
            blk = binary[:h * s, :w * s].reshape(h, s, w, s)
            counts.append(int((blk.any(axis=(1, 3))).sum()))
        if len(counts) < 2 or min(counts) <= 0:
            return 0.0
        xs = np.log(1.0 / np.asarray(sizes[:len(counts)], dtype=np.float32))
        ys = np.log(np.asarray(counts, dtype=np.float32))
        return float(np.polyfit(xs, ys, 1)[0])

    # ------------------------------------------------------------------
    def quality(self, sample: BioSample) -> QualityReport:
        base = image_quality(self._green(self._image(sample)))
        if cv2 is None:
            return base
        gray = self._prep(self._image(sample))
        try:
            feat, binary, stats = self._features(gray)
        except Exception as exc:
            return QualityReport(0.0, False, base.metrics, [f'视网膜处理失败: {exc}'])
        coverage = float(binary.mean())
        metrics = dict(base.metrics)
        metrics.update({'vessel_coverage': coverage, 'branches': float(stats[0]), 'width': float(stats[1]), 'fd': float(stats[2])})
        issues = list(base.issues)
        if coverage < 0.02:
            issues.append('血管过少（可能非眼底图/离焦）')
        if coverage > 0.35:
            issues.append('血管分割过度（噪声）')
        score = 0.55 * base.score + 0.45 * float(np.clip(coverage / 0.09, 0, 1))
        return QualityReport(score=clip01(score), passed=bool(score >= 0.48 and 0.02 <= coverage <= 0.35),
                             metrics=metrics, issues=issues)

    def _prep(self, img: np.ndarray) -> np.ndarray:
        gray = self._green(img)
        h, w = gray.shape[:2]
        scale = self.size / float(max(h, w))
        if scale < 1.0:
            gray = resize_gray(gray, (int(w * scale), int(h * scale)))
        return gray

    def extract(self, sample: BioSample) -> BioTemplate:
        report = self.quality(sample)
        if not report.passed:
            raise ValueError('视网膜质量不合格：' + '；'.join(report.issues or ['血管分割失败']))
        gray = self._prep(self._image(sample))
        feat, binary, stats = self._features(gray)
        small = cv2.resize(binary.astype(np.float32), (32, 32), interpolation=cv2.INTER_AREA).reshape(1, -1)
        return BioTemplate(
            modality=self.name, version=1,
            arrays={'embedding': feat.reshape(1, -1), 'map': small.astype(np.float32)},
            meta={'coverage': float(binary.mean()), 'fd': float(stats[2])},
            quality=report.score,
        )

    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        if 'embedding' not in a.arrays or 'embedding' not in b.arrays:
            return 0.0
        emb = cosine_score(a.arrays['embedding'].reshape(-1), b.arrays['embedding'].reshape(-1))
        ma = np.asarray(a.arrays.get('map', np.zeros((1, 1024))), dtype=np.float32).reshape(-1)
        mb = np.asarray(b.arrays.get('map', np.zeros((1, 1024))), dtype=np.float32).reshape(-1)
        if ma.size == mb.size and ma.size > 0:
            # 血管图用 IoU 而不是相关系数：大量背景 0 会把相关系数虚高
            ba, bb = ma > 0.15, mb > 0.15
            union = float(np.logical_or(ba, bb).sum())
            inter = float(np.logical_and(ba, bb).sum())
            iou = inter / union if union > 0 else 0.0
            coverage_penalty = min(float(ba.mean()), float(bb.mean())) / max(float(ba.mean()), float(bb.mean()), 1e-6)
            return clip01(0.30 * emb + 0.70 * iou * coverage_penalty)
        return emb

    def liveness(self, sample: BioSample) -> LivenessReport:
        report = self.quality(sample)
        # 眼底图无法用单帧判断打印/屏幕翻拍；需结合红外反射与瞳孔反应
        score = 0.5 + 0.4 * report.score
        return LivenessReport(passed=bool(report.passed and score >= 0.6), score=clip01(score),
                              mode='heuristic',
                              reasons=['视网膜 PAD 需眼底相机的红外反射/固视能力', '建议叠加近红外双眼同步校验'])
