"""生物特征引擎包。

新增模态的标准做法：
1. 在本目录新增 ``xxx.py``，实现 :class:`biometrics.base.ModalityEngine`；
2. 在下方 ``ENGINE_CLASSES`` 里登记一行；
3. 不需要改 UI、存储、融合、同步——注册器会自动发现并暴露给所有端。
"""

from __future__ import annotations

from .face import FaceEngine
from .fingerprint import FingerprintEngine
from .gait import GaitEngine
from .iris import IrisEngine
from .palmprint import PalmprintEngine
from .retina import RetinaEngine
from .signature import SignatureEngine
from .vein import VeinEngine
from .voiceprint import VoiceprintEngine

ENGINE_CLASSES = [
    FaceEngine,
    VoiceprintEngine,
    FingerprintEngine,
    IrisEngine,
    PalmprintEngine,
    VeinEngine,
    GaitEngine,
    RetinaEngine,
    SignatureEngine,
]

__all__ = [
    'FaceEngine', 'VoiceprintEngine', 'FingerprintEngine', 'IrisEngine',
    'PalmprintEngine', 'VeinEngine', 'GaitEngine', 'RetinaEngine',
    'SignatureEngine', 'ENGINE_CLASSES',
]
