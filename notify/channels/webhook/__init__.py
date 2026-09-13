"""通用 Webhook 通知渠道（HTTP POST JSON）。

可用于对接钉钉/企微群机器人、自建服务、或任意接收 JSON 的 HTTP 端点。
"""
import json
from urllib import request

from registry.base import PluginInfo

from ...base import Event, NotifyChannel


class WebhookChannel(NotifyChannel):
    name = 'webhook'
    display_name = 'Webhook 通知'
    config_section = 'Notify.Webhook'
    config_fields = [
        {'name': 'url', 'label': 'Webhook URL', 'type': 'text', 'required': True},
    ]

    def send(self, config: dict, event: Event) -> bool:
        url = str(config.get('url', '')).strip()
        if not url:
            raise ValueError('Webhook URL 未配置')

        payload = {
            'event_type': event.type,
            'level': event.level,
            'title': event.title,
            'content': event.content,
            'meta': event.meta,
            'timestamp': event.timestamp,
        }
        data = json.dumps(payload).encode('utf-8')
        req = request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with request.urlopen(req, timeout=10) as resp:
            return resp.status < 400


INFO = PluginInfo(
    name='webhook',
    display_name='Webhook 通知',
    description='通过 HTTP POST JSON 对接钉钉/企微/自建服务',
    origin='system',
    entry=WebhookChannel(),
    tags=['通知', 'Webhook'],
)
