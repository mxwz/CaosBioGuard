"""通用厂商 SDK 适配器。

支持两种接入方式：
1. python：通过 importlib 加载厂商 Python SDK 的包装类；
2. command：通过外部可执行程序/包装脚本以 JSON 交互，不使用 shell。

真实 SDK 可能返回 BioTemplate、字节模板、base64 或向量，统一在这里转换为 BioTemplate。
"""

from __future__ import annotations

import base64
import importlib
import json
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..types import BioSample, BioTemplate, LivenessReport, QualityReport
from .base import VendorAdapter


def normalize_template(raw: Any, modality: str, quality: float,
                       meta: Optional[Dict[str, Any]] = None) -> BioTemplate:
    base_meta = dict(meta or {})
    base_meta.setdefault('backend', 'sdk')

    if isinstance(raw, BioTemplate):
        raw.meta.update(base_meta)
        if quality:
            raw.quality = float(quality)
        return raw

    arrays: Dict[str, np.ndarray] = {}
    if isinstance(raw, (bytes, bytearray)):
        arrays['vendor_template'] = np.frombuffer(bytes(raw), dtype=np.uint8)
    elif isinstance(raw, np.ndarray):
        arrays['embedding'] = np.asarray(raw, dtype=np.float32)
    elif isinstance(raw, str):
        arrays['vendor_template'] = np.frombuffer(base64.b64decode(raw), dtype=np.uint8)
    elif isinstance(raw, dict):
        if raw.get('template'):
            value = raw['template']
            if isinstance(value, str):
                value = base64.b64decode(value)
            arrays['vendor_template'] = np.frombuffer(bytes(value), dtype=np.uint8)
        if raw.get('embedding') is not None:
            arrays['embedding'] = np.asarray(raw['embedding'], dtype=np.float32)
        for key, value in (raw.get('arrays') or {}).items():
            arrays[str(key)] = np.asarray(value, dtype=np.float32)
        quality = float(raw.get('quality', quality) or quality)
    else:
        raise TypeError(f'不支持的厂商模板类型: {type(raw)}')

    if not arrays:
        raise ValueError('厂商模板为空')
    return BioTemplate(modality=modality, arrays=arrays, meta=base_meta, quality=float(quality))


def _call_first(target: Any, names: List[str], *args: Any) -> Any:
    for name in names:
        method = getattr(target, name, None)
        if callable(method):
            return method(*args)
    return None


class GenericSDKAdapter(VendorAdapter):
    def __init__(self, modality: str, vendor: str, config: Dict[str, Any]):
        super().__init__(modality, vendor, config)
        self.mode = str(config.get('mode', 'python')).lower()
        self._target = None

    def _load_target(self):
        if self._target is not None:
            return self._target
        if self.mode == 'command':
            self._target = False
            return self._target
        dotted = str(self.config.get('python_class', '')).strip()
        if not dotted:
            raise RuntimeError('python 模式需要配置 python_class')
        module_name, class_name = dotted.rsplit('.', 1)
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        try:
            self._target = cls(self.config)
        except TypeError:
            self._target = cls()
        return self._target

    def check_available(self) -> Tuple[bool, str]:
        try:
            if self.mode == 'command':
                command = str(self.config.get('command', '')).strip()
                if not command:
                    return False, 'command 模式需要配置 command'
                return True, ''
            target = self._load_target()
            checker = getattr(target, 'caos_available', None)
            if callable(checker):
                ok, reason = checker()
                return bool(ok), str(reason)
            return True, ''
        except Exception as exc:
            return False, str(exc)

    def quality(self, sample: BioSample) -> Optional[QualityReport]:
        try:
            if self.mode == 'python':
                target = self._load_target()
                raw = _call_first(target, ['caos_quality', 'quality'], sample)
                if raw is None:
                    return None
                if isinstance(raw, QualityReport):
                    return raw
                data = raw
            else:
                data = self._run_command('quality', sample)
            score = float(data.get('score', 0.0) if isinstance(data, dict) else data)
            return QualityReport(score=score, passed=bool(score >= 0.45),
                                 metrics={}, issues=list(data.get('issues', [])) if isinstance(data, dict) else [])
        except Exception:
            return None

    def extract(self, sample: BioSample) -> BioTemplate:
        if self.mode == 'python':
            target = self._load_target()
            raw = _call_first(target, ['caos_extract', 'extract_template', 'extract'], sample)
            if raw is None:
                raise RuntimeError('厂商 SDK 未返回模板')
            quality = sample.meta.get('quality', 0.0)
        else:
            data = self._run_command('extract', sample)
            raw = data.get('template') or data.get('embedding') or data.get('arrays')
            quality = float(data.get('quality', 0.0))
        meta = {
            'backend': 'sdk', 'vendor': self.vendor,
            'sdk_version': self.config.get('sdk_version', ''),
            'template_format': self.config.get('template_format', 'vendor'),
        }
        template = normalize_template(raw, self.modality, float(quality), meta)
        return template

    def compare(self, probe: BioTemplate, gallery: BioTemplate) -> Optional[float]:
        try:
            if self.mode == 'python':
                target = self._load_target()
                score = _call_first(target, ['caos_compare', 'compare', 'match'], probe, gallery)
            else:
                score = self._run_command('compare', None, probe, gallery).get('score')
            return None if score is None else float(score)
        except Exception:
            return None

    def liveness(self, sample: BioSample) -> Optional[LivenessReport]:
        try:
            if self.mode == 'python':
                target = self._load_target()
                raw = _call_first(target, ['caos_liveness', 'liveness'], sample)
            else:
                raw = self._run_command('liveness', sample)
            if raw is None:
                return None
            if isinstance(raw, LivenessReport):
                return raw
            return LivenessReport(
                passed=bool(raw.get('passed', False)), score=float(raw.get('score', 0.0)),
                mode=str(raw.get('mode', 'sdk')), reasons=list(raw.get('reasons', [])),
            )
        except Exception:
            return None

    def _command_parts(self) -> List[str]:
        command = str(self.config.get('command', ''))
        parts = shlex.split(command)
        extra = str(self.config.get('args', ''))
        if extra:
            parts += shlex.split(extra)
        if not parts:
            raise RuntimeError('厂商 command 为空')
        return parts

    def _run_command(self, action: str, sample: Optional[BioSample], *objects: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'action': action, 'config': dict(self.config)}
        if sample is not None:
            payload['sample_meta'] = dict(sample.meta)
            payload['source_path'] = sample.meta.get('source_path', '')
        if objects:
            payload['objects'] = [str(x.meta) for x in objects]
        proc = subprocess.run(
            self._command_parts(), input=json.dumps(payload, ensure_ascii=False),
            text=True, capture_output=True, timeout=float(self.config.get('timeout', 8)),
            shell=False, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f'厂商命令退出码 {proc.returncode}')
        return json.loads(proc.stdout)
