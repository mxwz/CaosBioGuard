"""厂商 SDK 适配层基类。"""

from __future__ import annotations

import abc
from typing import Any, Dict, Optional, Tuple

from ..types import BioSample, BioTemplate, LivenessReport, QualityReport


class VendorAdapter(abc.ABC):
    modality: str
    vendor: str

    def __init__(self, modality: str, vendor: str, config: Optional[Dict[str, Any]] = None):
        self.modality = modality
        self.vendor = vendor
        self.config = dict(config or {})

    @abc.abstractmethod
    def check_available(self) -> Tuple[bool, str]: ...

    def quality(self, sample: BioSample) -> Optional[QualityReport]:
        return None

    @abc.abstractmethod
    def extract(self, sample: BioSample) -> BioTemplate: ...

    def compare(self, probe: BioTemplate, gallery: BioTemplate) -> Optional[float]:
        return None

    def liveness(self, sample: BioSample) -> Optional[LivenessReport]:
        return None

    def describe(self) -> Dict[str, Any]:
        return {'modality': self.modality, 'vendor': self.vendor, 'config': dict(self.config)}
