"""Agent 系统装配工厂：一次性组装能力目录、子 Agent、主 Agent 与前台/后台 Agent。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .backstage import BackstageAgent
from .base import BaseAgent
from .capabilities import CapabilityCatalog, build_catalog
from .frontstage import FrontstageAgent
from .orchestrator import OrchestratorAgent
from .sub_agents import build_default_sub_agents


@dataclass
class AgentSystem:
    """组装好的 Agent 系统，统一持有各组件。"""

    orchestrator: OrchestratorAgent
    frontstage: FrontstageAgent
    backstage: BackstageAgent
    catalog: CapabilityCatalog

    def shutdown(self) -> None:
        self.backstage.shutdown(wait=False)


def build_agent_system(tool_registry: Optional[Any] = None) -> AgentSystem:
    """从现有工具注册器构建完整 Agent 系统。

    不传 tool_registry 时仅含内置技能，便于离线单元测试。
    """
    catalog = build_catalog(tool_registry)
    sub_agents = build_default_sub_agents(catalog)
    orchestrator = OrchestratorAgent(sub_agents)
    frontstage = FrontstageAgent(orchestrator)
    backstage = BackstageAgent(orchestrator)
    return AgentSystem(
        orchestrator=orchestrator,
        frontstage=frontstage,
        backstage=backstage,
        catalog=catalog,
    )
