"""SDK 插件包完整性与签名校验。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .manifest import MANIFEST_NAME, PluginManifest

SIGNATURE_NAME = 'signature.sig'
HASHES_NAME = 'files.sha256.json'


def _relative_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == SIGNATURE_NAME:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def hash_files(root: str | Path) -> Dict[str, str]:
    root = Path(root).resolve()
    hashes: Dict[str, str] = {}
    for path in _relative_files(root):
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256()
        with path.open('rb') as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                digest.update(chunk)
        hashes[rel] = digest.hexdigest()
    return dict(sorted(hashes.items(), key=lambda item: item[0]))


def canonical_hashes(hashes: Dict[str, str]) -> bytes:
    return json.dumps(hashes, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def verify_plugin_signature(plugin_root: str | Path, public_key_paths: Iterable[str | Path]) -> bool:
    """使用 Ed25519 公钥验证插件签名。"""
    root = Path(plugin_root).resolve()
    signature_path = root / SIGNATURE_NAME
    if not signature_path.is_file():
        return False
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    signature = signature_path.read_bytes()
    payload = canonical_hashes(hash_files(root))
    for key_path in public_key_paths:
        key_path = Path(key_path)
        if not key_path.is_file():
            continue
        public_key = serialization.load_pem_public_key(key_path.read_bytes())
        if not isinstance(public_key, Ed25519PublicKey):
            continue
        try:
            public_key.verify(signature, payload)
            return True
        except InvalidSignature:
            continue
    return False


@dataclass
class PluginPackage:
    root: Path
    manifest: PluginManifest
    hashes: Dict[str, str]
    signed: bool

    @classmethod
    def open(cls, path: str | Path, public_key_paths: Optional[Iterable[str | Path]] = None,
             allow_unsigned: bool = False) -> 'PluginPackage':
        root = Path(path).resolve()
        manifest = PluginManifest.load(root / MANIFEST_NAME)
        hashes = hash_files(root)
        signed = False
        if public_key_paths:
            signed = verify_plugin_signature(root, public_key_paths)
        if not signed and not allow_unsigned:
            raise PermissionError('插件未通过可信签名校验；开发测试必须显式 allow_unsigned')
        package = cls(root=root, manifest=manifest, hashes=hashes, signed=signed)
        package.verify_integrity()
        return package

    def verify_integrity(self) -> None:
        current = hash_files(self.root)
        if current != self.hashes:
            raise RuntimeError('插件文件完整性校验失败')
        for rel in list(self.manifest.native_libraries.values()) + [self.manifest.license_path]:
            if not rel:
                continue
            path = Path(rel)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError(f'非法插件路径: {rel}')
            if not (self.root / path).is_file():
                raise FileNotFoundError(f'插件声明文件不存在: {rel}')
        if self.manifest.model_path:
            rel = self.manifest.model_path
            path = Path(rel)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError(f'非法插件路径: {rel}')
            if not (self.root / path).is_dir():
                raise FileNotFoundError(f'插件模型目录不存在: {rel}')

    def resolve(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError(f'非法插件路径: {relative}')
        return (self.root / path).resolve()

    def describe(self) -> Dict[str, object]:
        data = self.manifest.to_dict()
        data.update({'signed': self.signed, 'file_count': len(self.hashes)})
        return data
