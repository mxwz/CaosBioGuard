"""分层 Agent 框架：主 / 子 Agent × 前台 / 后台 Agent，统一调用工具、插件与技能。

公开入口：
- :func:`build_agent_system` 组装完整系统；
- :class:`Task` / :class:`AgentResult` 为标准任务与结果；
- :class:`CapabilityCatalog` 为能力目录。
"""
from .assembly import AgentSystem, build_agent_system
from .backstage import BackstageAgent, BackgroundRecord
from .base import (
    AgentMessage,
    AgentResult,
    AgentRole,
    BaseAgent,
    Task,
    TaskStatus,
)
from .capabilities import (
    Capability,
    CapabilityCatalog,
    CapabilityKind,
    CapabilityError,
    ConfirmationRequired,
)
from .frontstage import FrontstageAgent
from .orchestrator import OrchestratorAgent, RulePlanner
from .sub_agents import CapabilitySubAgent, build_default_sub_agents

__all__ = [
    'AgentSystem', 'build_agent_system',
    'BackstageAgent', 'BackgroundRecord',
    'AgentMessage', 'AgentResult', 'AgentRole', 'BaseAgent', 'Task', 'TaskStatus',
    'Capability', 'CapabilityCatalog', 'CapabilityKind', 'CapabilityError',
    'ConfirmationRequired',
    'FrontstageAgent', 'OrchestratorAgent', 'RulePlanner',
    'CapabilitySubAgent', 'build_default_sub_agents',
]
