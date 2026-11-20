"""子 Agent：按领域拆分，实际执行能力调用。

每个子 Agent 只负责一个领域，声明可处理的意图集合，执行时把任务转发给能力目录，
并把「确认 / 错误」统一转换为 :class:`AgentResult`。主 Agent 只做路由，不直接执行业务。
"""
from __future__ import annotations

from typing import Any

from .base import AgentMessage, AgentResult, AgentRole, BaseAgent, Task, TaskStatus
from .capabilities import CapabilityError, ConfirmationRequired


class CapabilitySubAgent(BaseAgent):
    """子 Agent 通用基类：默认 ``intent`` 即能力名，子类只需声明意图与元信息。"""

    role = AgentRole.SUB
    intents: tuple = ()

    def can_handle(self, intent: str) -> bool:
        return intent in self.intents

    def resolve_capability(self, task: Task) -> str:
        """意图到能力名的映射，默认同名；子类可覆盖做特殊路由。"""
        return task.intent

    def run(self, task: Task) -> AgentResult:
        try:
            capability = self.resolve_capability(task)
            data = self._capabilities.invoke(
                capability, task.arguments, confirmed=task.confirmed
            )
            return AgentResult(
                status=TaskStatus.OK,
                task_id=task.task_id,
                agent=self.name,
                data=data,
            )
        except ConfirmationRequired as confirm:
            return AgentResult(
                status=TaskStatus.PENDING_CONFIRMATION,
                task_id=task.task_id,
                agent=self.name,
                confirm_hint=confirm.hint,
                pending={
                    'intent': task.intent,
                    'arguments': confirm.payload
                    if confirm.payload is not None
                    else task.arguments,
                },
            )
        except Exception as exc:  # CapabilityError 及其它异常都归一为错误结果
            self.log.exception('子 Agent %s 执行失败', self.name)
            return AgentResult(
                status=TaskStatus.ERROR,
                task_id=task.task_id,
                agent=self.name,
                messages=[AgentMessage('error', str(exc))],
            )


class QuerySubAgent(CapabilitySubAgent):
    name = 'query_agent'
    display_name = '考勤门禁查询'
    description = '查询考勤、门禁、统计、系统日志与管理审计日志。'
    intents = (
        'query_attendance', 'query_access', 'query_statistics',
        'query_system_logs', 'query_admin_logs',
    )


class DeviceSubAgent(CapabilitySubAgent):
    name = 'device_agent'
    display_name = '设备管理'
    description = '查询设备列表与单设备详情、在线状态。'
    intents = ('query_devices', 'query_device_details')


class FaceLibrarySubAgent(CapabilitySubAgent):
    name = 'face_library_agent'
    display_name = '人脸库管理'
    description = '人脸库清单查询及新增、删除（写操作需确认）。'
    intents = ('list_faces', 'add_face', 'delete_face')


class ConfigSubAgent(CapabilitySubAgent):
    name = 'config_agent'
    display_name = '配置管理'
    description = '读取与修改系统配置（敏感字段脱敏，写操作需确认）。'
    intents = ('get_config', 'set_config')


class SystemSubAgent(CapabilitySubAgent):
    name = 'system_agent'
    display_name = '系统运维'
    description = '健康检查、触发数据同步与云端人脸库对账。'
    intents = ('health_check', 'trigger_sync', 'trigger_reconcile')


class SkillSubAgent(CapabilitySubAgent):
    name = 'skill_agent'
    display_name = '技能编排'
    description = '执行内置组合技能（考勤日报、系统健康总览）。'
    intents = ('attendance_daily_report', 'system_health_overview')


def build_default_sub_agents(catalog: Any) -> list[CapabilitySubAgent]:
    """构建一套默认子 Agent 并装配能力目录。"""
    agents = [
        QuerySubAgent(),
        DeviceSubAgent(),
        FaceLibrarySubAgent(),
        ConfigSubAgent(),
        SystemSubAgent(),
        SkillSubAgent(),
    ]
    for agent in agents:
        agent.attach(catalog)
    return agents
