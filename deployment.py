"""部署模式解析与一致性校验。

统一描述三类正交维度：
- operation_mode：offline（离线）/ online（在线）
- network_scope：lan（局域网）/ public（公网）
- topology：integrated（服务边缘集成）/ separated（服务边缘分离）

该模块只做配置解析和能力/风险校验，不直接启动数据库或网络连接，避免导入即产生副作用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

TRUE_VALUES = {'1', 'true', 'yes', 'on'}
OPERATION_MODES = {'offline', 'online'}
NETWORK_SCOPES = {'lan', 'public'}
TOPOLOGIES = {'integrated', 'separated'}


def _value(section: Dict[str, Any], key: str, default: str = '') -> str:
    return str(section.get(key, default) or default).strip()


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in TRUE_VALUES


@dataclass(frozen=True)
class DeploymentProfile:
    operation_mode: str
    network_scope: str
    topology: str
    cloud_enabled: bool
    public_base_url: str
    sync_endpoint: str
    storage: str
    capabilities: List[str]
    warnings: List[str]
    errors: List[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            'ok': self.ok,
            'operation_mode': self.operation_mode,
            'network_scope': self.network_scope,
            'topology': self.topology,
            'cloud_enabled': self.cloud_enabled,
            'public_base_url': self.public_base_url,
            'sync_endpoint': self.sync_endpoint,
            'storage': self.storage,
            'capabilities': self.capabilities,
            'warnings': self.warnings,
            'errors': self.errors,
        }

    @classmethod
    def from_config(cls, config_manager: Any) -> 'DeploymentProfile':
        deployment = dict(config_manager.get_section('Deployment') or {})
        general = dict(config_manager.get_section('General') or {})
        web = dict(config_manager.get_section('WebAdmin') or {})
        cloud = dict(config_manager.get_section('Cloud') or {})
        sync = dict(config_manager.get_section('Sync') or {})

        errors: List[str] = []
        warnings: List[str] = []
        cloud_enabled = _as_bool(_value(cloud, 'enabled', 'false'))

        operation_mode = _value(deployment, 'operation_mode') or _value(general, 'networkmode', 'online')
        operation_mode = operation_mode.lower()
        if operation_mode not in OPERATION_MODES:
            errors.append(f'operation_mode 只能是 offline/online，当前为 {operation_mode}')

        network_scope = _value(deployment, 'network_scope') or (
            'public' if _value(web, 'protocol', 'http').lower() == 'https' else 'lan'
        )
        network_scope = network_scope.lower()
        if network_scope not in NETWORK_SCOPES:
            errors.append(f'network_scope 只能是 lan/public，当前为 {network_scope}')

        topology = _value(deployment, 'topology') or ('separated' if cloud_enabled else 'integrated')
        topology = topology.lower()
        if topology not in TOPOLOGIES:
            errors.append(f'topology 只能是 integrated/separated，当前为 {topology}')
        if topology == 'separated' and not cloud_enabled:
            errors.append('服务边缘分离模式要求 [Cloud] enabled=true，由云端提供权威存储')
        if topology == 'integrated' and cloud_enabled:
            errors.append('服务边缘集成模式不应同时启用 [Cloud] enabled=true，避免存储语义冲突')

        public_base_url = _value(deployment, 'public_base_url') or _value(web, 'public_base_url')
        sync_endpoint = _value(sync, 'endpoint')
        protocol = _value(web, 'protocol', 'http').lower()
        token = _value(web, 'token')
        cors_origins = _value(web, 'cors_origins')

        if operation_mode == 'offline' and network_scope == 'public':
            errors.append('离线模式不能同时声明为公网模式；公网访问需要在线服务')
        if network_scope == 'public':
            if protocol != 'https':
                errors.append('公网模式要求 [WebAdmin] protocol=https，并由反向代理配置 TLS')
            if not public_base_url:
                errors.append('公网模式需要配置 public_base_url，例如 https://guard.example.com')
            elif not public_base_url.lower().startswith('https://'):
                errors.append('public_base_url 必须以 https:// 开头')
            if token in {'change-me-to-a-long-random-token', 'change-me'}:
                errors.append('公网模式仍在使用默认管理 token')
            if not cors_origins:
                warnings.append('未配置 cors_origins：同源 PWA 可用，跨域 Web 应用将无法访问 API')
        elif operation_mode == 'online' and protocol == 'https':
            warnings.append('局域网 HTTPS 需确保终端信任证书，否则移动端可能拦截请求')

        if topology == 'separated':
            if not sync_endpoint:
                errors.append('服务边缘分离模式需要配置 [Sync] endpoint，离线时也应保留用于恢复后同步')
            if not _value(sync, 'secret'):
                errors.append('服务边缘分离模式需要配置 [Sync] secret 用于 HMAC 签名')
            if network_scope == 'public' and sync_endpoint.startswith('http://'):
                errors.append('公网分离模式的 Sync.endpoint 必须使用 HTTPS')
        elif operation_mode == 'online' and not sync_endpoint:
            warnings.append('集成在线模式未配置同步端点；同机部署可忽略，跨机调用需补齐')

        if operation_mode == 'offline':
            warnings.append('离线模式依赖本地缓存和 outbox，恢复网络后需执行同步对账')
        if not cloud_enabled and token in {'change-me-to-a-long-random-token', 'change-me'}:
            warnings.append('当前仍使用默认管理 token，接入网络前应替换')

        storage = (
            '云端 MySQL + 对象存储为权威库，边缘 SQLite 为离线缓存'
            if topology == 'separated'
            else '本地 SQLite + 本地文件目录为权威库'
        )
        capabilities = ['local_quality_gate', 'encrypted_template_store', 'sync_outbox']
        if operation_mode == 'offline':
            capabilities += ['offline_identify', 'local_cache', 'recoverable_sync']
        else:
            capabilities += ['online_sync', 'mobile_access']
        if topology == 'integrated':
            capabilities.append('local_integrated_web')
        else:
            capabilities += ['cloud_authority', 'edge_cache', 'hmac_sync']
        if network_scope == 'public':
            capabilities += ['tls', 'public_pwa']

        return cls(
            operation_mode=operation_mode,
            network_scope=network_scope,
            topology=topology,
            cloud_enabled=cloud_enabled,
            public_base_url=public_base_url,
            sync_endpoint=sync_endpoint,
            storage=storage,
            capabilities=sorted(set(capabilities)),
            warnings=warnings,
            errors=errors,
        )


if __name__ == '__main__':
    import json
    from managers import ConfigManager

    current = DeploymentProfile.from_config(ConfigManager())
    print(json.dumps(current.to_dict(), ensure_ascii=False, indent=2))
    raise SystemExit(0 if current.ok else 1)
