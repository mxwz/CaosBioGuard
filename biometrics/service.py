"""多模态业务服务层：注册 / 验证 / 多因子认证。

UI、Web API、手机端、小程序都只调用这一层，避免各端各写一套质量门控与阈值逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .fusion import FusionPolicy, FusionResult, fuse
from .liveness import FacePadGate, LivenessPolicy
from .registry import BiometricRegistry
from .store import BioTemplateStore
from .types import BioSample, BioTemplate, MatchResult, QualityReport


@dataclass
class EnrollResult:
    ok: bool
    subject: str
    modality: str
    quality: float = 0.0
    samples: int = 0
    template_bytes: int = 0
    issues: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'ok': self.ok, 'subject': self.subject, 'modality': self.modality,
            'quality': round(self.quality, 3), 'samples': self.samples,
            'template_bytes': self.template_bytes, 'issues': self.issues, 'detail': self.detail,
        }


class BiometricService:
    def __init__(self, registry: Optional[BiometricRegistry] = None,
                 store: Optional[BioTemplateStore] = None,
                 liveness_policy: Optional[LivenessPolicy] = None):
        self.registry = registry or BiometricRegistry()
        self.store = store
        self.liveness_policy = liveness_policy or LivenessPolicy()
        self.pad_gate: Optional[FacePadGate] = self._build_default_gate()
        self._sync_face_gate()

    def _build_default_gate(self) -> FacePadGate:
        from .liveness import FaceLivenessDetector
        # 服务层可能收到单张图片，因此单帧也能给出结论；Kiosk 连续视频仍使用自己的多帧 Gate。
        policy = replace(self.liveness_policy, consecutive=1)
        return FacePadGate(FaceLivenessDetector(None, policy), policy)

    def _sync_face_gate(self) -> None:
        try:
            self.registry.resolve('face').set_pad_gate(self.pad_gate)
        except Exception:
            pass

    def attach_pad_model(self, model: Any) -> FacePadGate:
        from .liveness import FaceLivenessDetector
        policy = replace(self.liveness_policy, consecutive=1)
        self.pad_gate = FacePadGate(FaceLivenessDetector(model, policy), policy)
        self._sync_face_gate()
        return self.pad_gate

    # ------------------------------------------------------------------
    def enroll(self, subject: str, modality: str, samples: Sequence[BioSample],
               device_id: str = 'admin', min_samples: int = 1,
               min_quality: float = 0.45, use_liveness: bool = False) -> EnrollResult:
        engine = self.registry.resolve(modality)
        if not samples:
            return EnrollResult(False, subject, modality, issues=['没有采集样本'])
        if use_liveness:
            lr = engine.liveness(samples[0])
            if not lr.passed:
                return EnrollResult(False, subject, modality, issues=['活体未通过: ' + '；'.join(lr.reasons)],
                                    detail={'liveness': lr.to_dict()})

        templates: List[BioTemplate] = []
        issues: List[str] = []
        for sample in samples:
            report: QualityReport = engine.quality(sample)
            if not report.passed or report.score < min_quality:
                issues.extend(report.issues or [f'质量分 {report.score:.2f} 低于 {min_quality}'])
                continue
            try:
                templates.append(engine.extract(sample))
            except Exception as exc:
                issues.append(f'特征提取失败: {exc}')
        if len(templates) < min_samples:
            return EnrollResult(False, subject, modality, issues=issues or ['合格样本不足'],
                                detail={'accepted': len(templates)})

        final = engine.aggregate(templates) if len(templates) > 1 else templates[0]
        if self.store is not None:
            saved = self.store.save(subject, final, device_id=device_id)
            if not saved:
                issues.append('已有更高质量模板，本次未覆盖')
        return EnrollResult(
            ok=True, subject=subject, modality=modality,
            quality=final.quality, samples=len(templates),
            template_bytes=final.size_bytes(), issues=issues,
            detail={'samples_used': len(templates), 'accepted': len(templates)},
        )

    # ------------------------------------------------------------------
    def _guard_liveness(self, modality: str, sample: BioSample) -> tuple[bool, dict]:
        engine = self.registry.resolve(modality)
        try:
            report = engine.liveness(sample)
        except Exception as exc:
            return True, {'mode': 'error', 'error': str(exc)}
        return bool(report.passed), report.to_dict()

    def match_one(self, modality: str, sample: BioSample, device_id: Optional[str] = None,
                  candidates: Optional[Sequence[tuple[str, BioTemplate]]] = None,
                  threshold: Optional[float] = None, require_liveness: bool = True) -> MatchResult:
        engine = self.registry.resolve(modality)
        report = engine.quality(sample)
        if not report.passed:
            return MatchResult(modality, 0.0, threshold or engine.threshold, False,
                               details={'quality': report.to_dict(), 'reason': '质量门控未通过'})
        live_ok, live_detail = (True, {})
        if require_liveness:
            live_ok, live_detail = self._guard_liveness(modality, sample)
            if not live_ok:
                return MatchResult(modality, 0.0, threshold or engine.threshold, False,
                                   details={'liveness': live_detail, 'reason': '活体未通过'})
        try:
            probe = engine.extract(sample)
        except Exception as exc:
            return MatchResult(modality, 0.0, threshold or engine.threshold, False,
                               details={'reason': f'特征提取失败: {exc}'})

        if candidates is None:
            if self.store is None:
                raise ValueError('未配置模板库，且未提供候选模板')
            result = self.store.locate_gallery(modality, engine, probe, device_id, threshold)
        else:
            from .base import TemplateGallery
            result = TemplateGallery(candidates).match(probe, engine.compare,
                                                       threshold or engine.threshold, margin_threshold=0.04)
        result.quality = probe.quality
        result.details = dict(result.details or {}, quality=report.to_dict(), liveness=live_detail)
        return result

    # ------------------------------------------------------------------
    def verify_subject(self, subject: str, samples: Dict[str, BioSample],
                       policy: Optional[FusionPolicy] = None, device_id: Optional[str] = None,
                       require_liveness: bool = True) -> dict:
        """多因子认证：必须明确是「验证某个已声明身份」，逐模态与该用户模板比对后融合。"""
        if self.store is None:
            raise ValueError('verify_subject 需要模板库')
        results: List[MatchResult] = []
        liveness_all = True
        per_modality = {}
        for modality, sample in samples.items():
            engine = self.registry.resolve(modality)
            tmpl = self.store.load(subject, modality, device_id)
            if tmpl is None:
                per_modality[modality] = {'error': '该用户未注册此模态'}
                if (policy or FusionPolicy()).rule == 'all':
                    liveness_all = False
                continue
            ok, detail = self._guard_liveness(modality, sample) if require_liveness else (True, {})
            per_modality[modality] = {'liveness': detail}
            if not ok:
                liveness_all = False
                continue
            r = self.match_one(modality, sample, device_id, candidates=[(subject, tmpl)],
                               require_liveness=False)
            r.subject = subject
            results.append(r)
            per_modality[modality].update(r.to_dict())
        fusion = fuse(results, policy or FusionPolicy(rule='all'), liveness_ok=liveness_all)
        return {
            'subject': subject,
            'passed': fusion.passed,
            'fusion': fusion.to_dict(),
            'modalities': per_modality,
            'results': [r.to_dict() for r in results],
        }

    # ------------------------------------------------------------------
    def verify_1n(self, modality: str, sample: BioSample, device_id: Optional[str] = None,
                  threshold: Optional[float] = None, require_liveness: bool = True) -> dict:
        result = self.match_one(modality, sample, device_id, threshold=threshold,
                               require_liveness=require_liveness)
        return {'passed': result.passed, 'match': result.to_dict()}

    def stats(self) -> Dict[str, Any]:
        return {
            'registry': self.registry.specs(),
            'store': self.store.stats() if self.store else None,
            'liveness': self.liveness_policy.to_dict(),
            'pad_model': bool(self.pad_gate and self.pad_gate.detector.has_model),
        }
