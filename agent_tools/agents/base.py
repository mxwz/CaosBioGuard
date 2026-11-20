"""Agent 框架基础：任务、结果、消息数据类与 Agent 基类。

设计要点：
- :class:`Task` 描述「要做什么」，:class:`AgentResult` 描述「做得怎么样」，二者均可 JSON 序列化。
- :class:`BaseAgent` 只负责统一的能力调用与生命周期，不耦合具体业务，业务在子 Agent 中实现。
- 主/子、前台/后台是两个正交维度，分别用 :class:`AgentRole` 与运行位置区分。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    OK = 'ok'
    PENDING_CONFIRMATION = 'pending_confirmation'
    ERROR = 'error'


class AgentRole(str, Enum):
    ORCHESTRATOR = 'orchestrator'   # 主 Agent：编排 / 路由 / 汇总
    SUB = 'sub'                     # 子 Agent：单一领域执行
    FRONTSTAGE = 'frontstage'       # 前台：实时同步
    BACKSTAGE = 'backstage'         # 后台：异步长任务


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Task:
    """一次 Agent 调用的任务描述。"""

    goal: str                                       # 自然语言目标 / 指令
    intent: str = ''                                # 归一化意图（可由调用方给出或主 Agent 识别）
    arguments: Dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=new_task_id)
    confirmed: bool = False                         # 写操作是否已二次确认
    context: Dict[str, Any] = field(default_factory=dict)
    sender: str = ''                                # 来源：kiosk / web / mobile / agent / scheduler

    def to_dict(self) -> dict:
        return {
            'task_id': self.task_id,
            'goal': self.goal,
            'intent': self.intent,
            'arguments': self.arguments,
            'confirmed': self.confirmed,
            'context': self.context,
            'sender': self.sender,
        }


@dataclass
class AgentMessage:
    """Agent 执行过程中的人类可读消息。"""

    level: str           # info / warn / error
    text: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {'level': self.level, 'text': self.text, 'data': self.data}


@dataclass
class AgentResult:
    """Agent 执行结果。"""

    status: TaskStatus
    task_id: str = ''
    agent: str = ''
    data: Any = None
    messages: List[AgentMessage] = field(default_factory=list)
    confirm_hint: str = ''
    # 待确认时回传必要载荷，确认后原样回传即可
    pending: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == TaskStatus.OK

    def to_dict(self) -> dict:
        return {
            'status': self.status.value,
            'task_id': self.task_id,
            'agent': self.agent,
            'data': self.data,
            'messages': [m.to_dict() for m in self.messages],
            'confirm_hint': self.confirm_hint,
            'pending': self.pending,
        }


class BaseAgent:
    """所有 Agent 的基类，统一能力调用与元信息。"""

    name: str = 'base'
    display_name: str = '基础 Agent'
    role: AgentRole = AgentRole.SUB
    description: str = ''
    intents: tuple = ()                 # 可处理的归一化意图
    capability_names: tuple = ()        # 默认装配的能力名

    def __init__(self, capabilities: Optional['CapabilityCatalog'] = None, **config: Any):
        self._capabilities = capabilities
        self.config = dict(config)
        self.log = logging.getLogger(f'agent.{self.name}')

    # ------------------------------------------------------------------
    @property
    def capabilities(self) -> Optional['CapabilityCatalog']:
        return self._capabilities

    def attach(self, capabilities: 'CapabilityCatalog') -> None:
        self._capabilities = capabilities

    def call(self, capability: str, **arguments: Any) -> Any:
        """调用一个能力（工具 / 插件 / 技能），返回其结果数据。"""
        if self._capabilities is None:
            raise RuntimeError(f'Agent {self.name} 未装配能力目录')
        return self._capabilities.invoke(capability, arguments)

    def run(self, task: Task) -> AgentResult:
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            'name': self.name,
            'display_name': self.display_name,
            'role': self.role.value,
            'description': self.description,
            'intents': list(self.intents),
            'capabilities': list(self.capability_names),
        }
