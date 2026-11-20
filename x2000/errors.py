"""X2000 驱动层异常定义。"""

from __future__ import annotations


class X2000Error(Exception):
    """X2000 驱动层所有异常的基类。"""


class SerialConnectionError(X2000Error):
    """串口打开 / 读写失败。"""


class FrameParseError(X2000Error):
    """帧解析失败（帧头错乱、长度异常等）。"""


class ChecksumError(X2000Error):
    """帧 XOR 校验失败，说明数据链路存在干扰或帧错位。"""


class X2000Timeout(X2000Error):
    """等待模块应答超时。"""

    def __init__(self, msgid, timeout, message=None):
        self.msgid = msgid
        self.timeout = timeout
        super().__init__(message or '等待模块应答超时 (mid=0x%02X, timeout=%.1fs)' % (msgid, timeout))


class X2000ResultError(X2000Error):
    """模块返回非成功结果码（MR_* != MR_SUCCESS）。"""

    def __init__(self, msgid, result, message=None):
        self.msgid = msgid
        self.result = result
        if message is None:
            from .constants import result_name
            message = '模块执行失败 (mid=0x%02X, result=%s)' % (msgid, result_name(result))
        super().__init__(message)
