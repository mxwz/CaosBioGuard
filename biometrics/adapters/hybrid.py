"""模型引擎与厂商 SDK 的混合引擎。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..base import ModalityEngine, clip01
from ..types import BioSample, BioTemplate, LivenessReport, QualityReport
from .base import VendorAdapter


class HybridEngine(ModalityEngine):
    """对上层保持 ModalityEngine 契约，内部按策略选择模型或 SDK。"""

    def __init__(self, model: ModalityEngine, adapter: Optional[VendorAdapter] = None,
                 policy: str = 'auto', allow_fallback: bool = True,
                 fusion_weights: Optional[Dict[str, float]] = None):
        self.model = model
        self.adapter = adapter
        self.policy = policy if policy in {'auto', 'model', 'sdk', 'fusion'} else 'auto'
        self.allow_fallback = allow_fallback
        weights = fusion_weights or {'model': 0.5, 'sdk': 0.5}
        total = sum(max(0, v) for v in weights.values()) or 1.0
        self.fusion_weights = {k: max(0, v) / total for k, v in weights.items()}
        self.spec = model.spec

    @property
    def name(self) -> str:
        return self.model.name

    def check_available(self) -> Tuple[bool, str]:
        model_ok, model_reason = self.model.check_available()
        if self.adapter is None:
            return model_ok, model_reason
        sdk_ok, sdk_reason = self.adapter.check_available()
        if self.policy == 'sdk' and not sdk_ok and not self.allow_fallback:
            return False, sdk_reason
        if not model_ok and not sdk_ok:
            return False, f'模型: {model_reason}; SDK: {sdk_reason}'
        return True, ''

    def _sdk_available(self) -> bool:
        return self.adapter is not None and self.adapter.check_available()[0]

    def _backend_for(self, sample: Optional[BioSample]) -> str:
        if sample is not None and sample.meta.get('backend'):
            return str(sample.meta['backend']).lower()
        return self.policy

    @staticmethod
    def _mark(template: BioTemplate, backend: str, vendor: str = '') -> BioTemplate:
        template.meta['backend'] = backend
        if vendor:
            template.meta['vendor'] = vendor
        return template

    def quality(self, sample: BioSample) -> QualityReport:
        backend = self._backend_for(sample)
        if backend in {'sdk', 'fusion'} and self.adapter is not None:
            report = self.adapter.quality(sample)
            if report is not None:
                return report
        return self.model.quality(sample)

    def extract(self, sample: BioSample) -> BioTemplate:
        backend = self._backend_for(sample)
        if backend == 'model':
            return self._mark(self.model.extract(sample), 'model')
        if backend == 'sdk':
            return self._extract_sdk_or_fallback(sample)
        if backend == 'fusion':
            # 单模板接口默认返回模型模板；注册融合模板请使用 extract_all。
            return self._mark(self.model.extract(sample), 'model')
        if self._sdk_available():
            return self._mark(self.adapter.extract(sample), 'sdk', getattr(self.adapter, 'vendor', ''))
        return self._mark(self.model.extract(sample), 'model')

    def _extract_sdk_or_fallback(self, sample: BioSample) -> BioTemplate:
        if self._sdk_available():
            return self._mark(self.adapter.extract(sample), 'sdk', getattr(self.adapter, 'vendor', ''))
        if self.allow_fallback:
            return self._mark(self.model.extract(sample), 'model')
        raise RuntimeError(f'{self.label} 厂商 SDK 不可用，且未允许模型回退')

    def extract_all(self, sample: BioSample) -> List[BioTemplate]:
        output: List[BioTemplate] = [self._mark(self.model.extract(sample), 'model')]
        if self._sdk_available():
            output.append(self._mark(self.adapter.extract(sample), 'sdk', self.adapter.vendor))
        return output

    def compare(self, a: BioTemplate, b: BioTemplate) -> float:
        backend = a.meta.get('backend', b.meta.get('backend', self.policy))
        if backend == 'sdk' and self.adapter is not None:
            score = self.adapter.compare(a, b)
            if score is not None:
                return clip01(score)
        if backend == 'model':
            return self.model.compare(a, b)

        model_score: Optional[float] = None
        sdk_score: Optional[float] = None
        try:
            model_score = self.model.compare(a, b)
        except Exception:
            model_score = None
        if self.adapter is not None:
            sdk_score = self.adapter.compare(a, b)
        if model_score is not None and sdk_score is not None:
            return clip01(
                self.fusion_weights['model'] * model_score
                + self.fusion_weights['sdk'] * sdk_score
            )
        if model_score is not None:
            return clip01(model_score)
        if sdk_score is not None:
            return clip01(sdk_score)
        return 0.0

    def liveness(self, sample: BioSample) -> LivenessReport:
        if self.adapter is not None:
            report = self.adapter.liveness(sample)
            if report is not None:
                return report
        return self.model.liveness(sample)

    def aggregate(self, templates: Sequence[BioTemplate]) -> BioTemplate:
        if all(t.meta.get('backend') == 'sdk' for t in templates):
            return templates[0]
        return self.model.aggregate([t for t in templates if t.meta.get('backend') != 'sdk'])
