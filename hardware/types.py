"""硬件端通用数据类型。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class DeviceStatus:
    name: str
    kind: str
    online: bool
    enabled: bool
    details: Dict[str, Any] = field(default_factory=dict)
    last_error: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'kind': self.kind,
            'online': self.online,
            'enabled': self.enabled,
            'details': self.details,
            'last_error': self.last_error,
        }


@dataclass(frozen=True)
class HardwareEvent:
    device: str
    event: str
    value: Any = None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {'device': self.device, 'event': self.event, 'value': self.value, 'ts': self.ts}
