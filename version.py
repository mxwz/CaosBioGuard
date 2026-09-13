"""Caos BioGuard 版本号定义模块。

整个项目的版本号统一在此处管理，其它模块一律通过导入 ``CURRENT_VERSION`` 使用，
避免版本号散落多处、修改时遗漏。

版本形态（ReleaseType）：
- DEV（开发版）：开发中的版本，例如 ``v0.1.3-dev``
- BETA（预览版）：后续可能推出的内测版，例如 ``v0.1.3-beta``
- RELEASE（正式版）：功能完善且无严重漏洞的版本，例如 ``v0.1.3``

版本号遵循语义化版本（Semantic Versioning）：``v{major}.{minor}.{patch}``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ReleaseType(IntEnum):
    """版本形态枚举。

    数值越小越"早"，用于版本比较：同一主版本号下，开发版（DEV）< 预览版（BETA）< 正式版（RELEASE）。
    """
    DEV = 0
    BETA = 1
    RELEASE = 2

    @property
    def suffix(self) -> str:
        """版本号后缀，开发版返回 ``-dev``，预览版返回 ``-beta``，正式版返回空字符串。"""
        if self is ReleaseType.DEV:
            return "-dev"
        if self is ReleaseType.BETA:
            return "-beta"
        return ""


@dataclass(frozen=True, order=True)
class VersionInfo:
    """版本号数据类（不可变、可比较、可序列化）。

    ``order=True`` 会按字段顺序 (major, minor, patch, release_type) 自动生成比较方法，
    便于未来拉取更新时判断「本地版本是否落后于远程版本」。
    """

    major: int = 0
    minor: int = 1
    patch: int = 3
    release_type: ReleaseType = ReleaseType.RELEASE

    @property
    def tag(self) -> str:
        """完整版本号字符串，如 ``v0.1.3`` 或 ``v0.1.3-beta``。"""
        return f"v{self.major}.{self.minor}.{self.patch}{self.release_type.suffix}"

    def __str__(self) -> str:
        return self.tag

    def __repr__(self) -> str:
        return f"VersionInfo({self.tag})"

    def is_older_than(self, other: "VersionInfo") -> bool:
        """判断当前版本是否早于 ``other``（用于拉取更新判断）。"""
        return self < other

    def to_dict(self) -> dict:
        """序列化为字典（用于热更新 / 网络传输）。"""
        return {
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "release_type": self.release_type.name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VersionInfo":
        """从字典反序列化。"""
        return cls(
            major=int(data.get("major", 0)),
            minor=int(data.get("minor", 0)),
            patch=int(data.get("patch", 0)),
            release_type=ReleaseType[data.get("release_type", "RELEASE")],
        )

    @classmethod
    def from_tag(cls, tag: str) -> "VersionInfo":
        """从 ``v0.1.3`` 或 ``v0.1.3-beta`` 形式的字符串解析。"""
        text = tag.strip().lstrip("vV")
        release_type = ReleaseType.RELEASE
        if text.endswith("-dev"):
            release_type = ReleaseType.DEV
            text = text[: -len("-dev")]
        elif text.endswith("-beta"):
            release_type = ReleaseType.BETA
            text = text[: -len("-beta")]
        parts = text.split(".")
        if len(parts) != 3:
            raise ValueError(f"非法的版本号字符串: {tag!r}")
        try:
            return cls(*(int(p) for p in parts), release_type=release_type)
        except ValueError:
            raise ValueError(f"非法的版本号字符串: {tag!r}")


# 当前项目版本号：每次发布更新时只需修改此处
CURRENT_VERSION = VersionInfo(0, 1, 3)
# version.py 最后一行
# CURRENT_VERSION = VersionInfo(0, 1, 3)                         # 正式版 v0.1.3
# CURRENT_VERSION = VersionInfo(0, 1, 3, ReleaseType.BETA)       # 预览版 v0.1.3-beta
# CURRENT_VERSION = VersionInfo(0, 1, 3, ReleaseType.DEV)        # 开发版 v0.1.3-dev