"""串口传输层：基于 pyserial 的帧级读写。

负责：
- 打开 / 关闭串口（默认 115200、8 数据位、1 停止位、无校验、无流控）
- 逐字节定位帧头并解析完整帧
- 帧头错乱时自动重同步
- 读超时抛 :class:`X2000Timeout`
"""

from __future__ import annotations

import time
from typing import Optional

from .constants import SYNC_WORD
from .errors import ChecksumError, FrameParseError, SerialConnectionError, X2000Timeout
from .frame import Frame, xor_bytes


class SerialTransport:
    """X2000 串口帧收发器。

    依赖 ``pyserial``，请确保已安装（``pip install pyserial``）。
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser = None

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def open(self):
        """打开串口。"""
        try:
            import serial  # 延迟导入，避免未安装时影响包导入
        except ImportError as e:
            raise SerialConnectionError('未安装 pyserial，请先执行 pip install pyserial') from e

        try:
            self._ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
        except Exception as e:
            raise SerialConnectionError('打开串口失败: %s (%s)' % (self.port, e)) from e

    def close(self):
        if self._ser is not None and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def flush_input(self):
        """清空接收缓冲区（丢弃积压的旧数据）。"""
        if self.is_open:
            self._ser.reset_input_buffer()

    # ------------------------------------------------------------------
    # 底层字节读写
    # ------------------------------------------------------------------
    def write(self, data: bytes):
        if not self.is_open:
            raise SerialConnectionError('串口未打开，请先调用 open()')
        self._ser.write(data)

    def _read_byte(self, deadline: Optional[float]):
        """读取 1 字节；超时返回 None。"""
        if not self.is_open:
            raise SerialConnectionError('串口未打开')
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._ser.timeout = remaining
        else:
            self._ser.timeout = self.timeout
        b = self._ser.read(1)
        return b[0] if b else None

    def _read_exact(self, deadline: Optional[float], length: int) -> bytes:
        """读取指定长度字节；超时抛出 X2000Timeout。"""
        buf = bytearray()
        while len(buf) < length:
            b = self._read_byte(deadline)
            if b is None:
                raise X2000Timeout(msgid=None, timeout=0, message='读取数据超时（已读 %d/%d 字节）' % (len(buf), length))
            buf.append(b)
        return bytes(buf)

    # ------------------------------------------------------------------
    # 帧级读写
    # ------------------------------------------------------------------
    def write_frame(self, msgid: int, data: bytes = b''):
        """组包并发送一帧。"""
        from .frame import build_frame
        self.write(build_frame(msgid, data))

    def read_frame(self, timeout: Optional[float] = None) -> Frame:
        """读取并解析一帧，自动重同步帧头。

        :param timeout: 整帧读取超时（秒），None 表示使用串口默认 timeout。
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        # 1) 定位帧头 0xEF 0xAA
        state = 0  # 0 = 等待 0xEF；1 = 等待 0xAA
        while True:
            b = self._read_byte(deadline)
            if b is None:
                raise X2000Timeout(msgid=None, timeout=timeout or self.timeout, message='等待帧头超时')
            if state == 0:
                if b == SYNC_WORD[0]:
                    state = 1
            else:
                if b == SYNC_WORD[1]:
                    break
                elif b == SYNC_WORD[0]:
                    state = 1  # 连续 0xEF，继续等待 0xAA
                else:
                    state = 0  # 噪声字节，重新找 0xEF

        # 2) 读取 MsgID + Size
        msgid = self._read_byte(deadline)
        if msgid is None:
            raise X2000Timeout(msgid=None, timeout=timeout or self.timeout, message='读取 MsgID 超时')
        size_hi = self._read_byte(deadline)
        size_lo = self._read_byte(deadline)
        if size_hi is None or size_lo is None:
            raise X2000Timeout(msgid=None, timeout=timeout or self.timeout, message='读取 Size 超时')
        size = (size_hi << 8) | size_lo

        # 3) 读取 Data + 校验码
        data = self._read_exact(deadline, size)
        checksum = self._read_byte(deadline)
        if checksum is None:
            raise X2000Timeout(msgid=None, timeout=timeout or self.timeout, message='读取校验码超时')

        # 4) 校验
        body = bytes([msgid, size_hi, size_lo]) + data
        actual = xor_bytes(body)
        if actual != checksum:
            raise ChecksumError('XOR 校验失败: 期望 0x%02X，实际 0x%02X (mid=0x%02X)' % (actual, checksum, msgid))

        return Frame(msgid=msgid, data=data, checksum=checksum)
