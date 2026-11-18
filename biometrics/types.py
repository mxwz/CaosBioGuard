"""多生物特征识别的基础数据类型。

设计原则：
1. 所有模态共用同一套「样本 → 质量 → 模板 → 比对 → 决策」契约，新增模态只需实现
   :class:`biometrics.base.ModalityEngine`，不需要改动 UI、同步、存储与融合层。
2. 模板只保存**不可逆特征**（不保存原始人脸/指纹图像），并支持 Fernet 加密后落库。
3. 所有分数统一到 ``[0, 1]`` 区间且「越大越像」，便于加权融合与阈值统一管理。
"""

from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


# ---------------------------------------------------------------------------
# 模态定义
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModalitySpec:
    """一个生物特征模态的静态描述（供 UI / API / 文档展示）。"""

    name: str                 # 机器名，如 ``voiceprint``
    label: str                # 中文名，如「声纹」
    kind: str                 # 输入类型：image / audio / frames / strokes
    description: str = ''
    hardware: str = ''        # 推荐采集硬件
    supports_liveness: bool = False
    default_threshold: float = 0.6
    security_level: int = 2   # 1~5，用于多因子融合排序

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'label': self.label,
            'kind': self.kind,
            'description': self.description,
            'hardware': self.hardware,
            'supports_liveness': self.supports_liveness,
            'default_threshold': self.default_threshold,
            'security_level': self.security_level,
        }


# ---------------------------------------------------------------------------
# 样本 / 质量 / 模板 / 比对结果
# ---------------------------------------------------------------------------


@dataclass
class BioSample:
    """一次采集样本的统一载体。

    ``kind`` 决定 ``data`` 的形态：

    - ``image``   ：``np.ndarray``，BGR 或灰度
    - ``audio``   ：``(waveform: np.ndarray[float32], sample_rate: int)`` 或 WAV 路径
    - ``frames``  ：``List[np.ndarray]``（步态剪影序列 / 人脸多帧）
    - ``strokes`` ：``List[Dict]`` 或 ``{'points': [...], 'image': ndarray}``（签名）
    - ``embedding``：已提取的向量，用于「模板直传」场景
    """

    kind: str
    data: Any
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def image(cls, img: np.ndarray, **meta: Any) -> 'BioSample':
        return cls('image', img, dict(meta))

    @classmethod
    def audio(cls, waveform: np.ndarray, sr: int, **meta: Any) -> 'BioSample':
        return cls('audio', (np.asarray(waveform, dtype=np.float32), int(sr)), dict(meta))

    @classmethod
    def frames(cls, frames: List[np.ndarray], **meta: Any) -> 'BioSample':
        return cls('frames', list(frames), dict(meta))

    @classmethod
    def strokes(cls, strokes: Any, image: Optional[np.ndarray] = None, **meta: Any) -> 'BioSample':
        data = {'strokes': strokes, 'image': image}
        return cls('strokes', data, dict(meta))


@dataclass
class QualityReport:
    """质量评估结果。``score`` 为 0~1，低于阈值时应拒绝录入或提示重采。"""

    score: float
    passed: bool
    metrics: Dict[str, float] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'score': round(float(self.score), 4),
            'passed': bool(self.passed),
            'metrics': {k: round(float(v), 4) for k, v in self.metrics.items()},
            'issues': list(self.issues),
        }


@dataclass
class BioTemplate:
    """与模态无关的可比对模板。

    ``arrays`` 内的数组必须是数值型、尺寸固定；``meta`` 只放非敏感辅助信息
    （例如虹膜掩码比例、步态帧数、签名时长）。
    """

    modality: str
    version: int = 1
    arrays: Dict[str, np.ndarray] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    quality: float = 0.0
    created_at: float = field(default_factory=time.time)

    # -- 序列化 ---------------------------------------------------------
    def to_bytes(self) -> bytes:
        return self.encode()

    @classmethod
    def from_bytes(cls, blob: bytes) -> 'BioTemplate':
        return cls.decode(blob)

    def encode(self) -> bytes:
        """带模态头部的紧凑序列化（落库/网络传输用）。"""
        payload = {
            'modality': self.modality,
            'version': self.version,
            'meta': self.meta,
            'quality': self.quality,
            'created_at': self.created_at,
        }
        buf = io.BytesIO()
        np.savez_compressed(
            buf,
            __header__=np.array([json.dumps(payload, ensure_ascii=False)]),
            **self.arrays,
        )
        return buf.getvalue()

    @classmethod
    def decode(cls, blob: bytes) -> 'BioTemplate':
        with np.load(io.BytesIO(blob), allow_pickle=False) as npz:
            header = json.loads(str(npz['__header__'][0]))
            arrays = {k: npz[k] for k in npz.files if k != '__header__'}
        return cls(
            modality=header['modality'],
            version=int(header.get('version', 1)),
            arrays=arrays,
            meta=header.get('meta', {}),
            quality=float(header.get('quality', 0.0)),
            created_at=float(header.get('created_at', time.time())),
        )

    def digest(self) -> str:
        """模板摘要，可作为幂等键与完整性校验。"""
        h = hashlib.sha256()
        for key in sorted(self.arrays):
            arr = np.ascontiguousarray(self.arrays[key])
            h.update(key.encode('utf-8'))
            h.update(str(arr.dtype).encode('utf-8'))
            h.update(str(arr.shape).encode('utf-8'))
            h.update(arr.tobytes())
        return h.hexdigest()

    def size_bytes(self) -> int:
        return int(sum(a.nbytes for a in self.arrays.values()))


@dataclass
class MatchResult:
    """单次比对结果。``score`` 已统一到 0~1，``passed`` 由阈值裁决。"""

    modality: str
    score: float
    threshold: float
    passed: bool
    subject: str = ''
    quality: float = 0.0
    margin: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'modality': self.modality,
            'score': round(float(self.score), 4),
            'threshold': round(float(self.threshold), 4),
            'passed': bool(self.passed),
            'subject': self.subject,
            'quality': round(float(self.quality), 4),
            'margin': round(float(self.margin), 4),
            'details': self.details,
        }


@dataclass
class LivenessReport:
    """活体/防伪检测结果。

    ``mode`` 用于区分「神经网络模型」「启发式」「主动挑战」三种可信度，
    上层决策必须显式感知它，避免把弱检测当成强保证。
    """

    passed: bool
    score: float
    mode: str = 'heuristic'          # model / heuristic / active / hybrid / disabled
    reasons: List[str] = field(default_factory=list)
    spoof_type: str = ''
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'passed': bool(self.passed),
            'score': round(float(self.score), 4),
            'mode': self.mode,
            'reasons': list(self.reasons),
            'spoof_type': self.spoof_type,
            'latency_ms': round(float(self.latency_ms), 1),
        }
