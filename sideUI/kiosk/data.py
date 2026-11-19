"""Kiosk 数据层：配置、考勤事件库、主体仓库（人脸 + 多模态模板）。"""

from __future__ import annotations

import csv
import json
import os
import pickle
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from biometrics import BioTemplateStore

ROOT = Path(__file__).resolve().parents[2]
DD_DIR = ROOT / 'dd'
DD_DIR.mkdir(parents=True, exist_ok=True)


class KioskConfig:
    """只读写 UI/Kiosk 相关键，避免碰云端隐私配置。"""

    def __init__(self, path: Optional[Path] = None):
        import configparser
        self._lock = threading.RLock()
        self.path = Path(path or (ROOT / 'config.ini'))
        self._parser = configparser.ConfigParser()
        if self.path.exists():
            self._parser.read(self.path, encoding='utf-8')
        self._defaults()

    def _defaults(self) -> None:
        self._ensure('UI', {'theme': 'obsidian'})
        self._ensure('Kiosk', {
            'camera_index': '0',
            'fullscreen': '1',
            'threshold': '0.40',
            'liveness_mode': 'strict',
            'liveness_threshold': '0.72',
            'cooldown': '3.0',
            'device_id': 'EDGE-KIOSK-01',
            'company': 'Caos BioGuard',
            'admin_pin': '',
        })

    def _ensure(self, section: str, values: Dict[str, str]) -> None:
        if section not in self._parser:
            self._parser[section] = {}
        for k, v in values.items():
            if k not in self._parser[section]:
                self._parser[section][k] = v

    def get(self, section: str, key: str, fallback: str = '') -> str:
        with self._lock:
            return self._parser.get(section, key, fallback=fallback)

    def get_int(self, section: str, key: str, fallback: int = 0) -> int:
        try:
            return int(float(self.get(section, key, str(fallback))))
        except Exception:
            return fallback

    def get_float(self, section: str, key: str, fallback: float = 0.0) -> float:
        try:
            return float(self.get(section, key, str(fallback)))
        except Exception:
            return fallback

    def get_bool(self, section: str, key: str, fallback: bool = False) -> bool:
        return self.get(section, key, '1' if fallback else '0').strip().lower() in ('1', 'true', 'yes', 'on')

    def get_section(self, section: str) -> Dict[str, str]:
        with self._lock:
            if not self._parser.has_section(section):
                return {}
            return dict(self._parser[section])

    def get_encryption_key(self) -> str:
        with self._lock:
            if self._parser.has_option('Security', 'encryptionkey'):
                return self._parser.get('Security', 'encryptionkey')
            return self._parser.get('Security', 'EncryptionKey', fallback='')

    def set(self, section: str, key: str, value: Any) -> None:
        with self._lock:
            if section not in self._parser:
                self._parser[section] = {}
            self._parser[section][key] = str(value)
            with open(self.path, 'w', encoding='utf-8') as f:
                self._parser.write(f)


