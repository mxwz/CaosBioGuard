"""能力目录：统一封装「工具 / 插件 / 技能」三类能力，供 Agent 按名调用。

三类能力的区别：
- **tool（工具）**：原子操作，对应现有 ``agent_tools`` 中的单个工具（如 query_attendance）。
- **plugin（插件）**：注册中心里可扩展的外部实现，经通用注册器调用。
- **skill（技能）**：把多个工具/能力编排成一个完整业务动作（如「生成考勤日报」）。

本模块只负责能力的注册、发现与调用适配，并把「需要二次确认」与「执行失败」
转为明确异常，由上层 Agent 决定如何响应；不依赖任何 Web 框架，可独立测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class CapabilityKind(str, Enum):
    TOOL = 'tool'
    PLUGIN = 'plugin'
    SKILL = 'skill'


class ConfirmationRequired(Exception):
    """写操作需要二次确认时抛出。"""

    def __init__(self, hint: str, payload: Any):
        super().__init__(hint)
        self.hint = hint
        self.payload = payload


class CapabilityError(Exception):
    """能力执行失败时抛出。"""


@dataclass
class Capability:
    """一个可被调用的能力。

    ``entry`` 统一签名为 ``entry(arguments: dict, confirmed: bool) -> Any``，
    成功返回结果数据；需要确认时抛 :class:`ConfirmationRequired`。
    """

    name: str
    kind: CapabilityKind
    description: str = ''
    requires_confirmation: bool = False
    entry: Optional[Callable[[Dict[str, Any], bool], Any]] = None
    tags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'kind': self.kind.value,
            'description': self.description,
            'requires_confirmation': self.requires_confirmation,
            'tags': list(self.tags),
        }


class CapabilityCatalog:
    """能力目录：登记、查询并按名调用全部能力。"""

    def __init__(self) -> None:
        self._items: Dict[str, Capability] = {}

    # ------------------------------------------------------------------
    def register(self, capability: Capability) -> Capability:
        if not capability.name:
            raise ValueError('能力缺少 name')
        if not callable(capability.entry):
            raise ValueError(f'能力 {capability.name} 缺少可调用 entry')
        self._items[capability.name] = capability
        return capability

    def register_callable(
        self,
        name: str,
        entry: Callable[[Dict[str, Any], bool], Any],
        kind: CapabilityKind = CapabilityKind.TOOL,
        description: str = '',
        requires_confirmation: bool = False,
        tags: Optional[List[str]] = None,
    ) -> Capability:
        """便捷注册：直接给一个可调用对象。"""
        cap = Capability(
            name=name,
            kind=kind,
            description=description,
            requires_confirmation=requires_confirmation,
            entry=entry,
            tags=list(tags or []),
        )
        return self.register(cap)

    def get(self, name: str) -> Optional[Capability]:
        return self._items.get(name)

    def names(self) -> List[str]:
        return list(self._items)

    def list(self, kind: Optional[CapabilityKind] = None) -> List[dict]:
        items = self._items.values()
        if kind is not None:
            items = [c for c in items if c.kind == kind]
        return [c.to_dict() for c in items]

    # ------------------------------------------------------------------
    def invoke(self, name: str, arguments: Optional[Dict[str, Any]] = None,
               confirmed: bool = False) -> Any:
        cap = self._items.get(name)
        if cap is None:
            raise CapabilityError(f'未知能力: {name}')
        return cap.entry(dict(arguments or {}), confirmed)


# ---------------------------------------------------------------------------
# 适配器：把现有工具注册器（ToolRegistry）接入能力目录
# ---------------------------------------------------------------------------

def _tool_entry(tool_registry: Any, tool_name: str) -> Callable:
    """生成适配现有 ``ToolRegistry.dispatch`` 的统一 entry。"""

    def entry(arguments: Dict[str, Any], confirmed: bool) -> Any:
        args = dict(arguments)
        if confirmed:
            args['_confirmed'] = True
        body, _code = tool_registry.dispatch(tool_name, args)
        status = body.get('status')
        if status == 'ok':
            return body.get('result')
        if status == 'pending_confirmation':
            raise ConfirmationRequired(
                body.get('message', '该操作需要二次确认'),
                body.get('arguments'),
            )
        raise CapabilityError(body.get('error', '工具执行失败'))

    return entry


def attach_tool_registry(catalog: CapabilityCatalog, tool_registry: Any) -> None:
    """把工具注册器中的全部工具（含自定义工具）封装进能力目录。"""
    for meta in tool_registry.schema_list():
        name = meta['name']
        catalog.register_callable(
            name=name,
            entry=_tool_entry(tool_registry, name),
            kind=CapabilityKind.TOOL,
            description=meta.get('description', ''),
            requires_confirmation=bool(meta.get('requires_confirmation')),
            tags=list(meta.get('tags', [])),
        )


# ---------------------------------------------------------------------------
# 内置技能（skill）：编排多个工具完成完整业务动作
# ---------------------------------------------------------------------------

def _skill_attendance_report(catalog: CapabilityCatalog) -> Callable:
    def entry(arguments: Dict[str, Any], confirmed: bool) -> Any:
        start = arguments.get('start_date')
        end = arguments.get('end_date')
        attendance = catalog.invoke(
            'query_attendance',
            {'start_date': start, 'end_date': end, 'limit': arguments.get('limit', 500)},
        )
        statistics = catalog.invoke(
            'query_statistics', {'start_date': start, 'end_date': end}
        )
        records = attendance.get('records', []) if isinstance(attendance, dict) else []
        return {
            'range': {'start_date': start, 'end_date': end},
            'record_count': len(records),
            'statistics': statistics,
            'records': records,
        }

    return entry


def _skill_health_overview(catalog: CapabilityCatalog) -> Callable:
    def entry(arguments: Dict[str, Any], confirmed: bool) -> Any:
        health = catalog.invoke('health_check', {})
        devices = catalog.invoke('query_devices', {})
        config = catalog.invoke('get_config', {'section': 'cloud_enabled'})
        return {
            'health': health,
            'device_count': devices.get('total') if isinstance(devices, dict) else None,
            'cloud_enabled': config.get('cloud_enabled') if isinstance(config, dict) else None,
        }

    return entry


def attach_builtin_skills(catalog: CapabilityCatalog) -> None:
    """注册内置编排技能；依赖的工具缺失时调用阶段才会报错，注册不报错。"""
    catalog.register_callable(
        name='attendance_daily_report',
        entry=_skill_attendance_report(catalog),
        kind=CapabilityKind.SKILL,
        description='汇总指定时间范围的考勤记录与统计，生成考勤日报数据。',
        tags=['考勤', '报表'],
    )
    catalog.register_callable(
        name='system_health_overview',
        entry=_skill_health_overview(catalog),
        kind=CapabilityKind.SKILL,
        description='汇总服务健康、设备数量与云端开关，给出系统健康总览。',
        tags=['健康', '诊断'],
    )


def build_catalog(tool_registry: Optional[Any] = None) -> CapabilityCatalog:
    """从现有工具注册器构建完整能力目录，并挂载内置技能。"""
    catalog = CapabilityCatalog()
    if tool_registry is not None:
        attach_tool_registry(catalog, tool_registry)
    attach_builtin_skills(catalog)
    return catalog
