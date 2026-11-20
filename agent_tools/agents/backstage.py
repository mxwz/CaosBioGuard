"""后台 Agent：面向异步 / 定时 / 长任务，线程池执行并跟踪任务状态。

特征：
- ``submit`` 立即返回任务 ID，任务在后台线程池执行，不阻塞前台请求；
- 记录每个任务的状态、进度、尝试次数、结果与错误，支持按 ID 查询与列表；
- 失败自动重试（指数退避）；待确认 / 确定性错误不重试；
- 适用于数据同步、对账、批量处理、监控巡检、报告生成等场景。
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import AgentRole, Task, TaskStatus

logger = logging.getLogger('agent.backstage')


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


@dataclass
class BackgroundRecord:
    """后台任务的运行记录。"""

    task_id: str
    intent: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    attempts: int = 0
    result: Any = None
    error: str = ''
    confirm_hint: str = ''
    pending: Dict[str, Any] = field(default_factory=dict)
    submitted_at: str = field(default_factory=_now)
    finished_at: str = ''

    def to_dict(self) -> dict:
        return {
            'task_id': self.task_id,
            'intent': self.intent,
            'status': self.status.value,
            'progress': self.progress,
            'attempts': self.attempts,
            'result': self.result,
            'error': self.error,
            'confirm_hint': self.confirm_hint,
            'pending': self.pending,
            'submitted_at': self.submitted_at,
            'finished_at': self.finished_at,
        }


class BackstageAgent:
    """后台异步 Agent，内部包装一个主 Agent。"""

    role = AgentRole.BACKSTAGE
    name = 'backstage'
    display_name = '后台 Agent'

    def __init__(self, orchestrator: Any, max_workers: int = 4, max_retries: int = 2,
                 backoff_base: float = 0.4):
        self._orchestrator = orchestrator
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='backstage')
        self._records: Dict[str, BackgroundRecord] = {}

    # ------------------------------------------------------------------
    def submit(
        self,
        goal: str = '',
        intent: str = '',
        arguments: Optional[dict] = None,
        sender: str = 'scheduler',
    ) -> str:
        task = Task(
            goal=goal,
            intent=intent,
            arguments=dict(arguments or {}),
            sender=sender,
        )
        record = BackgroundRecord(task_id=task.task_id, intent=task.intent or goal[:24])
        self._records[task.task_id] = record
        self._pool.submit(self._execute, task, record)
        return task.task_id

    def _execute(self, task: Task, record: BackgroundRecord) -> None:
        record.status = TaskStatus.RUNNING
        for attempt in range(self._max_retries + 1):
            record.attempts = attempt + 1
            try:
                result = self._orchestrator.run(task)
            except Exception as exc:  # 运行期异常：按策略重试
                logger.warning('后台任务 %s 第 %s 次异常: %s', task.task_id, attempt + 1, exc)
                if attempt < self._max_retries:
                    time.sleep(self._backoff_base * (2 ** attempt))
                    continue
                record.status = TaskStatus.ERROR
                record.error = str(exc)
                record.finished_at = _now()
                return

            # 成功
            if result.status == TaskStatus.OK:
                record.status = TaskStatus.OK
                record.progress = 100
                record.result = result.data
                record.finished_at = _now()
                return

            # 待确认 / 确定性错误：不重试，直接落状态
            record.status = result.status
            record.confirm_hint = result.confirm_hint
            record.pending = result.pending
            if result.messages:
                record.error = result.messages[0].text
            record.finished_at = _now()
            return

    # ------------------------------------------------------------------
    def get_task(self, task_id: str) -> Optional[dict]:
        record = self._records.get(task_id)
        return record.to_dict() if record else None

    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[dict]:
        records = list(self._records.values())
        if status is not None:
            records = [r for r in records if r.status == status]
        return [r.to_dict() for r in records]

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait)

    def describe(self) -> dict:
        return {
            'name': self.name,
            'display_name': self.display_name,
            'role': self.role.value,
            'max_workers': self._pool._max_workers,
            'max_retries': self._max_retries,
            'tracked_tasks': len(self._records),
        }
