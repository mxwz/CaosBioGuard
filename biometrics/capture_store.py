"""加密原始采集样本与生物特征版本库。

设计目标：
- 原始人脸、指纹、虹膜等采集样本与提取后的模板均加密落盘；
- 每个 ``(subject, modality, device_id)`` 仅保留最近两个版本：0=上一版，1=当前版；
- 首次录入只有版本 1；再次录入时上一版降为 0，新版本为 1；
- 回退只切换激活游标，不删除历史版本；
- 重新录入时以当前激活版本作为上一版，旧的未激活版本会被覆盖清理。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .store import TemplateCipher
from .types import BioTemplate


@dataclass(frozen=True)
class CaptureVersion:
    subject: str
    modality: str
    device_id: str
    version: int
    active: bool
    image_bytes: bytes
    image_mime: str
    template: BioTemplate
    quality: float
    digest: str
    updated_at: float
    meta: Dict[str, Any]

    def to_dict(self, include_bytes: bool = False) -> Dict[str, Any]:
        data = {
            'subject': self.subject,
            'modality': self.modality,
            'device_id': self.device_id,
            'version': self.version,
            'active': self.active,
            'image_mime': self.image_mime,
            'quality': round(self.quality, 4),
            'digest': self.digest,
            'updated_at': self.updated_at,
            'meta': self.meta,
            'image_bytes': len(self.image_bytes),
            'template_bytes': self.template.size_bytes(),
        }
        if include_bytes:
            data['image_bytes'] = self.image_bytes
        return data


class CaptureRepository:
    """线程安全的原始样本与模板版本仓库。"""

    def __init__(self, db_path: str = './dd/capture_versions.db',
                 config_manager: Any = None,
                 cipher: Optional[TemplateCipher] = None,
                 allow_plaintext: bool = False):
        self.db_path = db_path
        self._lock = threading.RLock()
        if cipher is not None:
            self.cipher = cipher
        else:
            key = None
            if config_manager is not None:
                raw = config_manager.get_encryption_key()
                key = raw.encode() if isinstance(raw, str) else raw
            self.cipher = TemplateCipher(key, allow_plaintext=allow_plaintext)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or '.', exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bio_capture_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version IN (0,1)),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    image BLOB NOT NULL,
                    image_mime TEXT NOT NULL DEFAULT 'application/octet-stream',
                    template BLOB NOT NULL,
                    quality REAL NOT NULL DEFAULT 0,
                    digest TEXT NOT NULL,
                    meta TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(subject, modality, device_id, version)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_capture_lookup '
                         'ON bio_capture_versions(subject, modality, device_id, version)')
            conn.commit()

    def save_capture(self, subject: str, modality: str, image_bytes: bytes,
                     template: BioTemplate, device_id: str = 'admin',
                     image_mime: str = 'image/jpeg',
                     meta: Optional[Dict[str, Any]] = None) -> CaptureVersion:
        subject = str(subject).strip()
        if not subject:
            raise ValueError('subject 不能为空')
        if not image_bytes:
            raise ValueError('原始采集样本不能为空')
        now = time.time()
        meta = dict(meta or {})
        encrypted_image = self.cipher.encrypt(image_bytes)
        encrypted_template = self.cipher.encrypt(template.encode())
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                'SELECT id, version FROM bio_capture_versions WHERE subject=? AND modality=? AND device_id=? ORDER BY version',
                (subject, modality, device_id),
            ).fetchall()
            if rows:
                active_row = conn.execute(
                    'SELECT id, version FROM bio_capture_versions '
                    'WHERE subject=? AND modality=? AND device_id=? AND is_active=1',
                    (subject, modality, device_id),
                ).fetchone()
                source = active_row or rows[-1]
                source_row = conn.execute(
                    'SELECT * FROM bio_capture_versions WHERE id=?', (source['id'],)
                ).fetchone()
                # 只保留当前激活版本作为上一版；清理其它旧版本，避免超过两个版本。
                conn.execute(
                    'DELETE FROM bio_capture_versions WHERE subject=? AND modality=? AND device_id=?',
                    (subject, modality, device_id),
                )
                conn.execute(
                    'INSERT INTO bio_capture_versions '
                    '(subject, modality, device_id, version, is_active, image, image_mime, '
                    'template, quality, digest, meta, created_at, updated_at) '
                    'VALUES (?,?,?,0,0,?,?,?,?,?,?,?,?)',
                    (subject, modality, device_id, source_row['image'], source_row['image_mime'],
                     source_row['template'], source_row['quality'], source_row['digest'],
                     source_row['meta'], source_row['created_at'], now),
                )
            conn.execute(
                'INSERT INTO bio_capture_versions '
                '(subject, modality, device_id, version, is_active, image, image_mime, '
                'template, quality, digest, meta, created_at, updated_at) '
                'VALUES (?,?,?,1,1,?,?,?,?,?,?,?,?)',
                (subject, modality, device_id, encrypted_image, image_mime,
                 encrypted_template, float(template.quality), template.digest(),
                 json.dumps(meta, ensure_ascii=False), now, now),
            )
            conn.commit()
        result = self.get_version(subject, modality, device_id, 1)
        if result is None:
            raise RuntimeError('保存采集版本后读取失败')
        return result

    def _row_to_capture(self, row: sqlite3.Row) -> CaptureVersion:
        image_bytes = self.cipher.decrypt(row['image'])
        template = BioTemplate.decode(self.cipher.decrypt(row['template']))
        return CaptureVersion(
            subject=row['subject'], modality=row['modality'], device_id=row['device_id'],
            version=int(row['version']), active=bool(row['is_active']),
            image_bytes=image_bytes, image_mime=row['image_mime'], template=template,
            quality=float(row['quality']), digest=row['digest'],
            updated_at=float(row['updated_at']), meta=json.loads(row['meta'] or '{}'),
        )

    def get_version(self, subject: str, modality: str, device_id: str,
                    version: int) -> Optional[CaptureVersion]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                'SELECT * FROM bio_capture_versions '
                'WHERE subject=? AND modality=? AND device_id=? AND version=?',
                (subject, modality, device_id, int(version)),
            ).fetchone()
        return self._row_to_capture(row) if row else None

    def active_version(self, subject: str, modality: str,
                       device_id: str) -> Optional[CaptureVersion]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                'SELECT * FROM bio_capture_versions '
                'WHERE subject=? AND modality=? AND device_id=? AND is_active=1',
                (subject, modality, device_id),
            ).fetchone()
        return self._row_to_capture(row) if row else None

    def active_any_device(self, subject: str, modality: str) -> Optional[CaptureVersion]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                'SELECT * FROM bio_capture_versions '
                'WHERE subject=? AND modality=? AND is_active=1 '
                'ORDER BY updated_at DESC LIMIT 1',
                (subject, modality),
            ).fetchone()
        return self._row_to_capture(row) if row else None

    def list_versions(self, subject: str, modality: str,
                      device_id: str) -> List[CaptureVersion]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                'SELECT * FROM bio_capture_versions '
                'WHERE subject=? AND modality=? AND device_id=? ORDER BY version',
                (subject, modality, device_id),
            ).fetchall()
        return [self._row_to_capture(row) for row in rows]

    def rollback(self, subject: str, modality: str, device_id: str) -> CaptureVersion:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                'SELECT version FROM bio_capture_versions '
                'WHERE subject=? AND modality=? AND device_id=? ORDER BY version',
                (subject, modality, device_id),
            ).fetchall()
            versions = {int(row['version']) for row in rows}
            if 0 not in versions:
                raise ValueError('不存在可回退的上一版本')
            conn.execute(
                'UPDATE bio_capture_versions SET is_active=0, updated_at=? '
                'WHERE subject=? AND modality=? AND device_id=?',
                (time.time(), subject, modality, device_id),
            )
            conn.execute(
                'UPDATE bio_capture_versions SET is_active=1, updated_at=? '
                'WHERE subject=? AND modality=? AND device_id=? AND version=0',
                (time.time(), subject, modality, device_id),
            )
            conn.commit()
        result = self.active_version(subject, modality, device_id)
        if result is None:
            raise RuntimeError('回退后读取激活版本失败')
        return result

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            total = conn.execute('SELECT COUNT(*) AS c FROM bio_capture_versions').fetchone()['c']
            active = conn.execute('SELECT COUNT(*) AS c FROM bio_capture_versions WHERE is_active=1').fetchone()['c']
        return {'total_versions': int(total), 'active_versions': int(active)}
