"""百度人脸离线 SDK Python 适配器。

通过 C ABI 包装 DLL 调用 BaiduFaceApi，不直接调用 C++ 类成员函数。
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..types import BioSample, BioTemplate, LivenessReport
from .base import VendorAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WRAPPER = PROJECT_ROOT / 'vendor_wrappers' / 'build' / 'baidu_face' / 'Release' / 'caos_bdface.dll'
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / 'baidu_face_SDK' / 'extracted' / 'Windows_Cpp_8.4' / 'FaceOfflineSdk' / 'x64'
DEFAULT_MODEL_PATH = PROJECT_ROOT / 'baidu_face_SDK' / 'extracted' / 'Windows_Cpp_8.4' / 'FaceOfflineSdk' / 'models'


class BaiduFaceSDKAdapter(VendorAdapter):
    modality = 'face'
    vendor = 'baidu'

    def __init__(self, modality: str = 'face', vendor: str = 'baidu',
                 config: Optional[Dict[str, Any]] = None):
        super().__init__(modality, vendor, config)
        plugin_root = Path(self.config.get('plugin_root') or PROJECT_ROOT)
        if not plugin_root.is_absolute():
            plugin_root = PROJECT_ROOT / plugin_root

        def resolve_path(value: Any, default: Path) -> Path:
            path = Path(value or default)
            if not path.is_absolute():
                path = plugin_root / path
            return path

        self.wrapper_path = resolve_path(self.config.get('wrapper_library'), DEFAULT_WRAPPER)
        self.runtime_dir = resolve_path(self.config.get('runtime_dir'), DEFAULT_RUNTIME_DIR)
        self.model_path = str(resolve_path(self.config.get('model_path'), DEFAULT_MODEL_PATH))
        self._dll: Optional[ctypes.CDLL] = None
        self._handle: Optional[ctypes.c_void_p] = None
        self._dll_directory = None

    def _load_library(self) -> ctypes.CDLL:
        if self._dll is not None:
            return self._dll
        if not self.wrapper_path.is_file():
            raise FileNotFoundError(
                f'C ABI 包装库不存在: {self.wrapper_path}；百度离线 SDK 适配器当前仅提供 Windows 构建，'
                'Linux 环境请使用内置 InsightFace 人脸引擎。'
            )
        if self.runtime_dir.is_dir() and hasattr(os, 'add_dll_directory'):
            self._dll_directory = os.add_dll_directory(str(self.runtime_dir))
        elif self.runtime_dir.is_dir():
            os.environ['PATH'] = str(self.runtime_dir) + os.pathsep + os.environ.get('PATH', '')
        dll = ctypes.CDLL(str(self.wrapper_path))
        self._declare(dll)
        self._dll = dll
        return dll

    @staticmethod
    def _declare(dll: ctypes.CDLL) -> None:
        dll.caos_bdface_create.restype = ctypes.c_void_p
        dll.caos_bdface_create.argtypes = []
        dll.caos_bdface_destroy.restype = None
        dll.caos_bdface_destroy.argtypes = [ctypes.c_void_p]
        dll.caos_bdface_init.restype = ctypes.c_int
        dll.caos_bdface_init.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        dll.caos_bdface_is_authorized.restype = ctypes.c_int
        dll.caos_bdface_is_authorized.argtypes = [ctypes.c_void_p]
        dll.caos_bdface_extract.restype = ctypes.c_int
        dll.caos_bdface_extract.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_float),
        ]
        dll.caos_bdface_compare.restype = ctypes.c_int
        dll.caos_bdface_compare.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
            ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.POINTER(ctypes.c_float),
        ]
        dll.caos_bdface_rgb_liveness.restype = ctypes.c_int
        dll.caos_bdface_rgb_liveness.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_float),
        ]

    def _ensure_handle(self) -> ctypes.c_void_p:
        dll = self._load_library()
        if self._handle is not None:
            return self._handle
        raw_handle = dll.caos_bdface_create()
        if not raw_handle:
            raise RuntimeError('百度 SDK 实例创建失败')
        self._handle = ctypes.c_void_p(raw_handle)
        model = self.model_path.encode('utf-8') if self.model_path else None
        rc = dll.caos_bdface_init(self._handle, model)
        if rc != 0:
            raise RuntimeError(f'百度 SDK 初始化失败: {rc}')
        if not dll.caos_bdface_is_authorized(self._handle):
            raise RuntimeError('百度 SDK 未授权或授权已失效')
        return self._handle

    def check_available(self) -> Tuple[bool, str]:
        try:
            self._ensure_handle()
            return True, ''
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _image_parts(sample: BioSample) -> Tuple[np.ndarray, int, int, int]:
        if sample.kind != 'image':
            raise TypeError('百度人脸 SDK 需要 image 类型样本')
        image = np.ascontiguousarray(sample.data, dtype=np.uint8)
        if image.ndim == 2:
            height, width = image.shape
            channels = 1
        elif image.ndim == 3:
            height, width, channels = image.shape
        else:
            raise ValueError('不支持的图像维度')
        return image, int(width), int(height), int(channels)

    def extract(self, sample: BioSample) -> BioTemplate:
        handle = self._ensure_handle()
        dll = self._load_library()
        image, width, height, channels = self._image_parts(sample)
        feature = np.zeros(128, dtype=np.float32)
        box = np.zeros(6, dtype=np.float32)
        size = ctypes.c_int(0)
        rc = dll.caos_bdface_extract(
            handle,
            image.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            width, height, channels,
            feature.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            len(feature), ctypes.byref(size),
            box.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        )
        if rc != 0 or size.value <= 0:
            raise RuntimeError(f'百度 SDK 特征提取失败: rc={rc}')
        actual = feature[:size.value].copy()
        return BioTemplate(
            modality='face',
            arrays={'embedding': actual, 'bbox': box},
            quality=float(sample.meta.get('quality', 0.8)),
            meta={
                'backend': 'sdk', 'vendor': 'baidu',
                'sdk_version': self.config.get('sdk_version', '8.4'),
                'template_format': 'baidu-feature',
            },
        )

    def compare(self, probe: BioTemplate, gallery: BioTemplate) -> Optional[float]:
        handle = self._ensure_handle()
        dll = self._load_library()
        left = np.ascontiguousarray(probe.arrays.get('embedding'), dtype=np.float32)
        right = np.ascontiguousarray(gallery.arrays.get('embedding'), dtype=np.float32)
        score = ctypes.c_float(0.0)
        rc = dll.caos_bdface_compare(
            handle,
            left.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(left),
            right.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(right),
            ctypes.byref(score),
        )
        if rc != 0:
            return None
        return float(score.value)

    def liveness(self, sample: BioSample) -> Optional[LivenessReport]:
        handle = self._ensure_handle()
        dll = self._load_library()
        image, width, height, channels = self._image_parts(sample)
        score = ctypes.c_float(0.0)
        rc = dll.caos_bdface_rgb_liveness(
            handle,
            image.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            width, height, channels, ctypes.byref(score),
        )
        if rc != 0:
            return None
        value = float(score.value)
        return LivenessReport(passed=bool(value >= 0.5), score=value,
                              mode='sdk', reasons=['baidu-rgb-liveness'])

    def close(self) -> None:
        try:
            if self._dll is not None and self._handle is not None:
                self._dll.caos_bdface_destroy(self._handle)
        finally:
            self._handle = None
            if self._dll_directory is not None:
                self._dll_directory.close()
                self._dll_directory = None
