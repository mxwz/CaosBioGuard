"""标准生物模板包导入。

模板包目录示例：

    template.toml
    arrays/embedding.npy
    raw/sample.jpg   # 可选，强烈建议提供

template.toml 示例：

    subject = "张三"
    modality = "face"
    device_id = "WEB"
    backend = "sdk"
    quality = 0.91

    [arrays.embedding]
    file = "arrays/embedding.npy"
"""

from __future__ import annotations

import base64
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from ..capture_store import CaptureRepository
from ..store import BioTemplateStore
from ..types import BioTemplate

TEMPLATE_MANIFEST = 'template.toml'


@dataclass(frozen=True)
class TemplateImportResult:
    subject: str
    modality: str
    device_id: str
    backend: str
    quality: float
    digest: str
    raw_saved: bool
    template: BioTemplate

    def to_dict(self) -> Dict[str, Any]:
        return {
            'subject': self.subject,
            'modality': self.modality,
            'device_id': self.device_id,
            'backend': self.backend,
            'quality': self.quality,
            'digest': self.digest,
            'raw_saved': self.raw_saved,
        }


def _load_array(spec: Dict[str, Any], package_root: Path) -> np.ndarray:
    if spec.get('file'):
        path = Path(str(spec['file']))
        if path.is_absolute() or '..' in path.parts:
            raise ValueError(f'非法数组路径: {spec["file"]}')
        return np.load(package_root / path, allow_pickle=False)
    if spec.get('base64') is None:
        raise ValueError('数组必须提供 file 或 base64')
    raw = base64.b64decode(str(spec['base64']))
    dtype = str(spec.get('dtype', 'float32'))
    shape = tuple(int(x) for x in spec.get('shape', ()))
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def load_template_package(path: str | Path) -> tuple[BioTemplate, Dict[str, Any]]:
    root = Path(path).resolve()
    manifest_path = root / TEMPLATE_MANIFEST if root.is_dir() else root
    if manifest_path.suffix != '.toml':
        raise ValueError('标准模板包必须包含 template.toml')
    with manifest_path.open('rb') as fh:
        data = tomllib.load(fh)
    required = ['subject', 'modality', 'device_id', 'arrays']
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f'模板包缺少字段: {", ".join(missing)}')
    arrays = {
        str(name): _load_array(dict(spec), root if root.is_dir() else manifest_path.parent)
        for name, spec in dict(data['arrays']).items()
    }
    if not arrays:
        raise ValueError('模板 arrays 不能为空')
    template = BioTemplate(
        modality=str(data['modality']),
        version=int(data.get('version', 1)),
        arrays=arrays,
        quality=float(data.get('quality', 0.0)),
        meta=dict(data.get('meta', {})),
    )
    info = {
        'subject': str(data['subject']),
        'device_id': str(data['device_id']),
        'backend': str(data.get('backend', template.meta.get('backend', 'model'))),
        'raw_file': str(data.get('raw_file', '') or ''),
        'raw_mime': str(data.get('raw_mime', 'application/octet-stream')),
    }
    return template, info


def import_template_package(path: str | Path, template_store: BioTemplateStore,
                            capture_repo: Optional[CaptureRepository] = None) -> TemplateImportResult:
    template, info = load_template_package(path)
    backend = info['backend']
    template.meta.setdefault('backend', backend)
    subject = info['subject']
    device_id = info['device_id']
    template_store.save(subject, template, device_id=device_id, backend=backend)
    raw_saved = False
    root = Path(path).resolve()
    raw_rel = info.get('raw_file')
    if capture_repo is not None and raw_rel:
        raw_path = Path(raw_rel)
        if raw_path.is_absolute() or '..' in raw_path.parts:
            raise ValueError(f'非法原始样本路径: {raw_rel}')
        raw_full = root / raw_path if root.is_dir() else root.parent / raw_path
        if raw_full.is_file():
            capture_repo.save_capture(
                subject, template.modality, raw_full.read_bytes(), template,
                device_id=device_id, image_mime=info.get('raw_mime', 'application/octet-stream'),
                meta={'source': 'standard-template-import'},
            )
            raw_saved = True
    return TemplateImportResult(
        subject=subject, modality=template.modality, device_id=device_id,
        backend=backend, quality=template.quality, digest=template.digest(),
        raw_saved=raw_saved, template=template,
    )
