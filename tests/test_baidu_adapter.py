"""百度人脸 SDK 适配器的无授权单元测试。"""

from __future__ import annotations

import ctypes

import numpy as np
import pytest

from biometrics import BaiduFaceSDKAdapter, BioSample, BioTemplate


class FakeDll:
    def __init__(self):
        self.initialized = False

    def caos_bdface_create(self):
        return 123

    def caos_bdface_destroy(self, handle):
        return None

    def caos_bdface_init(self, handle, model_path):
        self.initialized = True
        return 0

    def caos_bdface_is_authorized(self, handle):
        return 1

    def caos_bdface_extract(self, handle, pixels, width, height, channels,
                            feature, capacity, size, box):
        ctypes.cast(size, ctypes.POINTER(ctypes.c_int))[0] = 128
        return 0

    def caos_bdface_compare(self, handle, left, left_size, right, right_size, score):
        ctypes.cast(score, ctypes.POINTER(ctypes.c_float))[0] = 0.72
        return 0

    def caos_bdface_rgb_liveness(self, handle, pixels, width, height, channels, score):
        ctypes.cast(score, ctypes.POINTER(ctypes.c_float))[0] = 0.91
        return 0


def _adapter():
    adapter = BaiduFaceSDKAdapter()
    adapter._load_library = lambda: FakeDll()
    return adapter


def test_baidu_adapter_check_available():
    adapter = _adapter()
    ok, reason = adapter.check_available()
    assert ok is True
    assert reason == ''


def test_baidu_adapter_extract():
    adapter = _adapter()
    sample = BioSample.image(np.zeros((32, 24, 3), dtype=np.uint8), quality=0.9)
    template = adapter.extract(sample)
    assert template.modality == 'face'
    assert template.arrays['embedding'].shape == (128,)
    assert template.arrays['bbox'].shape == (6,)
    assert template.meta['vendor'] == 'baidu'
    assert template.quality == 0.9


def test_baidu_adapter_compare_and_liveness():
    adapter = _adapter()
    left = BioTemplate('face', arrays={'embedding': np.ones(128, dtype=np.float32)})
    right = BioTemplate('face', arrays={'embedding': np.ones(128, dtype=np.float32)})
    assert adapter.compare(left, right) == pytest.approx(0.72, abs=1e-6)
    report = adapter.liveness(BioSample.image(np.zeros((32, 24, 3), dtype=np.uint8)))
    assert report.passed is True
    assert report.score == pytest.approx(0.91, abs=1e-6)
