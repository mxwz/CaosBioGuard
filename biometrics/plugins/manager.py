"""SDK 插件注册中心：安装、校验、启用、停用和适配器加载。"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters.base import VendorAdapter
from .manifest import PluginManifest
from .package import PluginPackage


@dataclass(frozen=True)
class RegisteredPlugin:
    plugin_id: str
    name: str
    version: str
    vendor: str
    modalities: List[str]
    path: str
    signed: bool
    enabled: bool
    status: str
    message: str
    installed_at: float
    updated_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'plugin_id': self.plugin_id,
            'name': self.name,
            'version': self.version,
            'vendor': self.vendor,
            'modalities': self.modalities,
            'path': self.path,
            'signed': self.signed,
            'enabled': self.enabled,
            'status': self.status,
            'message': self.message,
            'installed_at': self.installed_at,
            'updated_at': self.updated_at,
        }


class PluginManager:
    def __init__(self, plugin_root: str | Path = 'plugins/installed',
                 registry_db: str | Path = 'dd/plugin_registry.db',
                 trusted_key_dir: str | Path = 'plugins/trusted_keys',
                 allow_unsigned: bool = False):
        self.plugin_root = Path(plugin_root)
        self.registry_db = Path(registry_db)
        self.trusted_key_dir = Path(trusted_key_dir)
        self.allow_unsigned = bool(allow_unsigned)
        self._lock = threading.RLock()
        self.plugin_root.mkdir(parents=True, exist_ok=True)
        self.registry_db.parent.mkdir(parents=True, exist_ok=True)
        self.trusted_key_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.registry_db, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sdk_plugin_registry (
                    plugin_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    vendor TEXT NOT NULL,
                    modalities TEXT NOT NULL,
                    path TEXT NOT NULL,
                    signed INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    installed_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sdk_plugin_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plugin_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            ''')
            conn.commit()

    def _trusted_keys(self) -> List[Path]:
        keys = list(self.trusted_key_dir.glob('*.pem'))
        extra = os.environ.get('CAOS_PLUGIN_TRUSTED_KEYS', '')
        for item in extra.split(os.pathsep):
            if item:
                keys.append(Path(item))
        return keys

    def _audit(self, conn, plugin_id: str, action: str, detail: str = '') -> None:
        conn.execute(
            'INSERT INTO sdk_plugin_audit(plugin_id, action, detail, created_at) VALUES (?,?,?,?)',
            (plugin_id, action, detail, time.time()),
        )

    def install(self, source_path: str | Path, replace: bool = True) -> RegisteredPlugin:
        source_package = PluginPackage.open(
            source_path, self._trusted_keys(), allow_unsigned=self.allow_unsigned
        )
        manifest = source_package.manifest
        target = self.plugin_root / manifest.plugin_id
        with self._lock:
            if target.exists():
                if not replace:
                    raise FileExistsError(f'插件已存在: {manifest.plugin_id}')
                shutil.rmtree(target)
            shutil.copytree(source_package.root, target, symlinks=False)
            installed = PluginPackage.open(
                target, self._trusted_keys(), allow_unsigned=self.allow_unsigned
            )
            now = time.time()
            with self._conn() as conn:
                conn.execute('''
                    INSERT INTO sdk_plugin_registry
                    (plugin_id, name, version, vendor, modalities, path, signed,
                     enabled, status, message, installed_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(plugin_id) DO UPDATE SET
                        name=excluded.name, version=excluded.version,
                        vendor=excluded.vendor, modalities=excluded.modalities,
                        path=excluded.path, signed=excluded.signed,
                        status=excluded.status, message=excluded.message,
                        updated_at=excluded.updated_at
                ''', (
                    manifest.plugin_id, manifest.name, manifest.version, manifest.vendor,
                    json.dumps(manifest.modalities, ensure_ascii=False), str(target),
                    int(installed.signed), int(manifest.enabled_by_default),
                    'installed', '', now, now,
                ))
                self._audit(conn, manifest.plugin_id, 'install',
                            f'signed={installed.signed}; version={manifest.version}')
                conn.commit()
        return self.get(manifest.plugin_id)

    def list_plugins(self) -> List[RegisteredPlugin]:
        with self._lock, self._conn() as conn:
            rows = conn.execute('SELECT * FROM sdk_plugin_registry ORDER BY plugin_id').fetchall()
        return [self._row(row) for row in rows]

    def get(self, plugin_id: str) -> RegisteredPlugin:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                'SELECT * FROM sdk_plugin_registry WHERE plugin_id=?', (plugin_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f'插件不存在: {plugin_id}')
        return self._row(row)

    def set_enabled(self, plugin_id: str, enabled: bool) -> RegisteredPlugin:
        plugin = self.get(plugin_id)
        status, message = ('active', '') if enabled else ('disabled', '')
        if enabled:
            adapter = self.load_adapter(plugin_id)
            ok, reason = adapter.check_available()
            if not ok:
                status, message = 'error', reason
                enabled = False
        now = time.time()
        with self._lock, self._conn() as conn:
            conn.execute('''
                UPDATE sdk_plugin_registry
                SET enabled=?, status=?, message=?, updated_at=?
                WHERE plugin_id=?
            ''', (int(enabled), status, message, now, plugin_id))
            self._audit(conn, plugin_id, 'enable' if enabled else 'disable', message)
            conn.commit()
        return self.get(plugin_id)

    def health_check(self, plugin_id: str) -> tuple[bool, str]:
        try:
            return self.load_adapter(plugin_id).check_available()
        except Exception as exc:
            return False, str(exc)

    def load_adapter(self, plugin_id: str) -> VendorAdapter:
        plugin = self.get(plugin_id)
        manifest = PluginManifest.load(Path(plugin.path) / 'plugin.toml')
        module_name, class_name = manifest.adapter_class.rsplit('.', 1)
        module_path = Path(plugin.path) / f'{module_name.replace(".", "/")}.py'
        spec = importlib.util.spec_from_file_location(
            f'caos_plugin_{manifest.plugin_id.replace(".", "_")}', module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f'无法加载插件模块: {module_path}')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = getattr(module, class_name)
        config = {
            'plugin': manifest.to_dict(),
            'plugin_root': plugin.path,
            'model_path': manifest.model_path,
            'license_path': manifest.license_path,
            **manifest.native_libraries,
        }
        adapter = cls(config=config)
        if not isinstance(adapter, VendorAdapter):
            raise TypeError('插件适配器必须继承 VendorAdapter')
        return adapter

    @staticmethod
    def _row(row: sqlite3.Row) -> RegisteredPlugin:
        return RegisteredPlugin(
            plugin_id=row['plugin_id'], name=row['name'], version=row['version'],
            vendor=row['vendor'], modalities=json.loads(row['modalities']),
            path=row['path'], signed=bool(row['signed']), enabled=bool(row['enabled']),
            status=row['status'], message=row['message'],
            installed_at=float(row['installed_at']), updated_at=float(row['updated_at']),
        )
