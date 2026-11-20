"""安全解压插件与模板压缩包。"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
from typing import Tuple


def safe_extract_zip(zip_bytes: bytes, manifest_name: str) -> Tuple[Path, Path]:
    """解压 ZIP 并返回临时目录和包含指定 manifest 的根目录。"""
    tmp = Path(tempfile.mkdtemp(prefix='caos_plugin_upload_'))
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            target_root = tmp.resolve()
            for info in zf.infolist():
                name = info.filename
                path = Path(name)
                if path.is_absolute() or '..' in path.parts or name.startswith(('/')):
                    raise ValueError(f'压缩包包含非法路径: {name}')
                target = (target_root / path).resolve()
                if not str(target).startswith(str(target_root)):
                    raise ValueError(f'压缩包路径越界: {name}')
            zf.extractall(target_root)
        matches = list(target_root.rglob(manifest_name))
        if not matches:
            raise ValueError(f'压缩包缺少 {manifest_name}')
        if len(matches) > 1:
            raise ValueError(f'压缩包内存在多个 {manifest_name}')
        return tmp, matches[0].parent
    except Exception:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        raise
