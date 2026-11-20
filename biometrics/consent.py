"""生物识别单独同意记录仓库。

保存同意、撤回、协议版本、协议哈希和审计信息；不保存原始生物样本或完整模板。
同意记录属于个人信息处理记录，应放在受控数据目录并限制访问。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ConsentRecord:
    id: int
    subject: str
    modality: str
    device_id: str
    status: str
    consent_version: str
    consent_hash: str
    storage_location: str
    source_ip: str
    created_at: float
    updated_at: float
    record_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'subject': self.subject,
            'modality': self.modality,
            'device_id': self.device_id,
            'status': self.status,
            'consent_version': self.consent_version,
            'consent_hash': self.consent_hash,
            'storage_location': self.storage_location,
            'source_ip': self.source_ip,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'record_hash': self.record_hash,
        }


class ConsentRepository:
    """线程安全的单独同意记录仓库。"""

    def __init__(self, db_path: str = './dd/consent_records.db'):
        self.db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or '.', exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bio_consent_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('granted','withdrawn')),
                    consent_version TEXT NOT NULL,
                    consent_hash TEXT NOT NULL,
                    storage_location TEXT NOT NULL DEFAULT 'local-encrypted',
                    source_ip TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    record_hash TEXT NOT NULL
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_consent_lookup '
                         'ON bio_consent_records(subject, modality, device_id, id DESC)')
            conn.commit()

    @staticmethod
    def _hash_payload(payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def grant(self, subject: str, modality: str, consent_version: str, consent_hash: str,
              device_id: str = 'admin', storage_location: str = 'local-encrypted',
              source_ip: str = '') -> ConsentRecord:
        return self._write(
            subject, modality, 'granted', consent_version, consent_hash,
            device_id, storage_location, source_ip
        )

    def withdraw(self, subject: str, modality: str, consent_version: str, consent_hash: str,
                 device_id: str = 'admin', storage_location: str = 'local-encrypted',
                 source_ip: str = '') -> ConsentRecord:
        return self._write(
            subject, modality, 'withdrawn', consent_version, consent_hash,
            device_id, storage_location, source_ip
        )

    def _write(self, subject: str, modality: str, status: str, consent_version: str,
               consent_hash: str, device_id: str, storage_location: str,
               source_ip: str) -> ConsentRecord:
        subject = str(subject).strip()
        modality = str(modality).strip()
        if not subject or not modality:
            raise ValueError('subject 和 modality 不能为空')
        if not consent_version or not consent_hash:
            raise ValueError('协议版本和协议哈希不能为空')
        now = time.time()
        payload = {
            'subject': subject,
            'modality': modality,
            'device_id': device_id,
            'status': status,
            'consent_version': consent_version,
            'consent_hash': consent_hash,
            'storage_location': storage_location,
            'source_ip': source_ip,
            'created_at': now,
            'updated_at': now,
        }
        record_hash = self._hash_payload(payload)
        with self._lock, self._conn() as conn:
            cur = conn.execute('''
                INSERT INTO bio_consent_records
                (subject, modality, device_id, status, consent_version, consent_hash,
                 storage_location, source_ip, created_at, updated_at, record_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ''', (subject, modality, device_id, status, consent_version, consent_hash,
                  storage_location, source_ip, now, now, record_hash))
            conn.commit()
            row_id = int(cur.lastrowid)
            row = conn.execute('SELECT * FROM bio_consent_records WHERE id=?', (row_id,)).fetchone()
        return self._row_to_record(row)

    def latest(self, subject: str, modality: str, device_id: str) -> Optional[ConsentRecord]:
        with self._lock, self._conn() as conn:
            row = conn.execute('''
                SELECT * FROM bio_consent_records
                WHERE subject=? AND modality=? AND device_id=?
                ORDER BY id DESC LIMIT 1
            ''', (subject, modality, device_id)).fetchone()
        return self._row_to_record(row) if row else None

    def list_for(self, subject: str, device_id: Optional[str] = None) -> List[ConsentRecord]:
        sql = 'SELECT * FROM bio_consent_records WHERE subject=?'
        args: list[Any] = [subject]
        if device_id:
            sql += ' AND device_id=?'
            args.append(device_id)
        sql += ' ORDER BY id DESC'
        with self._lock, self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ConsentRecord:
        return ConsentRecord(
            id=int(row['id']), subject=row['subject'], modality=row['modality'],
            device_id=row['device_id'], status=row['status'],
            consent_version=row['consent_version'], consent_hash=row['consent_hash'],
            storage_location=row['storage_location'], source_ip=row['source_ip'],
            created_at=float(row['created_at']), updated_at=float(row['updated_at']),
            record_hash=row['record_hash'],
        )
