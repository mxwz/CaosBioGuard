"""X2000 高层客户端：面向业务的 API。

封装了录入（人脸交互式 / 单帧 / 掌静脉）、鉴权解锁、删除用户、查询用户、
获取版本、抓拍图片等常用操作，并统一处理 NOTE / IMAGE 中间消息的采集与回调。

明文模式使用说明：本层不涉及加密握手，直接与模组以明文通信；加密（AES）
将在后续阶段作为独立能力加入（见开发需求文档）。
"""

from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from . import constants as C
from .errors import X2000ResultError, X2000Timeout
from .frame import read_int16_le, read_uint16_be, read_uint32_be, truncate_pad
from .transport import SerialTransport

logger = logging.getLogger(__name__)

USER_NAME_SIZE = 32
DEFAULT_IMAGE_CHUNK = 4000   # 协议单次上传图片最大 4K 字节

# NOTE 回调签名：on_note(nid: int, payload: bytes) -> None
NoteCallback = Callable[[int, bytes], None]
ImageCallback = Callable[[bytes], None]


@dataclass
class Reply:
    """一次命令的完整应答聚合结果。"""
    mid: int
    result: int
    data: bytes = b''
    notes: List[Tuple[int, bytes]] = field(default_factory=list)
    images: List[bytes] = field(default_factory=list)


@dataclass
class FaceState:
    """人脸 / 手掌状态信息（NID_FACE_STATE 携带的 s_note_data_face）。"""
    state: int = 0
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    yaw: int = 0
    pitch: int = 0
    roll: int = 0

    @property
    def state_name(self) -> str:
        return C.face_state_name(self.state)


@dataclass
class VerifyResult:
    """鉴权解锁结果。"""
    result: int
    user_id: int = 0
    user_name: str = ''
    admin: int = 0
    unlock_status: int = 0
    reply: Optional[Reply] = None

    @property
    def success(self) -> bool:
        return self.result == C.MR_SUCCESS


@dataclass
class EnrollResult:
    """录入结果。"""
    result: int
    user_id: int = 0
    face_direction: int = 0
    reply: Optional[Reply] = None

    @property
    def success(self) -> bool:
        return self.result == C.MR_SUCCESS


@dataclass
class UserInfo:
    """用户信息。"""
    user_id: int
    user_name: str = ''
    admin: int = 0


def parse_face_state(payload: bytes) -> Optional[FaceState]:
    """解析 s_note_data_face（8 个 int16 小端字段）。"""
    if len(payload) < 16:
        return None
    return FaceState(
        state=read_int16_le(payload, 0),
        left=read_int16_le(payload, 2),
        top=read_int16_le(payload, 4),
        right=read_int16_le(payload, 6),
        bottom=read_int16_le(payload, 8),
        yaw=read_int16_le(payload, 10),
        pitch=read_int16_le(payload, 12),
        roll=read_int16_le(payload, 14),
    )


