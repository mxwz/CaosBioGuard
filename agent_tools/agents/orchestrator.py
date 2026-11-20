"""主 Agent（Orchestrator）：意图识别、任务路由与结果汇总。

职责：
- 当任务未显式给出意图时，通过可插拔的 Planner 从自然语言目标识别意图；
- 把任务路由给能处理该意图的子 Agent 执行；
- 汇总并返回子 Agent 的结果。

Planner 默认采用确定性规则（:class:`RulePlanner`），零外部依赖、结果可预测；
需要 LLM 规划时实现同样的 ``plan`` 接口替换即可，编排与子 Agent 无需改动。
"""
from __future__ import annotations

from typing import Any, List, Optional, Protocol

from .base import AgentMessage, AgentResult, AgentRole, BaseAgent, Task, TaskStatus


class Planner(Protocol):
    """意图规划器协议：输入目标与参数，输出归一化意图（无法识别返回空串）。"""

    def plan(self, goal: str, arguments: dict) -> str: ...


# 规则按书写顺序匹配，第一个命中胜出；关键词统一小写比较
_RULES: List[tuple] = [
    (('日报', '考勤报表'), 'attendance_daily_report'),
    (('健康总览', '系统总览', 'overview'), 'system_health_overview'),
    (('考勤', '打卡', 'attendance'), 'query_attendance'),
    (('门禁', '通行', 'access'), 'query_access'),
    (('统计', 'statistics'), 'query_statistics'),
    (('审计日志', '管理日志', '管理员日志'), 'query_admin_logs'),
    (('系统日志', '日志', 'log'), 'query_system_logs'),
    (('设备详情',), 'query_device_details'),
    (('设备', 'device'), 'query_devices'),
    (('删除人脸', '移除人脸'), 'delete_face'),
    (('新增人脸', '添加人脸', '录入人脸', '人脸注册'), 'add_face'),
    (('人脸', 'face'), 'list_faces'),
    (('修改配置', '设置配置', '更新配置'), 'set_config'),
    (('配置', 'config'), 'get_config'),
    (('对账', 'reconcile'), 'trigger_reconcile'),
    (('同步', 'sync'), 'trigger_sync'),
    (('健康', '诊断', 'health'), 'health_check'),
]


class RulePlanner:
    """确定性关键词规则规划器。"""

    def plan(self, goal: str, arguments: dict) -> str:
        text = (goal or '').lower()
        for keywords, intent in _RULES:
            if any(keyword in text for keyword in keywords):
                return intent
        return ''


class OrchestratorAgent(BaseAgent):
    """主 Agent：持有并编排全部子 Agent。"""

    name = 'orchestrator'
    display_name = '主 Agent'
    role = AgentRole.ORCHESTRATOR
    description = '识别意图、路由到对应子 Agent 并汇总结果。'

    def __init__(self, sub_agents: List[BaseAgent],
                 planner: Optional[Planner] = None, **config: Any):
        super().__init__(**config)
        self._sub_agents = list(sub_agents)
        self.planner = planner or RulePlanner()

    # ------------------------------------------------------------------
    @property
    def sub_agents(self) -> List[BaseAgent]:
        return self._sub_agents

    def _route(self, intent: str) -> Optional[BaseAgent]:
        for agent in self._sub_agents:
            if hasattr(agent, 'can_handle') and agent.can_handle(intent):
                return agent
        return None

    def available_intents(self) -> List[str]:
        intents: List[str] = []
        for agent in self._sub_agents:
            intents.extend(getattr(agent, 'intents', ()))
        return sorted(set(intents))

    def run(self, task: Task) -> AgentResult:
        # 1. 补齐意图
        if not task.intent:
            task.intent = self.planner.plan(task.goal, task.arguments)

        # 2. 意图无法识别
        if not task.intent:
            return AgentResult(
                status=TaskStatus.ERROR,
                task_id=task.task_id,
                agent=self.name,
                messages=[AgentMessage('error', '无法识别该指令的意图，请显式指定 intent')],
                data={'available_intents': self.available_intents()},
            )

        # 3. 路由到子 Agent
        sub = self._route(task.intent)
        if sub is None:
            return AgentResult(
                status=TaskStatus.ERROR,
                task_id=task.task_id,
                agent=self.name,
                messages=[AgentMessage('error', f'没有能处理意图 {task.intent} 的子 Agent')],
                data={'intent': task.intent, 'available_intents': self.available_intents()},
            )

        # 4. 执行并返回（保留子 Agent 的确认/错误状态）
        result = sub.run(task)
        return result

    def describe(self) -> dict:
        return {
            **super().describe(),
            'planner': type(self.planner).__name__,
            'sub_agents': [agent.describe() for agent in self._sub_agents],
        }
