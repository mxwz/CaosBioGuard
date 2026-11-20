"""帧的组包 / 拆包与 XOR 校验。

协议帧结构（明文）：:

    SyncWord(2) | MsgID(1) | Size(2, 大端) | Data(N) | ParityCheck(1)

校验码 ``ParityCheck`` 为除 SyncWord 外所有字节（MsgID + Size + Data）逐字节 XOR 的结果。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

from .constants import SYNC_WORD
from .errors import ChecksumError, FrameParseError


def xor_bytes(data) -> int:
    """对字节串逐字节做 XOR，返回校验值。"""
    result = 0
    for b in data:
        result ^= b
    return result


@dataclass
class Frame:
    """一帧已解析的消息（不含 SyncWord 与校验码）。"""

    msgid: int
    data: bytes = b''
    checksum: int = 0

    def to_bytes(self) -> bytes:
        """组包为完整帧字节流。"""
        return build_frame(self.msgid, self.data)


def build_frame(msgid: int, data: bytes = b'') -> bytes:
    """由消息 ID 与数据组包为完整帧字节流。"""
    size = len(data)
    if size > 0xFFFF:
        raise FrameParseError('Data 长度超过协议上限 65535 字节: %d' % size)
    body = bytes([msgid & 0xFF]) + struct.pack('>H', size) + bytes(data)
    checksum = xor_bytes(body)
    return SYNC_WORD + body + bytes([checksum])


def parse_frame(buffer: bytes) -> Frame:
    """从完整字节流解析一帧并校验，失败抛出异常。

    ``buffer`` 应为从 SyncWord 开始的完整帧（含校验字节）。
    """
    if len(buffer) < 5:
        raise FrameParseError('帧长度不足 5 字节，无法解析')
    if buffer[0] != SYNC_WORD[0] or buffer[1] != SYNC_WORD[1]:
        raise FrameParseError('帧头错误: 期望 EF AA，实际 %02X %02X' % (buffer[0], buffer[1]))

    msgid = buffer[2]
    size = (buffer[3] << 8) | buffer[4]
    expected_len = 5 + size + 1  # sync(2) + msgid(1) + size(2) + data + checksum(1)
    if len(buffer) < expected_len:
        raise FrameParseError('帧不完整: 期望 %d 字节，实际 %d 字节' % (expected_len, len(buffer)))

    data = bytes(buffer[5:5 + size])
    checksum = buffer[5 + size]
    body = bytes([msgid]) + buffer[3:5] + data
    if xor_bytes(body) != checksum:
        raise ChecksumError('XOR 校验失败: 期望 0x%02X，实际 0x%02X' % (xor_bytes(body), checksum))

    return Frame(msgid=msgid, data=data, checksum=checksum)


def read_uint16_be(data: bytes, offset: int = 0) -> int:
    """读取大端 2 字节无符号整数。"""
    if offset + 2 > len(data):
        raise FrameParseError('数据长度不足，无法读取 uint16')
    return (data[offset] << 8) | data[offset + 1]


def read_uint32_be(data: bytes, offset: int = 0) -> int:
    """读取大端 4 字节无符号整数。"""
    if offset + 4 > len(data):
        raise FrameParseError('数据长度不足，无法读取 uint32')
    return int.from_bytes(data[offset:offset + 4], 'big')


def read_int16_be(data: bytes, offset: int = 0) -> int:
    """读取大端 2 字节有符号整数。"""
    if offset + 2 > len(data):
        raise FrameParseError('数据长度不足，无法读取 int16')
    return struct.unpack('>h', data[offset:offset + 2])[0]


def read_int16_le(data: bytes, offset: int = 0) -> int:
    """读取小端 2 字节有符号整数。"""
    if offset + 2 > len(data):
        raise FrameParseError('数据长度不足，无法读取 int16')
    return struct.unpack('<h', data[offset:offset + 2])[0]


def truncate_pad(data: bytes, length: int) -> bytes:
    """将字节串截断或右侧补零到指定长度。"""
    if len(data) >= length:
        return data[:length]
    return data + b'\x00' * (length - len(data))
