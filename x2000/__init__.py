"""X2000 人脸 / 掌静脉识别模组串口驱动层。

本包实现《X2000 人脸识别模组通信协议 V1.0》的明文串口通信，提供：

- :mod:`x2000.constants` 协议常量与枚举
- :mod:`x2000.frame` 帧组包 / 拆包 / 校验
- :mod:`x2000.transport` 串口帧级收发
- :mod:`x2000.client` 高层业务 API

典型用法::

    from x2000 import X2000Client

    client = X2000Client('COM3')
    client.connect(wait_ready=True)
    print(client.get_version())
    result = client.verify(timeout=10)
    print(result.user_id, result.user_name)
    client.close()
"""

from .client import (
    X2000Client,
    Reply,
    FaceState,
    VerifyResult,
    EnrollResult,
    UserInfo,
    parse_face_state,
)
from .errors import (
    X2000Error,
    SerialConnectionError,
    FrameParseError,
    ChecksumError,
    X2000Timeout,
    X2000ResultError,
)
from . import constants

__version__ = '0.1.0'

__all__ = [
    'X2000Client',
    'Reply',
    'FaceState',
    'VerifyResult',
    'EnrollResult',
    'UserInfo',
    'parse_face_state',
    'X2000Error',
    'SerialConnectionError',
    'FrameParseError',
    'ChecksumError',
    'X2000Timeout',
    'X2000ResultError',
    'constants',
    '__version__',
]
