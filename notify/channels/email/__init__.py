"""邮件通知渠道（SMTP）。"""
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from registry.base import PluginInfo

from ...base import Event, NotifyChannel


class EmailChannel(NotifyChannel):
    name = 'email'
    display_name = '邮件'
    config_section = 'Notify.Email'
    config_fields = [
        {'name': 'smtp_host', 'label': 'SMTP 服务器', 'type': 'text', 'required': True},
        {'name': 'smtp_port', 'label': 'SMTP 端口', 'type': 'number', 'required': True},
        {'name': 'smtp_user', 'label': '发件账号', 'type': 'text', 'required': True},
        {'name': 'smtp_password', 'label': '授权码/密码', 'type': 'password', 'required': True, 'secret': True},
        {'name': 'from_addr', 'label': '发件人地址', 'type': 'text', 'required': True},
        {'name': 'to_addrs', 'label': '收件人（逗号分隔）', 'type': 'text', 'required': True},
        {'name': 'use_ssl', 'label': '使用 SSL', 'type': 'checkbox', 'required': False},
    ]

    def send(self, config: dict, event: Event) -> bool:
        host = str(config.get('smtp_host', '')).strip()
        port = int(config.get('smtp_port', 465) or 465)
        user = str(config.get('smtp_user', '')).strip()
        password = str(config.get('smtp_password', '')).strip()
        from_addr = str(config.get('from_addr', '') or user).strip()
        to_addrs = [a.strip() for a in str(config.get('to_addrs', '')).split(',') if a.strip()]
        use_ssl = str(config.get('use_ssl', 'true')).strip().lower() in ('true', '1', 'yes', 'on')

        if not host or not user or not password or not to_addrs:
            raise ValueError('SMTP 配置不完整')

        subject = f"[CaosBioGuard][{event.level}] {event.title or event.type}"
        body = event.content or ''
        if event.meta:
            body += '\n\n---\n'
            body += '\n'.join(f'{k}: {v}' for k, v in event.meta.items())

        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = formataddr((str(Header('CaosBioGuard', 'utf-8')), from_addr))
        msg['To'] = ', '.join(to_addrs)

        # SSL 优先走 SMTP_SSL，否则走 STARTTLS
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls(context=ssl.create_default_context())

        try:
            server.login(user, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
            return True
        finally:
            try:
                server.quit()
            except Exception:
                pass


INFO = PluginInfo(
    name='email',
    display_name='邮件',
    description='通过 SMTP 发送邮件通知',
    origin='system',
    entry=EmailChannel(),
    tags=['通知', '邮件'],
)
