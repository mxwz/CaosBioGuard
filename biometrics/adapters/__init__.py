"""厂商 SDK 与模型混合后端。"""

from .baidu_face import BaiduFaceSDKAdapter
from .base import VendorAdapter
from .generic import GenericSDKAdapter, normalize_template
from .hybrid import HybridEngine
from .registry import VendorAdapterRegistry

__all__ = [
    'BaiduFaceSDKAdapter',
    'GenericSDKAdapter',
    'HybridEngine',
    'VendorAdapter',
    'VendorAdapterRegistry',
    'normalize_template',
]
