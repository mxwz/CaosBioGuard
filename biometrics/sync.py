"""云边同步加固：Outbox + HMAC + 幂等键 + 指数退避。

设计目标（对应审计结论）：
- 边缘端不再直接 ``requests.post`` 云端，而是先落本地 outbox，断网可恢复；
- 每条事件带 ``idempotency_key``，云端按 key 去重，重放安全；
- 请求体与时间戳做 HMAC-SHA256，防篡改/重放；
- 失败按指数退避 + 抖动重排，避免雪崩；
- 批量为单位确认，成功才标记 acked，保留审计记录。

云端只需实现 ``POST /api/sync/events``：校验签名、按 idempotency_key 去重、
返回 ``{"accepted": [...], "duplicates": [...]}``。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import sqlite3
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sign_payload(secret: str, timestamp: int, body: str) -> str:
    message = f'{timestamp}.{body}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp: int, body: str, signature: str,
                     max_skew: int = 300) -> bool:
    if abs(int(time.time()) - int(timestamp)) > max_skew:
        return False
    return hmac.compare_digest(sign_payload(secret, timestamp, body), signature or '')


@dataclass
class SyncConfig:
    endpoint: str = ''
    secret: str = ''
    device_id: str = 'edge'
    batch_size: int = 20
    max_attempts: int = 8
    base_delay: float = 2.0
    timeout: float = 8.0

    @classmethod
    def from_config(cls, config_manager: Any, default_device: str = 'edge') -> 'SyncConfig':
        try:
            section = config_manager.get_section('Sync') or {}
        except Exception:
            section = {}
        return cls(
            endpoint=str(section.get('endpoint') or ''),
            secret=str(section.get('secret') or ''),
            device_id=str(section.get('device_id') or default_device),
            batch_size=max(1, int(section.get('batch_size') or 20)),
            max_attempts=max(1, int(section.get('max_attempts') or 8)),
            base_delay=max(0.5, float(section.get('base_delay') or 2.0)),
            timeout=max(1.0, float(section.get('timeout') or 8.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {'endpoint': self.endpoint, 'device_id': self.device_id,
                'batch_size': self.batch_size, 'max_attempts': self.max_attempts,
                'base_delay': self.base_delay, 'timeout': self.timeout,
                'has_secret': bool(self.secret)}


class SyncOutbox:
    """SQLite 持久化 outbox；线程安全，进程重启不丢。"""

    def __init__(self, db_path: str = './dd/sync_outbox.db'):
        self.db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or '.', exist_ok=True)
        with self._conn() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS sync_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_at REAL NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                acked_at REAL
            )''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_outbox_status ON sync_outbox(status, next_at)')

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def enqueue(self, event_type: str, payload: Dict[str, Any],
                key: Optional[str] = None) -> str:
        key = key or f'{event_type}:{uuid.uuid4().hex}'
        with self._lock, self._conn() as conn:
            existing = conn.execute('SELECT id FROM sync_outbox WHERE idempotency_key=?', (key,)).fetchone()
            if existing:
                return key
            conn.execute(
                'INSERT INTO sync_outbox(event_type,payload,idempotency_key,created_at) VALUES(?,?,?,?)',
                (event_type, canonical_json(payload), key, time.time()),
            )
        return key

    def pending(self, limit: int = 20, now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = time.time() if now is None else now
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sync_outbox WHERE status IN ('pending','retry') AND next_at<=? "
                'ORDER BY id ASC LIMIT ?', (now, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_acked(self, keys: List[str]) -> int:
        if not keys:
            return 0
        with self._lock, self._conn() as conn:
            n = 0
            for key in keys:
                cur = conn.execute(
                    "UPDATE sync_outbox SET status='acked', acked_at=? WHERE idempotency_key=?",
                    (time.time(), key),
                )
                n += cur.rowcount
        return n

    def mark_retry(self, key: str, error: str, next_at: float, max_attempts: int) -> str:
        with self._lock, self._conn() as conn:
            row = conn.execute('SELECT attempts FROM sync_outbox WHERE idempotency_key=?', (key,)).fetchone()
            attempts = int(row['attempts'] if row else 0) + 1
            status = 'dead' if attempts >= max_attempts else 'retry'
            conn.execute(
                'UPDATE sync_outbox SET attempts=?, status=?, next_at=?, last_error=? WHERE idempotency_key=?',
                (attempts, status, next_at, error[:500], key),
            )
        return status

    def stats(self) -> Dict[str, int]:
        with self._lock, self._conn() as conn:
            rows = conn.execute('SELECT status, COUNT(*) AS n FROM sync_outbox GROUP BY status').fetchall()
        return {r['status']: int(r['n']) for r in rows}

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sync_outbox WHERE status='dead' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


Transport = Callable[[str, str, Dict[str, str], float], Dict[str, Any]]


def _urllib_transport(url: str, body: str, headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=body.encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode('utf-8')
    return json.loads(raw) if raw else {}


class SyncClient:
    """把 outbox 批量推送到云端；可注入 transport 便于测试。"""

    def __init__(self, config: SyncConfig, outbox: SyncOutbox,
                 transport: Optional[Transport] = None):
        self.config = config
        self.outbox = outbox
        self.transport = transport or _urllib_transport

    def _next_at(self, attempts: int) -> float:
        delay = min(self.config.base_delay * (2 ** max(attempts - 1, 0)), 3600.0)
        return time.time() + delay + random.uniform(0, delay * 0.3)

    def flush(self, limit: Optional[int] = None) -> Dict[str, Any]:
        limit = limit or self.config.batch_size
        items = self.outbox.pending(limit)
        if not items:
            return {'sent': 0, 'acked': 0, 'failed': 0, 'duplicates': 0}
        if not self.config.endpoint or not self.config.secret:
            return {'sent': 0, 'acked': 0, 'failed': 0, 'error': '缺少 [Sync] endpoint/secret'}

        events = [{'idempotency_key': it['idempotency_key'],
                   'type': it['event_type'],
                   'payload': json.loads(it['payload']),
                   'created_at': it['created_at']} for it in items]
        envelope = {'device_id': self.config.device_id, 'events': events,
                    'sent_at': time.time()}
        body = canonical_json(envelope)
        timestamp = int(time.time())
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'X-Caos-Device': self.config.device_id,
            'X-Caos-Timestamp': str(timestamp),
            'X-Caos-Signature': sign_payload(self.config.secret, timestamp, body),
        }
        try:
            result = self.transport(self.config.endpoint, body, headers, self.config.timeout)
        except Exception as exc:
            for it in items:
                self.outbox.mark_retry(it['idempotency_key'], str(exc),
                                       self._next_at(it['attempts'] + 1), self.config.max_attempts)
            return {'sent': 0, 'acked': 0, 'failed': len(items), 'error': str(exc)}

        accepted = result.get('accepted') or []
        duplicates = result.get('duplicates') or []
        acked = self.outbox.mark_acked(list(accepted)) if accepted else 0
        if duplicates:
            self.outbox.mark_acked(list(duplicates))
        failed = len(items) - len(accepted) - len(duplicates)
        if failed > 0:
            for it in items:
                if it['idempotency_key'] not in accepted and it['idempotency_key'] not in duplicates:
                    self.outbox.mark_retry(it['idempotency_key'], '云端未确认',
                                           self._next_at(it['attempts'] + 1), self.config.max_attempts)
        return {'sent': len(items), 'acked': acked, 'failed': max(failed, 0),
                'duplicates': len(duplicates)}
