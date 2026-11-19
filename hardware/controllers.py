"""门禁硬件控制器：仿真器、串口继电器和 Wiegand 编码。

真实设备协议差异较大，因此串口控制器只负责按配置发送字节，不绑定特定厂商；
没有硬件时使用 SimulatedRelay 完成应用联调。
"""

from __future__ import annotations

import abc
import threading
from typing import Callable, List, Optional, Sequence, Tuple


class RelayController(abc.ABC):
    @property
    @abc.abstractmethod
    def state(self) -> bool:
        """True=继电器吸合/门锁打开，False=释放/门锁关闭。"""

    @abc.abstractmethod
    def open(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    def pulse(self, seconds: float) -> None:
        self.open()
        self._schedule_close(max(0.1, float(seconds)))

    @abc.abstractmethod
    def _schedule_close(self, seconds: float) -> None: ...


class SimulatedRelay(RelayController):
    def __init__(self, name: str = 'simulated-lock'):
        self.name = name
        self._state = False
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.RLock()

    @property
    def state(self) -> bool:
        return self._state

    def open(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._state = True

    def close(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._state = False

    def _schedule_close(self, seconds: float) -> None:
        with self._lock:
            timer = threading.Timer(seconds, self.close)
            timer.daemon = True
            self._timer = timer
            timer.start()


def parse_byte_command(value: str) -> bytes:
    """把 A0 01 02、A00102 或 0xA0,0x01 形式解析为字节。"""
    cleaned = value.replace('0x', ' ').replace(',', ' ').replace(';', ' ')
    parts = [p.strip() for p in cleaned.split() if p.strip()]
    if not parts:
        return b''
    if len(parts) == 1 and len(parts[0]) > 2:
        token = parts[0]
        parts = [token[i:i + 2] for i in range(0, len(token), 2)]
    return bytes(int(p, 16) for p in parts)


class SerialRelay(RelayController):
    def __init__(self, port: str, open_command: str, close_command: str,
                 baudrate: int = 9600, timeout: float = 1.0):
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.open_command = parse_byte_command(open_command)
        self.close_command = parse_byte_command(close_command)
        self._serial = None
        self._state = False
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.RLock()

    @property
    def state(self) -> bool:
        return self._state

    def _ensure_serial(self):
        if self._serial is None:
            import serial  # type: ignore
            self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        if not self._serial.is_open:
            self._serial.open()
        return self._serial

    def _send(self, command: bytes) -> None:
        if not command:
            raise ValueError('串口继电器命令为空')
        with self._lock:
            device = self._ensure_serial()
            device.write(command)
            if hasattr(device, 'reset_output_buffer'):
                device.reset_output_buffer()

    def open(self) -> None:
        self._send(self.open_command)
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._state = True

    def close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._send(self.close_command)
        self._state = False

    def _schedule_close(self, seconds: float) -> None:
        timer = threading.Timer(seconds, self.close)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def shutdown(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            if self._serial is not None:
                self._serial.close()


class WiegandEncoder:
    """26-bit Wiegand 编码器，输出可交给 GPIO 适配层。"""

    @staticmethod
    def encode_26bit(facility: int, card_number: int) -> List[Tuple[int, int]]:
        if not 0 <= facility <= 255:
            raise ValueError('Wiegand 26 位 facility code 范围为 0~255')
        if not 0 <= card_number <= 65535:
            raise ValueError('Wiegand 26 位 card number 范围为 0~65535')
        bits = [(facility >> i) & 1 for i in reversed(range(8))]
        bits += [(card_number >> i) & 1 for i in reversed(range(16))]
        even_parity = sum(bits[:12]) % 2
        odd_parity = (sum(bits[12:]) + 1) % 2
        bits = [even_parity] + bits + [odd_parity]
        # (bit, pulse_gap_us)：bit=1 走 D1，bit=0 走 D0
        return [(bit, 100) for bit in bits]
