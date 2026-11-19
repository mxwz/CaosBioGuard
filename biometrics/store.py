"""加密生物特征模板库（SQLite + Fernet）。

- 只落库**不可逆模板**，不保存人脸/指纹原图；
- 同一 ``(subject, modality, device_id)`` 唯一，重复注册按质量择优覆盖；
- 支持按设备隔离（与现有 device_id 机制一致）；
- 模板整体加密后存储，密钥复用 ``config.ini [Security] encryptionkey``。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .base import ModalityEngine
from .types import BioTemplate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 加密
# ---------------------------------------------------------------------------


class TemplateCipher:
    """Fernet 加密封装；缺少 cryptography 时退化为带前缀的明文并告警。"""

    PREFIX = b'CAOSBIO1:'

    def __init__(self, key: Optional[bytes] = None):
        self._fernet = None
        self.enabled = False
        try:
            from cryptography.fernet import Fernet
            if key:
                self._fernet = Fernet(key)
                self.enabled = True
        except Exception as exc:
            logger.warning(f'模板加密不可用，将以明文存储: {exc}')

    def encrypt(self, data: bytes) -> bytes:
        if self.enabled and self._fernet is not None:
            return self.PREFIX + self._fernet.encrypt(data)
        return data

    def decrypt(self, data: bytes) -> bytes:
        if self.enabled and self._fernet is not None and data.startswith(self.PREFIX):
            return self._fernet.decrypt(data[len(self.PREFIX):])
        return data


def _cipher_from_config(config_manager: Any) -> TemplateCipher:
    key = None
    if config_manager is not None:
        try:
            raw = config_manager.get_encryption_key()
            if raw:
                key = raw.encode() if isinstance(raw, str) else raw
        except Exception as exc:
            logger.warning(f'读取加密密钥失败: {exc}')
    return TemplateCipher(key)


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------


@dataclass
class StoredTemplate:
    subject: str
    modality: str
    device_id: str
    backend: str
    template: BioTemplate
    quality: float
    updated_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'subject': self.subject, 'modality': self.modality,
            'device_id': self.device_id, 'backend': self.backend,
            'quality': round(self.quality, 3),
            'updated_at': self.updated_at,
            'template_bytes': self.template.size_bytes(),
        }


class BioTemplateStore:
    """线程安全的模板库。"""

    def __init__(self, db_path: str = './dd/biometrics.db', config_manager: Any = None,
                 cipher: Optional[TemplateCipher] = None):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.cipher = cipher or _cipher_from_config(config_manager)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or '.', exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bio_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    device_id TEXT NOT NULL DEFAULT 'admin',
                    backend TEXT NOT NULL DEFAULT 'model',
                    template BLOB NOT NULL,
                    quality REAL DEFAULT 0,
                    digest TEXT NOT NULL,
                    version INTEGER DEFAULT 1,
                    meta TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(subject, modality, device_id, backend)
                )
            ''')
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(bio_templates)')}
            if 'backend' not in columns:
                self._migrate_backend_column(conn)
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bio_modality ON bio_templates(modality)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bio_subject ON bio_templates(subject)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bio_backend ON bio_templates(backend)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bio_enroll_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT, modality TEXT, device_id TEXT,
                    action TEXT, quality REAL, detail TEXT, created_at REAL
                )
            ''')
            conn.commit()

    @staticmethod
    def _migrate_backend_column(conn: sqlite3.Connection) -> None:
        conn.execute('ALTER TABLE bio_templates RENAME TO bio_templates_old')
        conn.execute('''
            CREATE TABLE bio_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                modality TEXT NOT NULL,
                device_id TEXT NOT NULL DEFAULT 'admin',
                backend TEXT NOT NULL DEFAULT 'model',
                template BLOB NOT NULL,
                quality REAL DEFAULT 0,
                digest TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                meta TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(subject, modality, device_id, backend)
            )
        ''')
        conn.execute('''
            INSERT INTO bio_templates
                (subject, modality, device_id, backend, template, quality, digest,
                 version, meta, created_at, updated_at)
            SELECT subject, modality, device_id, 'model', template, quality, digest,
                   version, meta, created_at, updated_at
            FROM bio_templates_old
        ''')
        conn.execute('DROP TABLE bio_templates_old')

    # ------------------------------------------------------------------
    def save(self, subject: str, template: BioTemplate, device_id: str = 'admin',
             replace_lower_quality: bool = True, backend: Optional[str] = None) -> bool:
        subject = str(subject).strip()
        if not subject:
            raise ValueError('subject 不能为空')
        backend = (backend or template.meta.get('backend', 'model')).lower()
        blob = self.cipher.encrypt(template.encode())
        digest = template.digest()
        now = time.time()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                'SELECT quality FROM bio_templates WHERE subject=? AND modality=? AND device_id=? AND backend=?',
                (subject, template.modality, device_id, backend),
            ).fetchone()
            if row and replace_lower_quality and float(row['quality']) > template.quality:
                self._log(conn, subject, template.modality, device_id,
                          f'skip-lower-quality-{backend}', template.quality)
                conn.commit()
                return False
            conn.execute('''
                INSERT INTO bio_templates
                    (subject, modality, device_id, backend, template, quality, digest,
                     version, meta, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(subject, modality, device_id, backend) DO UPDATE SET
                    template=excluded.template, quality=excluded.quality, digest=excluded.digest,
                    version=excluded.version, meta=excluded.meta, updated_at=excluded.updated_at
            ''', (subject, template.modality, device_id, backend, blob, template.quality,
                  digest, int(template.version), json.dumps(template.meta, ensure_ascii=False), now, now))
            self._log(conn, subject, template.modality, device_id, f'upsert-{backend}', template.quality)
            conn.commit()
        return True

    def _log(self, conn, subject, modality, device_id, action, quality, detail=''):
        conn.execute(
            'INSERT INTO bio_enroll_log (subject, modality, device_id, action, quality, detail, created_at) VALUES (?,?,?,?,?,?,?)',
            (subject, modality, device_id, action, float(quality), detail, time.time()),
        )

    # ------------------------------------------------------------------
    def load(self, subject: str, modality: str, device_id: Optional[str] = None,
             backend: Optional[str] = None) -> Optional[BioTemplate]:
        sql = 'SELECT template FROM bio_templates WHERE subject=? AND modality=?'
        args: List[Any] = [subject, modality]
        if device_id:
            sql += ' AND device_id=?'
            args.append(device_id)
        if backend:
            sql += ' AND backend=?'
            args.append(backend)
        with self._lock, self._conn() as conn:
            row = conn.execute(sql + ' ORDER BY quality DESC LIMIT 1', args).fetchone()
        if not row:
            return None
        return BioTemplate.decode(self.cipher.decrypt(row['template']))

    def get_entry(self, subject: str, modality: str, device_id: Optional[str] = None,
                  backend: Optional[str] = None) -> Optional[StoredTemplate]:
        sql = 'SELECT * FROM bio_templates WHERE subject=? AND modality=?'
        args: List[Any] = [subject, modality]
        if device_id:
            sql += ' AND device_id=?'
            args.append(device_id)
        if backend:
            sql += ' AND backend=?'
            args.append(backend)
        with self._lock, self._conn() as conn:
            row = conn.execute(sql + ' ORDER BY quality DESC LIMIT 1', args).fetchone()
        if not row:
            return None
        return StoredTemplate(row['subject'], row['modality'], row['device_id'], row['backend'],
                              BioTemplate.decode(self.cipher.decrypt(row['template'])),
                              float(row['quality']), float(row['updated_at']))

    def gallery(self, modality: str, device_id: Optional[str] = None,
                backend: Optional[str] = None) -> List[Tuple[str, BioTemplate]]:
        sql = 'SELECT subject, template, backend, quality FROM bio_templates WHERE modality=?'
        args: List[Any] = [modality]
        if device_id:
            sql += ' AND device_id=?'
            args.append(device_id)
        if backend:
            sql += ' AND backend=?'
            args.append(backend)
        with self._lock, self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()

        if backend:
            out = []
            for row in rows:
                try:
                    out.append((row['subject'],
                                BioTemplate.decode(self.cipher.decrypt(row['template']))))
                except Exception as exc:
                    logger.warning(f'模板解码失败 {row["subject"]}/{modality}: {exc}')
            return out

        grouped: Dict[str, List[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row['subject'], []).append(row)
        out = []
        for subject, entries in grouped.items():
            preferred = next((r for r in entries if r['backend'] == 'sdk'), None)
            row = preferred or max(entries, key=lambda r: r['quality'])
            try:
                out.append((subject, BioTemplate.decode(self.cipher.decrypt(row['template']))))
            except Exception as exc:
                logger.warning(f'模板解码失败 {subject}/{modality}: {exc}')
        return out

    def subjects(self, modality: Optional[str] = None, device_id: Optional[str] = None) -> List[str]:
        sql = 'SELECT DISTINCT subject FROM bio_templates'
        cond, args = [], []
        if modality:
            cond.append('modality=?')
            args.append(modality)
        if device_id:
            cond.append('device_id=?')
            args.append(device_id)
        if cond:
            sql += ' WHERE ' + ' AND '.join(cond)
        with self._lock, self._conn() as conn:
            return [r['subject'] for r in conn.execute(sql + ' ORDER BY subject', args).fetchall()]

    def modalities_of(self, subject: str, device_id: Optional[str] = None) -> List[str]:
        sql = 'SELECT modality FROM bio_templates WHERE subject=?'
        args: List[Any] = [subject]
        if device_id:
            sql += ' AND device_id=?'
            args.append(device_id)
        with self._lock, self._conn() as conn:
            return [r['modality'] for r in conn.execute(sql, args).fetchall()]

    def delete(self, subject: str, modality: Optional[str] = None, device_id: Optional[str] = None,
               backend: Optional[str] = None) -> int:
        sql = 'DELETE FROM bio_templates WHERE subject=?'
        args: List[Any] = [subject]
        if modality:
            sql += ' AND modality=?'
            args.append(modality)
        if device_id:
            sql += ' AND device_id=?'
            args.append(device_id)
        if backend:
            sql += ' AND backend=?'
            args.append(backend)
        with self._lock, self._conn() as conn:
            cur = conn.execute(sql, args)
            conn.commit()
            return int(cur.rowcount or 0)

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                'SELECT modality, backend, COUNT(*) AS n, AVG(quality) AS q '
                'FROM bio_templates GROUP BY modality, backend'
            ).fetchall()
            total = conn.execute('SELECT COUNT(*) AS n FROM bio_templates').fetchone()['n']
        modalities: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            item = modalities.setdefault(row['modality'], {'count': 0, 'backends': {}})
            item['count'] += int(row['n'])
            item['backends'][row['backend']] = {
                'count': int(row['n']),
                'avg_quality': round(float(row['q'] or 0), 3),
            }
        return {
            'total': int(total),
            'encrypted': bool(self.cipher.enabled),
            'modalities': modalities,
        }

    def locate_gallery(self, modality: str, engine: ModalityEngine,
                       probe: BioTemplate, device_id: Optional[str] = None,
                       threshold: Optional[float] = None,
                       margin_threshold: float = 0.05):
        """1:N 检索：返回最佳 MatchResult（含 margin）。"""
        backend = probe.meta.get('backend')
        entries = self.gallery(modality, device_id, backend=backend)
        if not entries:
            from .types import MatchResult
            return MatchResult(modality, 0.0, threshold or engine.threshold, False, '')
        from .base import TemplateGallery
        gallery = TemplateGallery(entries)
        return gallery.match(probe, engine.compare, threshold or engine.threshold, margin_threshold)
