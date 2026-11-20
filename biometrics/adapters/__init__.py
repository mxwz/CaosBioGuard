"""厂商 SDK 与模型混合后端。"""

from .aliyun import (AliyunAndroidAARAdapter, AliyunBaseAdapter, AliyunCloudAuthAdapter,
                     AliyunFacebodyAdapter, AliyunIMMAdapter, build_aliyun_adapter)
from .baidu_face import BaiduFaceSDKAdapter
from .base import VendorAdapter
from .generic import GenericSDKAdapter, normalize_template
from .hybrid import HybridEngine
from .registry import VendorAdapterRegistry

__all__ = [
    'AliyunAndroidAARAdapter',
    'AliyunBaseAdapter',
    'AliyunCloudAuthAdapter',
    'AliyunFacebodyAdapter',
    'AliyunIMMAdapter',
    'BaiduFaceSDKAdapter',
    'GenericSDKAdapter',
    'HybridEngine',
    'VendorAdapter',
    'VendorAdapterRegistry',
    'build_aliyun_adapter',
    'normalize_template',
]
