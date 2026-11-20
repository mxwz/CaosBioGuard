"""拔插式 SDK 插件 manifest 数据模型与校验。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set

MANIFEST_NAME = 'plugin.toml'
PLUGIN_SCHEMA_VERSION = '1.0'
VALID_PLATFORMS = {'windows-x64', 'linux-x64', 'linux-arm64', 'android-arm64'}
VALID_CAPABILITIES = {
    'detect', 'quality', 'extract', 'compare', 'identify',
    'liveness.rgb', 'liveness.nir', 'liveness.depth', 'user_manage',
}
VALID_PERMISSIONS = {
    'camera', 'microphone', 'serial', 'gpio', 'network.localhost',
    'network.lan', 'files.plugin', 'files.models',
}


@dataclass(frozen=True)
class PluginManifest:
    schema_version: str
    plugin_id: str
    name: str
    version: str
    vendor: str
    modalities: List[str]
    platforms: List[str]
    adapter_class: str
    capabilities: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    native_libraries: Dict[str, str] = field(default_factory=dict)
    license_path: str = ''
    model_path: str = ''
    min_app_version: str = '0.2.2'
    enabled_by_default: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> 'PluginManifest':
        path = Path(path)
        with path.open('rb') as fh:
            data = tomllib.load(fh)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PluginManifest':
        required = ['schema_version', 'plugin_id', 'name', 'version', 'vendor',
                    'modalities', 'platforms', 'adapter_class']
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError(f'manifest 缺少必填字段: {", ".join(missing)}')
        manifest = cls(
            schema_version=str(data['schema_version']),
            plugin_id=str(data['plugin_id']),
            name=str(data['name']),
            version=str(data['version']),
            vendor=str(data['vendor']),
            modalities=[str(x) for x in data['modalities']],
            platforms=[str(x) for x in data['platforms']],
            adapter_class=str(data['adapter_class']),
            capabilities=[str(x) for x in data.get('capabilities', [])],
            permissions=[str(x) for x in data.get('permissions', [])],
            native_libraries={str(k): str(v) for k, v in data.get('native_libraries', {}).items()},
            license_path=str(data.get('license_path', '') or ''),
            model_path=str(data.get('model_path', '') or ''),
            min_app_version=str(data.get('min_app_version', '0.2.2')),
            enabled_by_default=bool(data.get('enabled_by_default', False)),
            raw=dict(data),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if self.schema_version != PLUGIN_SCHEMA_VERSION:
            raise ValueError(f'不支持的插件协议版本: {self.schema_version}')
        if not self.modalities:
            raise ValueError('插件至少声明一个模态')
        unknown_platforms = set(self.platforms) - VALID_PLATFORMS
        if unknown_platforms:
            raise ValueError(f'不支持的平台: {sorted(unknown_platforms)}')
        unknown_caps = set(self.capabilities) - VALID_CAPABILITIES
        if unknown_caps:
            raise ValueError(f'不支持的能力: {sorted(unknown_caps)}')
        unknown_perms = set(self.permissions) - VALID_PERMISSIONS
        if unknown_perms:
            raise ValueError(f'不支持的权限: {sorted(unknown_perms)}')
        if '.' not in self.adapter_class:
            raise ValueError('adapter_class 必须为模块路径.类名')

    def capability_set(self) -> Set[str]:
        return set(self.capabilities)

    def permission_set(self) -> Set[str]:
        return set(self.permissions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'plugin_id': self.plugin_id,
            'name': self.name,
            'version': self.version,
            'vendor': self.vendor,
            'modalities': self.modalities,
            'platforms': self.platforms,
            'adapter_class': self.adapter_class,
            'capabilities': self.capabilities,
            'permissions': self.permissions,
            'native_libraries': self.native_libraries,
            'license_path': self.license_path,
            'model_path': self.model_path,
            'min_app_version': self.min_app_version,
            'enabled_by_default': self.enabled_by_default,
        }
