"""硬件设备管理器：门锁、门磁、出门按钮、报警器和外部读卡器。"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from platform_utils import default_serial_port

from .controllers import RelayController, SerialRelay, SimulatedRelay
from .types import DeviceStatus, HardwareEvent


class HardwareManager:
    def __init__(self, relay: RelayController, config: Optional[Dict[str, Any]] = None,
                 event_callback: Optional[Callable[[HardwareEvent], None]] = None):
        self.relay = relay
        self.config = dict(config or {})
        self.event_callback = event_callback
        self._lock = threading.RLock()
        self._alarm_active = False
        self._alarm_timer: Optional[threading.Timer] = None
        self._door_open = False
        self._unlock_duration = float(self.config.get('unlock_duration', 3.0))
        self._alarm_duration = float(self.config.get('alarm_duration', 30.0))

    # ------------------------------------------------------------------
    @classmethod
    def from_config(cls, config_manager: Any,
                    event_callback: Optional[Callable[[HardwareEvent], None]] = None) -> 'HardwareManager':
        section = dict(config_manager.get_section('Hardware') or {})

        def get(key, default=''):
            return str(section.get(key, default) or default).strip()

        enabled = get('enabled', 'true').lower() in {'1', 'true', 'yes', 'on'}
        mode = get('mode', 'simulator').lower()
        if not enabled:
            mode = 'simulator'
        if mode == 'serial':
            relay: RelayController = SerialRelay(
                port=get('serial_port', default_serial_port()),
                baudrate=int(get('baudrate', '9600') or 9600),
                open_command=get('open_command', 'A0 01 01 A2'),
                close_command=get('close_command', 'A0 01 00 A1'),
                timeout=float(get('timeout', '1') or 1),
            )
        else:
            relay = SimulatedRelay(get('lock_name', 'door-lock'))
        manager = cls(relay, section, event_callback)
        if isinstance(relay, SerialRelay):
            relay.on_relock_failure = lambda _relay: manager.trigger_alarm()
        return manager

    # ------------------------------------------------------------------
    def _emit(self, device: str, event: str, value: Any = None) -> None:
        if self.event_callback:
            self.event_callback(HardwareEvent(device, event, value))

    def unlock(self, duration: Optional[float] = None) -> bool:
        seconds = float(duration or self._unlock_duration)
        with self._lock:
            self.relay.pulse(seconds)
            self._door_open = True
        self._emit('door-lock', 'unlock', seconds)
        return True

    def lock(self) -> bool:
        with self._lock:
            self.relay.close()
            self._door_open = False
        self._emit('door-lock', 'lock')
        return True

    def press_exit_button(self) -> bool:
        self._emit('exit-button', 'pressed')
        return self.unlock()

    def update_door_sensor(self, door_open: bool) -> None:
        with self._lock:
            self._door_open = bool(door_open)
        self._emit('door-sensor', 'state', door_open)

    def trigger_alarm(self, duration: Optional[float] = None) -> None:
        seconds = float(duration or self._alarm_duration)
        with self._lock:
            if self._alarm_timer is not None:
                self._alarm_timer.cancel()
            self._alarm_active = True
            timer = threading.Timer(seconds, self.clear_alarm)
            timer.daemon = True
            self._alarm_timer = timer
            timer.start()
        self._emit('alarm', 'trigger', seconds)

    def clear_alarm(self) -> None:
        with self._lock:
            if self._alarm_timer is not None:
                self._alarm_timer.cancel()
                self._alarm_timer = None
            self._alarm_active = False
        self._emit('alarm', 'clear')

    # ------------------------------------------------------------------
    def health(self) -> List[DeviceStatus]:
        mode = str(self.config.get('mode', 'simulator')).lower()
        devices = [
            DeviceStatus('door-lock', 'relay_lock', True, True,
                         {'mode': mode, 'state': self.relay.state}),
            DeviceStatus('door-sensor', 'magnetic_sensor', True, True,
                         {'door_open': self._door_open}),
            DeviceStatus('exit-button', 'push_button', True, True, {}),
            DeviceStatus('alarm', 'audible_visual_alarm', True, True,
                         {'active': self._alarm_active}),
            DeviceStatus('external-reader', 'card_or_biometric_reader', True, True,
                         {'protocol': str(self.config.get('reader_protocol', 'wiegand26'))}),
        ]
        return devices

    def shutdown(self) -> None:
        with self._lock:
            if self._alarm_timer is not None:
                self._alarm_timer.cancel()
            if hasattr(self.relay, 'shutdown'):
                self.relay.shutdown()
            else:
                self.relay.close()
