"""跨平台运行环境检测与适配工具。

统一识别操作系统、CPU 架构、位数与运行形态（源码 / PyInstaller 冻结包），
并提供平台相关的默认值（OpenCV 摄像头后端、串口设备、动态库后缀、资源路径），
避免各模块自行判断平台导致分支不一致或在 Windows/Linux 上运行报错。
"""

from __future__ import annotations

import platform
import sys
from enum import Enum
from pathlib import Path
from typing import Optional


class OSFamily(str, Enum):
    WINDOWS = 'windows'
    LINUX = 'linux'
    MACOS = 'macos'
    UNKNOWN = 'unknown'


class ArchFamily(str, Enum):
    X86_64 = 'x86_64'
    ARM64 = 'arm64'
    ARM32 = 'arm32'
    X86_32 = 'x86_32'
    UNKNOWN = 'unknown'


def _detect_os() -> OSFamily:
    if sys.platform.startswith('win'):
        return OSFamily.WINDOWS
    if sys.platform == 'darwin':
        return OSFamily.MACOS
    if sys.platform.startswith('linux'):
        return OSFamily.LINUX
    return OSFamily.UNKNOWN


def _detect_arch() -> ArchFamily:
    machine = (platform.machine() or '').lower()
    if machine in ('amd64', 'x86_64', 'x64'):
        return ArchFamily.X86_64
    if machine in ('arm64', 'aarch64'):
        return ArchFamily.ARM64
    if machine.startswith('arm'):
        return ArchFamily.ARM32
    if machine in ('i386', 'i486', 'i586', 'i686', 'x86'):
        return ArchFamily.X86_32
    return ArchFamily.UNKNOWN


# 模块级常量，import 即可用
OS_FAMILY = _detect_os()
ARCH_FAMILY = _detect_arch()
IS_WINDOWS = OS_FAMILY == OSFamily.WINDOWS
IS_LINUX = OS_FAMILY == OSFamily.LINUX
IS_MACOS = OS_FAMILY == OSFamily.MACOS
IS_64BIT = sys.maxsize > 2 ** 32
IS_FROZEN = bool(getattr(sys, 'frozen', False))
IS_ARM = ARCH_FAMILY in (ArchFamily.ARM64, ArchFamily.ARM32)


def project_root() -> Path:
    """项目根目录：冻结包返回 exe 所在目录，源码运行返回本模块所在目录。"""
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(relative: str) -> Path:
    """兼容 PyInstaller 的资源路径：冻结包优先使用 _MEIPASS，源码运行相对项目根。"""
    if IS_FROZEN:
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass) / relative
    return project_root() / relative


def default_camera_backend() -> Optional[int]:
    """OpenCV 摄像头默认后端：Windows 用 DirectShow，Linux 用 V4L2，其余回退默认。"""
    import cv2

    if IS_WINDOWS and hasattr(cv2, 'CAP_DSHOW'):
        return cv2.CAP_DSHOW
    if IS_LINUX and hasattr(cv2, 'CAP_V4L2'):
        return cv2.CAP_V4L2
    return cv2.CAP_ANY if hasattr(cv2, 'CAP_ANY') else None


def default_serial_port() -> str:
    """串口默认设备：Windows 为 COM3，Linux 自动探测 /dev/ttyUSB0 等常见节点。"""
    if IS_WINDOWS:
        return 'COM3'
    if IS_LINUX:
        for candidate in ('/dev/ttyUSB0', '/dev/ttyS0', '/dev/ttyAMA0'):
            if Path(candidate).exists():
                return candidate
        return '/dev/ttyUSB0'
    return ''


def shared_library_suffixes() -> tuple:
    """动态库文件名后缀约定，供通用厂商适配器按平台加载。"""
    if IS_WINDOWS:
        return ('.dll',)
    if IS_MACOS:
        return ('.dylib', '.so')
    return ('.so',)


def environment_summary() -> dict:
    """供日志/健康检查/部署校验使用的运行环境摘要。"""
    return {
        'os': OS_FAMILY.value,
        'os_release': platform.release(),
        'arch': ARCH_FAMILY.value,
        'is_64bit': IS_64BIT,
        'frozen': IS_FROZEN,
        'python': platform.python_version(),
    }
