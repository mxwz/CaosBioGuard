"""厂商 SDK 与模型混合后端。"""

from .base import VendorAdapter
from .generic import GenericSDKAdapter, normalize_template
from .hybrid import HybridEngine
from .registry import VendorAdapterRegistry

__all__ = [
    'GenericSDKAdapter',
    'HybridEngine',
    'VendorAdapter',
    'VendorAdapterRegistry',
    'normalize_template',
]
