"""人脸模态引擎：InsightFace 封装 + 质量自适应阈值 + 1:N margin 判决。

相对旧实现的增强点：
1. **质量门控**：清晰度、姿态、人脸占比、检测置信度共同决定本次是否可信；
2. **自适应阈值**：质量越低，放行阈值越高，避免「糊脸高分」误放行；
3. **Margin 判决**：不仅看第一名分数，还要求与第二名拉开差距，降低撞脸；
4. **多帧聚合**：注册时按质量加权平均多帧特征，比单帧模板更稳；
5. **活体前置**：``verify`` 明确要求活体先通过（由 liveness 层负责）。
"""

from __future__ import annotations

import math
import os
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..base import ImageEngine, TemplateGallery, clip01, cosine_score, ensure_gray, image_quality, l2norm
from ..types import BioSample, BioTemplate, MatchResult, ModalitySpec, QualityReport


FACE_SPEC = ModalitySpec(
    name='face',
    label='人脸',
    kind='image',
    description='基于 InsightFace 的 512 维特征比对，支持质量自适应与多帧聚合。',
    hardware='USB/UVC 摄像头、MIPI CSI 摄像头',
    supports_liveness=True,
    default_threshold=0.55,
    security_level=2,
)


class FaceEngine(ImageEngine):
    """InsightFace 引擎（惰性加载，避免 import 即占用显存）。"""

    spec = FACE_SPEC

    def __init__(self, app: Any = None, ctx_id: Optional[int] = None,
                 det_size: Tuple[int, int] = (640, 640), model_name: str = 'buffalo_l'):
        self._app = app
        self._model_name = model_name
        self._det_size = det_size
        self._ctx_id = ctx_id
        self._lock = threading.RLock()
        self._load_error = ''

    # ------------------------------------------------------------------
    # 模型
    # ------------------------------------------------------------------
    def set_model(self, app: Any) -> None:
        """注入外部已加载的 FaceAnalysis 实例，避免重复加载。"""
        self._app = app

    def _ensure_model(self) -> Any:
        if self._app is not None:
            return self._app
        with self._lock:
            if self._app is not None:
                return self._app
            if self._load_error:
                raise RuntimeError(self._load_error)
            try:
                from insightface.app import FaceAnalysis  # type: ignore
            except Exception as exc:  # pragma: no cover - 环境相关
                self._load_error = f'未安装 insightface: {exc}'
                raise RuntimeError(self._load_error) from exc
            ctx = self._ctx_id
            if ctx is None:
                try:
                    import onnxruntime
                    providers = onnxruntime.get_available_providers()
                    ctx = 0 if 'CUDAExecutionProvider' in providers else -1
                except Exception:
                    ctx = -1
            app = FaceAnalysis(name=self._model_name)
            app.prepare(ctx_id=ctx, det_size=self._det_size)
            self._app = app
            return app

    def check_available(self) -> Tuple[bool, str]:
        try:
            self._ensure_model()
            return True, ''
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # 质量
    # ------------------------------------------------------------------
    def assess(self, frame: np.ndarray, face: Any, min_face_ratio: float = 0.06) -> QualityReport:
        """综合评估单张人脸：清晰度 + 姿态 + 占比 + 检测分。"""
        gray = ensure_gray(frame)
        h, w = gray.shape[:2]
        base = image_quality(gray)
        bbox = np.asarray(getattr(face, 'bbox', [0, 0, 0, 0]), dtype=np.float32).astype(int)
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return QualityReport(0.0, False, base.metrics, base.issues + ['人脸框无效'])
        crop = gray[y1:y2, x1:x2]
        face_ratio = ((x2 - x1) * (y2 - y1)) / float(w * h)
        pose = self._pose(face)
        det = float(getattr(face, 'det_score', 1.0) or 1.0)

        crop_quality = image_quality(crop, min_side=48)
        metrics = dict(base.metrics)
        metrics.update({
            'face_ratio': face_ratio,
            'det_score': det,
            'yaw': pose['yaw'],
            'pitch': pose['pitch'],
            'roll': pose['roll'],
            'crop_sharpness': crop_quality.metrics.get('sharpness', 0.0),
        })
        issues = list(crop_quality.issues)

        # 加权：人脸区域清晰度最重要，其次姿态与占比
        score = 0.34 * crop_quality.metrics.get('sharpness', 0.0)
        score += 0.20 * clip01(1.0 - abs(pose['yaw']) / 0.55)
        score += 0.14 * clip01(1.0 - abs(pose['pitch']) / 0.45)
        score += 0.12 * clip01(1.0 - abs(pose['roll']) / 0.50)
        score += 0.12 * clip01(face_ratio / max(min_face_ratio * 2.0, 0.12))
        score += 0.08 * clip01((det - 0.35) / 0.55)

        if abs(pose['yaw']) > 0.55:
            issues.append('侧脸角度过大')
        if abs(pose['pitch']) > 0.45:
            issues.append('俯仰角过大')
        if face_ratio < min_face_ratio:
            issues.append('人脸占比过小，请靠近')
        if det < 0.55:
            issues.append('检测置信度偏低')
        return QualityReport(score=clip01(score), passed=bool(score >= 0.48 and det >= 0.5), metrics=metrics, issues=issues)

    @staticmethod
    def _pose(face: Any) -> Dict[str, float]:
        """由 5 点关键点估计近似 yaw/pitch/roll（归一化到 [-1,1] 附近）。"""
        kps = getattr(face, 'kps', None)
        try:
            pts = np.asarray(kps, dtype=np.float32)
        except Exception:
            pts = None
        if pts is None or pts.shape[0] < 3:
            return {'yaw': 0.0, 'pitch': 0.0, 'roll': 0.0}
        left_eye, right_eye, nose = pts[0], pts[1], pts[2]
        eye_mid = (left_eye + right_eye) / 2.0
        eye_dist = float(np.linalg.norm(right_eye - left_eye)) + 1e-6
        yaw = float((nose[0] - eye_mid[0]) / eye_dist)
        pitch = float((nose[1] - eye_mid[1]) / eye_dist) - 0.35
        roll = float(math.atan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0])) / (math.pi / 2)
        return {'yaw': yaw, 'pitch': pitch, 'roll': roll}

    # ------------------------------------------------------------------
    # 提取
    # ------------------------------------------------------------------
    def extract(self, sample: BioSample) -> BioTemplate:
        img = self._image(sample)
        app = self._ensure_model()
        with self._lock:
            faces = app.get(img)
        if not faces:
            raise ValueError('未检测到人脸')
        face = max(faces, key=lambda f: float((f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])))
        quality = self.assess(img, face)
        emb = l2norm(np.asarray(face.embedding, dtype=np.float32))
        bbox = np.asarray(face.bbox, dtype=np.float32)
        kps = np.asarray(getattr(face, 'kps', np.zeros((5, 2), dtype=np.float32)), dtype=np.float32)
        pose = self._pose(face)
        return BioTemplate(
            modality=self.name,
            version=2,
            arrays={
                'embedding': emb.reshape(1, -1),
                'bbox': bbox.reshape(1, 4),
                'kps': kps.reshape(1, -1),
            },
            meta={
                'det_score': float(getattr(face, 'det_score', 0.0) or 0.0),
                'pose': pose,
                'face_ratio': float(quality.metrics.get('face_ratio', 0.0)),
                'source': 'insightface',
            },
            quality=quality.score,
        )

    def extract_many(self, frames: Sequence[np.ndarray], max_samples: int = 5,
                     min_quality: float = 0.45) -> List[BioTemplate]:
        """从多帧中筛选高质量模板（注册时使用）。"""
        out: List[BioTemplate] = []
        for frame in frames:
            try:
                t = self.extract(BioSample.image(frame))
            except Exception:
                continue
            if t.quality >= min_quality:
                out.append(t)
            if len(out) >= max_samples:
                break
        return out

    # ------------------------------------------------------------------
    # 比对
    # ------------------------------------------------------------------
    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        if 'embedding' not in a.arrays or 'embedding' not in b.arrays:
            return 0.0
        return cosine_score(a.arrays['embedding'].reshape(-1), b.arrays['embedding'].reshape(-1))

    def threshold_for(self, quality: float, base: Optional[float] = None) -> float:
        """质量自适应阈值：质量 1.0 时用基础阈值，质量 0 时上浮 0.10。"""
        base = self.threshold if base is None else float(base)
        return float(np.clip(base + 0.10 * (1.0 - clip01(quality)), 0.0, 0.99))

    def match_gallery(self, probe: BioTemplate, entries: Sequence[Tuple[str, BioTemplate]],
                      threshold: Optional[float] = None, margin_threshold: float = 0.06) -> MatchResult:
        thr = self.threshold_for(probe.quality, threshold)
        gallery = TemplateGallery(entries)
        return gallery.match(probe, self.compare, thr, margin_threshold=margin_threshold)

    def aggregate(self, templates: Sequence[BioTemplate]) -> BioTemplate:
        """人脸模板只用 embedding 聚合，姿态/框信息取质量最高的一帧。"""
        valid = [t for t in templates if 'embedding' in t.arrays]
        if not valid:
            raise ValueError('没有可用人脸模板')
        weights = [max(t.quality, 0.01) for t in valid]
        stacked = np.stack([l2norm(t.arrays['embedding'].reshape(-1)) for t in valid], axis=0)
        w = np.asarray(weights, dtype=np.float32)
        emb = (stacked * (w / w.sum())[:, None]).sum(axis=0)
        emb = l2norm(emb)
        best = max(valid, key=lambda t: t.quality)
        return BioTemplate(
            modality=self.name,
            version=2,
            arrays={'embedding': emb.reshape(1, -1)},
            meta={'samples': len(valid), 'aggregated': True,
                  'pose': best.meta.get('pose', {}),
                  'det_score': best.meta.get('det_score', 0.0)},
            quality=float(np.mean([t.quality for t in valid])),
        )

    def describe(self) -> Dict[str, Any]:
        available, reason = self.check_available()
        return {
            'name': self.name, 'label': self.label,
            'available': available, 'reason': reason,
            'model': self._model_name,
            'threshold': self.threshold,
        }