@dataclass
class EdgeEvent:
    ts: float
    subject: str
    modality: str
    score: float
    liveness: float
    passed: bool
    device_id: str = ''
    detail: str = ''
    snapshot: str = ''

    @property
    def time_text(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime('%H:%M:%S')

    @property
    def date_text(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime('%Y-%m-%d')

    @property
    def result_text(self) -> str:
        return '通过' if self.passed else '拒绝'


class EventStore:
    """本地考勤/门禁事件库（WAL，线程安全）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.path = Path(db_path or (DD_DIR / 'kiosk_events.db'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                subject TEXT NOT NULL,
                modality TEXT NOT NULL,
                score REAL DEFAULT 0,
                liveness REAL DEFAULT 0,
                passed INTEGER DEFAULT 0,
                device_id TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                snapshot TEXT DEFAULT ''
            )''')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC)')
        self._conn.commit()

    def add(self, event: EdgeEvent) -> int:
        with self._lock:
            cur = self._conn.execute(
                'INSERT INTO events(ts,subject,modality,score,liveness,passed,device_id,detail,snapshot) '
                'VALUES(?,?,?,?,?,?,?,?,?)',
                (event.ts, event.subject, event.modality, event.score, event.liveness,
                 int(event.passed), event.device_id, event.detail, event.snapshot))
            self._conn.commit()
            return int(cur.lastrowid)

    def recent(self, limit: int = 80, result: str = '', modality: str = '') -> List[EdgeEvent]:
        sql = 'SELECT ts,subject,modality,score,liveness,passed,device_id,detail,snapshot FROM events WHERE 1=1'
        params: list = []
        if result == 'pass':
            sql += ' AND passed=1'
        elif result == 'deny':
            sql += ' AND passed=0'
        if modality:
            sql += ' AND modality=?'
            params.append(modality)
        sql += ' ORDER BY ts DESC LIMIT ?'
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [EdgeEvent(*r) for r in rows]

    def stats_today(self) -> Dict[str, int]:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self._lock:
            total = self._conn.execute('SELECT COUNT(*) FROM events WHERE ts>=?', (start,)).fetchone()[0]
            passed = self._conn.execute('SELECT COUNT(*) FROM events WHERE ts>=? AND passed=1',
                                        (start,)).fetchone()[0]
        return {'total': total, 'passed': passed, 'denied': total - passed}

    def export_csv(self, target: Path, limit: int = 5000) -> Path:
        rows = self.recent(limit=limit)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['时间', '主体', '模态', '分数', '活体', '结果', '设备', '详情'])
            for e in rows:
                writer.writerow([datetime.fromtimestamp(e.ts).strftime('%Y-%m-%d %H:%M:%S'),
                                 e.subject, e.modality, f'{e.score:.3f}', f'{e.liveness:.3f}',
                                 e.result_text, e.device_id, e.detail])
        return target

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class SubjectRepository:
    """统一主体视图：人脸库（兼容旧 pkl）+ 多模态模板库。"""

    def __init__(self, config: Optional[KioskConfig] = None):
        self.config = config or KioskConfig()
        self.face_db_path = Path(self.config.get('Paths', 'face_database', str(DD_DIR / 'face_database.pkl')))
        if not self.face_db_path.is_absolute():
            self.face_db_path = ROOT / self.face_db_path
        self._lock = threading.RLock()
        self._faces: Dict[str, np.ndarray] = self._load_faces()
        self.images_dir = self.face_db_path.parent / 'face_images'
        self.images_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.bio_store = BioTemplateStore(
                str(DD_DIR / 'biometrics.db'), config_manager=self.config
            )
        except Exception:
            self.bio_store = None

    def _load_faces(self) -> Dict[str, np.ndarray]:
        if not self.face_db_path.exists():
            return {}
        try:
            with open(self.face_db_path, 'rb') as f:
                data = pickle.load(f)
            return {str(k): np.asarray(v, dtype=np.float32) for k, v in data.items()}
        except Exception:
            return {}

    def _persist(self) -> None:
        self.face_db_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.face_db_path, 'wb') as f:
            pickle.dump(self._faces, f)

    def names(self) -> List[str]:
        with self._lock:
            names = set(self._faces.keys())
        if self.bio_store:
            try:
                names.update(self.bio_store.subjects())
            except Exception:
                pass
        return sorted(names)

    def embedding(self, name: str) -> Optional[np.ndarray]:
        with self._lock:
            emb = self._faces.get(name)
        return emb.copy() if emb is not None else None

    def gallery(self) -> Tuple[List[str], Optional[np.ndarray]]:
        with self._lock:
            names = list(self._faces.keys())
            if not names:
                return [], None
            mat = np.stack([self._faces[n] for n in names]).astype(np.float32)
        return names, mat

    def add_face(self, name: str, embedding: np.ndarray, image: Optional[np.ndarray] = None) -> None:
        with self._lock:
            self._faces[name] = np.asarray(embedding, dtype=np.float32)
            self._persist()
        if image is not None:
            self.save_image(name, image)

    def remove(self, name: str) -> None:
        with self._lock:
            if name in self._faces:
                del self._faces[name]
                self._persist()
        for ext in ('.jpg', '.png', '.jpeg'):
            p = self.images_dir / f'{name}{ext}'
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        if self.bio_store:
            try:
                self.bio_store.delete(name)
            except Exception:
                pass

    def image_path(self, name: str) -> Optional[Path]:
        key = name.replace('/', '_')
        for ext in ('.jpg', '.png', '.jpeg'):
            p = self.images_dir / f'{key}{ext}'
            if p.exists():
                return p
        return None

    def save_image(self, name: str, image: np.ndarray) -> Optional[Path]:
        try:
            import cv2
            target = self.images_dir / f'{name}.jpg'
            cv2.imwrite(str(target), image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            return target
        except Exception:
            return None

    def bio_summary(self) -> Dict[str, int]:
        if not self.bio_store:
            return {}
        try:
            stats = self.bio_store.stats()
            return stats.get('by_modality', {}) if isinstance(stats, dict) else {}
        except Exception:
            return {}
