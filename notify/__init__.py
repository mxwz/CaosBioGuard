"""通知注册中心包：单例初始化与访问入口。

用法（在 web_admin/app.py 启动时）：
    from notify import init_notify_center, get_notify_center
    init_notify_center(config_manager, db_manager)

业务方触发通知：
    from notify import get_notify_center, Event
    get_notify_center().dispatch_async(Event(type='agent_report', level='warning', ...))
"""
from .base import Event, NotifyChannel, NotifyCenter

_center = None


def init_notify_center(config_manager=None, db_manager=None):
    """创建并返回全局唯一通知中心（幂等），并自动发现渠道插件。"""
    global _center
    _center = NotifyCenter(config_manager, db_manager)
    _center.discover()
    return _center


def get_notify_center():
    return _center


__all__ = ['Event', 'NotifyChannel', 'NotifyCenter', 'init_notify_center', 'get_notify_center']
