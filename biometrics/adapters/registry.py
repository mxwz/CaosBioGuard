"""厂商 SDK 适配器注册器。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .base import VendorAdapter
from .generic import GenericSDKAdapter

VALID_POLICIES = {'auto', 'model', 'sdk', 'fusion'}


class VendorAdapterRegistry:
    def __init__(self, adapters: Optional[Dict[str, VendorAdapter]] = None,
                 default_policy: str = 'auto', allow_fallback: bool = True,
                 modality_policies: Optional[Dict[str, str]] = None):
        self.adapters = dict(adapters or {})
        self.default_policy = default_policy
        self.allow_fallback = allow_fallback
        self.modality_policies = dict(modality_policies or {})

    @classmethod
    def from_config(cls, config_manager: Any, modalities: List[str]) -> 'VendorAdapterRegistry':
        backend_section = dict(config_manager.get_section('BiometricBackends') or {})
        default_policy = str(backend_section.get('default_policy', 'auto')).lower()
        allow_fallback = str(backend_section.get('allow_fallback', 'true')).lower() in {
            '1', 'true', 'yes', 'on'
        }
        modality_policies = {}
        adapters: Dict[str, VendorAdapter] = {}
        for modality in modalities:
            section = dict(config_manager.get_section(f'VendorSDK.{modality}') or {})
            policy = str(section.pop('policy', '') or '').lower()
            if policy:
                modality_policies[modality] = policy
            if str(section.get('enabled', 'false')).lower() not in {'1', 'true', 'yes', 'on'}:
                continue
            vendor = str(section.get('vendor', 'generic'))
            adapters[modality] = GenericSDKAdapter(modality, vendor, section)
        return cls(adapters, default_policy, allow_fallback, modality_policies)

    def get(self, modality: str) -> Optional[VendorAdapter]:
        return self.adapters.get(modality)

    def policy_for(self, modality: str) -> str:
        policy = self.modality_policies.get(modality, self.default_policy).lower()
        return policy if policy in VALID_POLICIES else 'auto'

    def available(self, modality: str) -> Tuple[bool, str]:
        adapter = self.get(modality)
        if adapter is None:
            return False, '未配置厂商 SDK'
        return adapter.check_available()

    def describe(self) -> Dict[str, Any]:
        return {
            'default_policy': self.default_policy,
            'allow_fallback': self.allow_fallback,
            'modality_policies': self.modality_policies,
            'adapters': {k: v.describe() for k, v in self.adapters.items()},
        }
