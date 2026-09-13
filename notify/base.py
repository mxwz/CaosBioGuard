"""通知注册中心：事件、渠道抽象、注册中心与统一调度器。"""
import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from registry.base import Registry

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """一条待分发的通知事件。"""
    type: str                     # 事件类型，如 'agent_report'
    level: str = 'info'           # info / warning / critical
    title: str = ''               # 标题
    content: str = ''             # 正文
    meta: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


class NotifyChannel(ABC):
    """通知渠道插件接口。

    新增渠道：继承本类，实现 send()，声明 name/display_name/config_section/config_fields，
    并在插件模块顶层定义 INFO = PluginInfo(name=..., entry=本类实例, origin='system'|'custom')。
    通知中心启动时自动发现 channels 与 custom_plugins.notify 下的插件，核心逻辑零改动。
    """
    name = 'base'
    display_name = 'Base'
    config_section = ''           # config.ini 中该渠道的 section 名
    config_fields = []            # [{name,label,type,required,secret}]，驱动后台表单自动生成

    @abstractmethod
    def send(self, config: dict, event: Event) -> bool:
        """发送一条通知，成功返回 True。config 来自 config.ini 对应 section。"""

    def validate(self, config: dict) -> list:
        """返回缺失/非法字段列表，用于后台保存前校验。"""
        errors = []
        for f in self.config_fields:
            if f.get('required') and not str(config.get(f['name'], '')).strip():
                errors.append(f['label'])
        return errors


class NotifyCenter(Registry):
    """通知渠道注册器：登记各通知渠道，并按订阅规则统一调度分发。"""

    name = 'notify'
    label = '通知渠道'
    system_plugin_package = 'notify.channels'
    custom_plugin_package = 'custom_plugins.notify'

    def __init__(self, config_manager=None, db_manager=None):
        super().__init__()
        self.config_manager = config_manager
        self.db_manager = db_manager

    def list_channels(self):
        """返回已注册渠道的元信息（含配置项定义），供后台渲染。"""
        result = []
        for name, info in self._items.items():
            channel = info.entry
            result.append({
                'name': name,
                'display_name': info.display_name or channel.display_name,
                'description': info.description,
                'origin': info.origin,
                'config_section': channel.config_section,
                'config_fields': channel.config_fields,
                'config': self._channel_config(channel),
            })
        return result

    def _channel_config(self, channel: NotifyChannel) -> dict:
        if not self.config_manager or not channel.config_section:
            return {}
        return self.config_manager.get_section(channel.config_section)

    def dispatch(self, event: Event) -> dict:
        """按订阅规则把事件分发给命中的启用渠道，返回 {channel_name: bool}。"""
        results = {}
        if not self.db_manager:
            logger.warning("NotifyCenter: db_manager 未注入，无法读取订阅规则")
            return results

        try:
            rules = self.db_manager.get_notify_rules()
        except Exception as e:
            logger.error(f"读取通知订阅规则失败: {e}")
            return results

        matched = None
        for rule in rules:
            if rule.get('event_type') == event.type:
                matched = rule
                break

        if not matched or not matched.get('enabled'):
            logger.debug(f"事件 {event.type} 无启用订阅规则，跳过")
            return results

        channel_names = self._parse_channels(matched.get('channels'))
        for name in channel_names:
            info = self._items.get(name)
            channel = info.entry if info else None
            if not channel:
                logger.warning(f"订阅了未注册的渠道: {name}")
                results[name] = False
                continue
            config = self._channel_config(channel)
            try:
                results[name] = bool(channel.send(config, event))
                logger.info(f"通知已发送: event={event.type} channel={name} ok={results[name]}")
            except Exception as e:
                results[name] = False
                logger.error(f"通知发送失败: event={event.type} channel={name}: {e}")
        return results

    def dispatch_async(self, event: Event):
        """后台线程分发，避免阻塞主流程。"""
        t = threading.Thread(target=self.dispatch, args=(event,), daemon=True)
        t.start()
        return t

    @staticmethod
    def _parse_channels(channels) -> list:
        """兼容 JSON 数组字符串或逗号分隔字符串。"""
        if not channels:
            return []
        if isinstance(channels, list):
            return [c for c in channels if c]
        s = str(channels).strip()
        if s.startswith('['):
            try:
                return [c for c in json.loads(s) if c]
            except Exception:
                pass
        return [c.strip() for c in s.split(',') if c.strip()]
