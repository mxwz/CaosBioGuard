"""前台 Agent：面向实时用户交互，同步执行并带超时保护。

特征：
- 运行在请求线程，调用后立即返回 :class:`AgentResult`，适合 Kiosk / Web / 移动端的在线请求；
- 写操作未确认时返回 ``pending_confirmation``，前端带上确认标记重新提交即可；
- 用独立线程 + 超时控制，避免能力调用卡死整个请求。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Optional

from .base import AgentMessage, AgentResult, AgentRole, Task, TaskStatus


class FrontstageAgent:
    """前台同步 Agent，内部包装一个主 Agent。"""

    role = AgentRole.FRONTSTAGE
    name = 'frontstage'
    display_name = '前台 Agent'

    def __init__(self, orchestrator: Any, default_timeout: float = 15.0):
        self._orchestrator = orchestrator
        self.default_timeout = default_timeout

    def submit(
        self,
        goal: str = '',
        intent: str = '',
        arguments: Optional[dict] = None,
        confirmed: bool = False,
        sender: str = 'web',
        timeout: Optional[float] = None,
    ) -> AgentResult:
        task = Task(
            goal=goal,
            intent=intent,
            arguments=dict(arguments or {}),
            confirmed=confirmed,
            sender=sender,
        )
        wait = timeout if timeout is not None else self.default_timeout
        return self._run_with_timeout(task, wait)

    def _run_with_timeout(self, task: Task, timeout: float) -> AgentResult:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._orchestrator.run, task)
            try:
                return future.result(timeout=timeout)
            except FutureTimeout:
                return AgentResult(
                    status=TaskStatus.ERROR,
                    task_id=task.task_id,
                    agent=self.name,
                    messages=[AgentMessage('error', f'前台执行超时（{timeout:g}s）')],
                )

    def describe(self) -> dict:
        return {
            'name': self.name,
            'display_name': self.display_name,
            'role': self.role.value,
            'default_timeout': self.default_timeout,
        }
