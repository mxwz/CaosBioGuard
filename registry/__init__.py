"""注册中心包：单例初始化与访问入口。

用法（web_admin/app.py 启动时）：
    from registry import init_registry_center, get_registry_center
    center = init_registry_center()
    center.register(notify_registry)
    center.register(face_store_registry)
    center.register(tool_registry)
"""
from .base import (
    Registry,
    RegistryCenter,
    PluginInfo,
    validate_plugin_info,
    ORIGIN_SYSTEM,
    ORIGIN_CUSTOM,
    discover_plugin_infos,
    package_dir,
    sanitize_plugin_name,
)

_center = None


def init_registry_center():
    """创建并返回全局唯一注册中心（幂等）。"""
    global _center
    _center = RegistryCenter()
    return _center


def get_registry_center():
    return _center


__all__ = [
    'Registry', 'RegistryCenter', 'PluginInfo', 'validate_plugin_info',
    'ORIGIN_SYSTEM', 'ORIGIN_CUSTOM',
    'discover_plugin_infos', 'package_dir', 'sanitize_plugin_name',
    'init_registry_center', 'get_registry_center',
]