class X2000Client:
    """X2000 模组客户端。

    用法::

        client = X2000Client('COM3')
        client.connect(wait_ready=True)
        print(client.get_version())
        result = client.verify(timeout=10)
        client.close()
    """

    def __init__(self, port: str, baudrate: int = 115200,
                 name_encoding: str = 'utf-8', serial_timeout: float = 1.0):
        self.transport = SerialTransport(port, baudrate, timeout=serial_timeout)
        self.name_encoding = name_encoding

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def connect(self, wait_ready: bool = False, ready_timeout: float = 3.0) -> bool:
        """打开串口并清空接收缓冲；可选等待 NID_READY。"""
        self.transport.open()
        self.transport.flush_input()
        if wait_ready:
            return self.wait_ready(ready_timeout)
        return True

    def close(self):
        self.transport.close()

    def wait_ready(self, timeout: float = 3.0) -> bool:
        """阻塞等待模块上电 NID_READY 通知，超时返回 False。"""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                frame = self.transport.read_frame(timeout=remaining)
            except X2000Timeout:
                return False
            if frame.msgid == C.MID_NOTE and frame.data and frame.data[0] == C.NID_READY:
                return True

    def ping(self, timeout: float = 1.0) -> int:
        """连通性探测，返回模块工作状态码。"""
        return self.get_status(timeout)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------
    def request(self, msgid: int, data: bytes = b'', timeout: float = 2.0,
                on_note: Optional[NoteCallback] = None,
                on_image: Optional[ImageCallback] = None) -> Reply:
        """发送一条命令并等待其最终 REPLY，期间收集 NOTE / IMAGE 中间消息。

        :param msgid: 命令码（MID_*）
        :param data: 命令数据段
        :param timeout: 整体等待超时（秒）
        :param on_note: NOTE 消息回调
        :param on_image: IMAGE 消息回调
        """
        self.transport.write_frame(msgid, data)
        deadline = time.monotonic() + timeout
        reply = Reply(mid=msgid, result=C.MR_FAILED4_UNKNOWNREASON)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise X2000Timeout(msgid, timeout)
            try:
                frame = self.transport.read_frame(timeout=remaining)
            except X2000Timeout:
                raise X2000Timeout(msgid, timeout)

            if frame.msgid == C.MID_NOTE:
                nid = frame.data[0] if frame.data else None
                payload = frame.data[1:] if len(frame.data) > 1 else b''
                reply.notes.append((nid, payload))
                if on_note:
                    on_note(nid, payload)
            elif frame.msgid == C.MID_IMAGE:
                reply.images.append(frame.data)
                if on_image:
                    on_image(frame.data)
            elif frame.msgid == C.MID_REPLY:
                if len(frame.data) < 2:
                    continue
                reply_mid = frame.data[0]
                if reply_mid == msgid:
                    reply.result = frame.data[1]
                    reply.data = frame.data[2:]
                    return reply
                # 其它命令迟到的 REPLY，忽略，继续等待目标应答
        # 不可达，仅为类型提示

    # ------------------------------------------------------------------
    # 基础命令
    # ------------------------------------------------------------------
    def reset(self, timeout: float = 1.0) -> Reply:
        """复位到 standby。"""
        return self.request(C.MID_RESET, timeout=timeout)

    def get_status(self, timeout: float = 1.0) -> int:
        """获取模块工作状态，返回 MS_* 常量。"""
        reply = self.request(C.MID_GETSTATUS, timeout=timeout)
        self._raise_if_error(C.MID_GETSTATUS, reply)
        return reply.data[0] if reply.data else C.MS_INVALID

    def get_version(self, timeout: float = 1.0) -> str:
        """获取软件版本信息。"""
        reply = self.request(C.MID_GET_VERSION, timeout=timeout)
        self._raise_if_error(C.MID_GET_VERSION, reply)
        return self._decode_fixed_string(reply.data)

    def get_library_version(self, timeout: float = 1.0) -> str:
        """获取算法库版本信息。"""
        reply = self.request(C.MID_GETLIBRARY_VERSION, timeout=timeout)
        self._raise_if_error(C.MID_GETLIBRARY_VERSION, reply)
        return self._decode_fixed_string(reply.data)

    def face_reset(self, timeout: float = 1.0) -> Reply:
        """重置算法状态，清空交互式录入进度。"""
        return self.request(C.MID_FACERESET, timeout=timeout)

    # ------------------------------------------------------------------
    # 录入
    # ------------------------------------------------------------------
    def enroll_face(self, user_name: str, admin: int = 0,
                    face_direction: int = C.FACE_DIRECTION_MIDDLE,
                    timeout: float = 30.0,
                    on_note: Optional[NoteCallback] = None) -> EnrollResult:
        """交互式录入单个方向的人脸（MID_ENROLL）。

        完整录入通常需要按 up/down/left/right/middle 依次调用。
        """
        data = bytes([admin & 0xFF]) + self._encode_name(user_name) \
            + bytes([face_direction & 0xFF, int(timeout) & 0xFF])
        reply = self.request(C.MID_ENROLL, data=data, timeout=timeout + 2, on_note=on_note)
        return self._parse_enroll_reply(reply)

    def enroll_face_single(self, user_name: str, admin: int = 0,
                           timeout: float = 30.0,
                           on_note: Optional[NoteCallback] = None) -> EnrollResult:
        """单帧录入正脸（MID_ENROLL_SINGLE），仅需一张正脸。"""
        data = bytes([admin & 0xFF]) + self._encode_name(user_name) \
            + bytes([C.FACE_DIRECTION_MIDDLE & 0xFF, int(timeout) & 0xFF])
        reply = self.request(C.MID_ENROLL_SINGLE, data=data, timeout=timeout + 2, on_note=on_note)
        return self._parse_enroll_reply(reply)

    def enroll_palm(self, user_name: str, admin: int = 0,
                    timeout: float = 30.0,
                    on_note: Optional[NoteCallback] = None) -> EnrollResult:
        """录入掌静脉（MID_ENROLL_SINGLE + FACE_DIRECTION_HAND）。"""
        data = bytes([admin & 0xFF]) + self._encode_name(user_name) \
            + bytes([C.FACE_DIRECTION_HAND & 0xFF, int(timeout) & 0xFF])
        reply = self.request(C.MID_ENROLL_SINGLE, data=data, timeout=timeout + 2, on_note=on_note)
        return self._parse_enroll_reply(reply)

    # ------------------------------------------------------------------
    # 鉴权解锁
    # ------------------------------------------------------------------
    def verify(self, timeout: float = 10.0,
               verify_mode: int = C.VERIFY_MODE_STANDARD,
               pd_rightaway: int = 0,
               on_note: Optional[NoteCallback] = None) -> VerifyResult:
        """鉴权解锁，识别成功返回用户 ID / 姓名 / 管理员 / 解锁状态。

        :param timeout: 解锁超时（秒），最大 255
        :param verify_mode: 识别模式（标准 / 掌静脉 / 人脸+掌静脉等）
        """
        data = struct.pack('>BBB', pd_rightaway & 0xFF, int(timeout) & 0xFF, verify_mode & 0xFF)
        reply = self.request(C.MID_VERIFY, data=data, timeout=timeout + 2, on_note=on_note)
        result = VerifyResult(result=reply.result, reply=reply)
        if reply.result == C.MR_SUCCESS and len(reply.data) >= 36:
            result.user_id = read_uint16_be(reply.data, 0)
            result.user_name = self._decode_name(reply.data[2:34])
            result.admin = reply.data[34]
            result.unlock_status = reply.data[35]
        return result

    # ------------------------------------------------------------------
    # 用户管理
    # ------------------------------------------------------------------
    def delete_user(self, user_id: int, user_type: int = C.USER_TYPE_FACE,
                    timeout: float = 2.0) -> Reply:
        """删除指定用户。"""
        data = struct.pack('>H', user_id) + bytes([user_type & 0xFF])
        reply = self.request(C.MID_DELUSER, data=data, timeout=timeout)
        self._raise_if_error(C.MID_DELUSER, reply)
        return reply

    def delete_all(self, delete_type: int = C.DELALL_TYPE_ALL,
                   begin_user_id: int = 0, end_user_id: int = 0,
                   timeout: float = 2.0) -> Reply:
        """批量删除用户。"""
        data = bytes([delete_type & 0xFF])
        if delete_type == C.DELALL_TYPE_RANGE:
            data += struct.pack('>H', begin_user_id) + struct.pack('>H', end_user_id)
        reply = self.request(C.MID_DELALL, data=data, timeout=timeout)
        self._raise_if_error(C.MID_DELALL, reply)
        return reply

    def get_user_info(self, user_id: int, timeout: float = 2.0) -> UserInfo:
        """获取指定用户信息。"""
        data = struct.pack('>H', user_id)
        reply = self.request(C.MID_GETUSERINFO, data=data, timeout=timeout)
        self._raise_if_error(C.MID_GETUSERINFO, reply)
        if len(reply.data) < 35:
            return UserInfo(user_id=user_id)
        return UserInfo(
            user_id=read_uint16_be(reply.data, 0),
            user_name=self._decode_name(reply.data[2:34]),
            admin=reply.data[34],
        )

    def get_all_user_ids(self, fmt: int = 0, timeout: float = 2.0) -> List[int]:
        """获取所有已注册用户 ID 列表。

        :param fmt: 0 = 长格式（每 ID 2 字节）；1/2 = 位图短格式（人脸/掌静脉）
        """
        data = bytes([fmt & 0xFF])
        reply = self.request(C.MID_GET_ALL_USERID, data=data, timeout=timeout)
        self._raise_if_error(C.MID_GET_ALL_USERID, reply)
        if not reply.data:
            return []
        counts = reply.data[0]
        if fmt == 0:
            ids = []
            for i in range(counts):
                off = 1 + i * 2
                if off + 2 > len(reply.data):
                    break
                ids.append(read_uint16_be(reply.data, off))
            return ids
        # 位图格式：一个位表示一个用户，用户 ID 从 1 开始编号
        bitmap = reply.data[1:]
        ids = []
        for bit_index in range(len(bitmap) * 8):
            if bitmap[bit_index // 8] & (1 << (bit_index % 8)):
                ids.append(bit_index + 1)
        return ids[:counts] if counts else ids

    # ------------------------------------------------------------------
    # 图片抓拍 / 上传
    # ------------------------------------------------------------------
    def snapshot(self, image_counts: int = 1, start_number: int = 1,
                 timeout: float = 2.0) -> Reply:
        """抓拍图片并存储到模组本地。"""
        data = bytes([image_counts & 0xFF, start_number & 0xFF])
        reply = self.request(C.MID_SNAPIMAGE, data=data, timeout=timeout)
        self._raise_if_error(C.MID_SNAPIMAGE, reply)
        return reply

    def get_saved_image_size(self, image_number: int = 0, width: int = 0, height: int = 0,
                             timeout: float = 2.0) -> int:
        """获取待上传图片大小（字节）。"""
        data = bytes([image_number & 0xFF])
        if image_number == 0:
            # 现场图：可指定宽高，LSB 格式
            data += struct.pack('<H', width) + struct.pack('<H', height)
        reply = self.request(C.MID_GETSAVEDIMAGE, data=data, timeout=timeout)
        self._raise_if_error(C.MID_GETSAVEDIMAGE, reply)
        return read_uint32_be(reply.data, 0) if len(reply.data) >= 4 else 0

    def upload_image_chunk(self, offset: int, size: int, timeout: float = 10.0) -> bytes:
        """上传图片的一段（最大 4K），返回该段图片字节。"""
        data = struct.pack('>I', offset) + struct.pack('>I', size)
        reply = self.request(C.MID_UPLOADIMAGE, data=data, timeout=timeout)
        self._raise_if_error(C.MID_UPLOADIMAGE, reply)
        return b''.join(reply.images)

    def capture_image(self, image_number: int = 0, width: int = 0, height: int = 0,
                      chunk_size: int = DEFAULT_IMAGE_CHUNK,
                      timeout: float = 10.0) -> bytes:
        """抓取并下载一张完整图片，返回图片字节流。"""
        size = self.get_saved_image_size(image_number, width, height, timeout=timeout)
        if size <= 0:
            return b''
        buf = bytearray()
        offset = 0
        while offset < size:
            n = min(chunk_size, size - offset)
            buf.extend(self.upload_image_chunk(offset, n, timeout=timeout))
            offset += n
        return bytes(buf)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _raise_if_error(msgid: int, reply: Reply):
        if reply.result != C.MR_SUCCESS:
            raise X2000ResultError(msgid, reply.result)

    def _parse_enroll_reply(self, reply: Reply) -> EnrollResult:
        result = EnrollResult(result=reply.result, reply=reply)
        if len(reply.data) >= 2:
            result.user_id = read_uint16_be(reply.data, 0)
        if len(reply.data) >= 3:
            result.face_direction = reply.data[2]
        return result

    def _encode_name(self, name: str) -> bytes:
        data = name.encode(self.name_encoding, errors='ignore')
        return truncate_pad(data, USER_NAME_SIZE)

    def _decode_name(self, raw: bytes) -> str:
        text = raw.split(b'\x00')[0].strip()
        if not text:
            return ''
        for enc in (self.name_encoding, 'utf-8', 'gbk'):
            try:
                return text.decode(enc).strip()
            except (UnicodeDecodeError, LookupError):
                continue
        return text.decode('utf-8', errors='replace').strip()

    @staticmethod
    def _decode_fixed_string(raw: bytes) -> str:
        text = raw.split(b'\x00')[0].strip()
        for enc in ('utf-8', 'gbk', 'ascii'):
            try:
                return text.decode(enc).strip()
            except (UnicodeDecodeError, LookupError):
                continue
        return text.decode('utf-8', errors='replace').strip()
