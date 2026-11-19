"""Caos BioGuard 多生物特征核心包。

快速开始::

    from biometrics import build_biometric_registry, BiometricService, BioTemplateStore

    registry = build_biometric_registry()          # 9 个模态，惰性加载模型
    store = BiometricTemplateStore('dd/biometrics.db', config_manager=cfg)
    service = BiometricService(registry, store)
    service.enroll('张三', 'voiceprint', [BioSample.audio(wav, sr)])

设计文档见 ``docs/biometrics-api.md`` 与 ``docs/hardware-design.md``。
"""

from .adapters import GenericSDKAdapter, HybridEngine, VendorAdapter, VendorAdapterRegistry, normalize_template
from .base import ImageEngine, ModalityEngine, ScoreCalibrator, TemplateGallery, cosine_score, l2norm
from .fusion import FusionPolicy, FusionResult, evaluate_thresholds, fuse
from .liveness import (ActiveChallenge, FaceLivenessDetector, FacePadGate, LivenessPolicy,
                       TemporalGuard, crop_face, liveness_compatibility)
from .registry import BiometricRegistry, build_biometric_registry
from .service import BiometricService, EnrollResult
from .store import BioTemplateStore, StoredTemplate, TemplateCipher
from .types import (BioSample, BioTemplate, LivenessReport, MatchResult, ModalitySpec,
                    QualityReport)

__all__ = [
    'BioSample', 'BioTemplate', 'QualityReport', 'MatchResult', 'LivenessReport', 'ModalitySpec',
    'ModalityEngine', 'ImageEngine', 'TemplateGallery', 'ScoreCalibrator',
    'VendorAdapter', 'GenericSDKAdapter', 'VendorAdapterRegistry', 'HybridEngine',
    'normalize_template',
    'BiometricRegistry', 'build_biometric_registry',
    'BiometricService', 'EnrollResult',
    'BioTemplateStore', 'StoredTemplate', 'TemplateCipher',
    'FusionPolicy', 'FusionResult', 'fuse', 'evaluate_thresholds',
    'LivenessPolicy', 'FaceLivenessDetector', 'FacePadGate', 'TemporalGuard',
    'ActiveChallenge', 'crop_face', 'liveness_compatibility',
    'cosine_score', 'l2norm',
]
