"""分层 Agent 框架测试：能力目录、子 Agent、主 Agent 编排、前台/后台与 HTTP 接口。

使用假工具注册器（FakeToolRegistry）模拟现有 ToolRegistry 的成功 / 待确认 / 失败行为，
保证测试不依赖真实数据库或外部服务。
"""
import time

import pytest
from flask import Flask

from agent_tools import build_agent_system, create_agent_v2_blueprint
from agent_tools.agents import (
    CapabilityCatalog,
    CapabilityError,
    CapabilityKind,
    CapabilitySubAgent,
    ConfirmationRequired,
    OrchestratorAgent,
    RulePlanner,
    Task,
    TaskStatus,
)
from agent_tools.agents.assembly import AgentSystem
from agent_tools.agents.backstage import BackstageAgent
from agent_tools.agents.frontstage import FrontstageAgent


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------

class FakeToolRegistry:
    """模拟现有 ToolRegistry：schema_list + dispatch，含确认与失败分支。"""

    def __init__(self):
        self._tools = [
            {'name': 'echo', 'description': '回显参数', 'requires_confirmation': False, 'tags': []},
            {'name': 'write_thing', 'description': '写操作', 'requires_confirmation': True, 'tags': ['写']},
            {'name': 'fail_thing', 'description': '失败操作', 'requires_confirmation': False, 'tags': []},
        ]

    def schema_list(self):
        return self._tools

    def dispatch(self, name, args):
        if name == 'echo':
            return {'status': 'ok', 'result': {'echoed': args}}, 200
        if name == 'write_thing':
            if not args.get('_confirmed'):
                return {'status': 'pending_confirmation',
                        'message': '请确认写操作', 'arguments': args}, 200
            return {'status': 'ok', 'result': {'written': True}}, 200
        if name == 'fail_thing':
            return {'status': 'error', 'error': '故意失败'}, 500
        return {'status': 'error', 'error': f'unknown {name}'}, 404


class FakeSubAgent(CapabilitySubAgent):
    name = 'fake_agent'
    display_name = '假领域子 Agent'
    intents = ('echo', 'write_thing', 'fail_thing')


def _build_system() -> AgentSystem:
    """基于假注册器构建可编排的系统（替换默认子 Agent 为 FakeSubAgent）。"""
    base = build_agent_system(FakeToolRegistry())
    sub = FakeSubAgent()
    sub.attach(base.catalog)
    orchestrator = OrchestratorAgent([sub])
    return AgentSystem(
        orchestrator=orchestrator,
        frontstage=FrontstageAgent(orchestrator),
        backstage=BackstageAgent(orchestrator, max_retries=1),
        catalog=base.catalog,
    )


# ---------------------------------------------------------------------------
# 1. 能力目录
# ---------------------------------------------------------------------------

def test_catalog_invoke_success_confirmation_and_unknown():
    catalog = CapabilityCatalog()

    def ok_entry(args, confirmed):
        return {'ok': True, 'args': args}

    def confirm_entry(args, confirmed):
        if not confirmed:
            raise ConfirmationRequired('需要确认', args)
        return {'confirmed': True}

    catalog.register_callable('ok_cap', ok_entry)
    catalog.register_callable('confirm_cap', confirm_entry,
                              requires_confirmation=True)

    assert catalog.invoke('ok_cap', {'a': 1})['ok'] is True

    with pytest.raises(ConfirmationRequired):
        catalog.invoke('confirm_cap', {})
    assert catalog.invoke('confirm_cap', {}, confirmed=True) == {'confirmed': True}

    with pytest.raises(CapabilityError):
        catalog.invoke('not_exist', {})

    kinds = {c['kind'] for c in catalog.list()}
    assert kinds == {CapabilityKind.TOOL.value}


def test_catalog_adapts_fake_registry():
    system = _build_system()
    # 假工具已被适配进能力目录
    assert set(system.catalog.names()) >= {'echo', 'write_thing', 'fail_thing'}
    assert system.catalog.invoke('echo', {'x': 1}) == {'echoed': {'x': 1}}


# ---------------------------------------------------------------------------
# 2. 子 Agent：成功 / 待确认 / 错误
# ---------------------------------------------------------------------------

def test_sub_agent_success_confirmation_error():
    system = _build_system()
    sub = system.orchestrator.sub_agents[0]

    ok = sub.run(Task(goal='', intent='echo', arguments={'v': 2}))
    assert ok.status == TaskStatus.OK
    assert ok.data == {'echoed': {'v': 2}}

    pending = sub.run(Task(goal='', intent='write_thing', arguments={}))
    assert pending.status == TaskStatus.PENDING_CONFIRMATION
    assert pending.pending['intent'] == 'write_thing'

    confirmed = sub.run(Task(goal='', intent='write_thing', confirmed=True))
    assert confirmed.status == TaskStatus.OK
    assert confirmed.data == {'written': True}

    failed = sub.run(Task(goal='', intent='fail_thing'))
    assert failed.status == TaskStatus.ERROR
    assert failed.messages[0].text == '故意失败'


# ---------------------------------------------------------------------------
# 3. 主 Agent：路由与未知意图
# ---------------------------------------------------------------------------

def test_orchestrator_explicit_intent_routing():
    system = _build_system()
    result = system.orchestrator.run(Task(goal='', intent='echo', arguments={'k': 9}))
    assert result.status == TaskStatus.OK
    assert result.data == {'echoed': {'k': 9}}


def test_orchestrator_unknown_intent_lists_available():
    system = _build_system()
    result = system.orchestrator.run(Task(goal='一段完全无法识别的话'))
    assert result.status == TaskStatus.ERROR
    assert 'available_intents' in result.data
    assert 'echo' in result.data['available_intents']


def test_rule_planner_keywords():
    planner = RulePlanner()
    assert planner.plan('帮我查一下今天的考勤', {}) == 'query_attendance'
    assert planner.plan('查询设备在线状态', {}) == 'query_devices'
    assert planner.plan('生成考勤日报', {}) == 'attendance_daily_report'
    assert planner.plan('触发一次数据同步', {}) == 'trigger_sync'
    assert planner.plan('无意义内容 xyz', {}) == ''


# ---------------------------------------------------------------------------
# 4. 前台 Agent
# ---------------------------------------------------------------------------

def test_frontstage_submit_synchronous():
    system = _build_system()
    result = system.frontstage.submit(intent='echo', arguments={'a': 1})
    assert result.status == TaskStatus.OK
    assert result.data == {'echoed': {'a': 1}}


# ---------------------------------------------------------------------------
# 5. 后台 Agent：异步 + 轮询
# ---------------------------------------------------------------------------

def _wait_for(backstage, task_id, target, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = backstage.get_task(task_id)
        if record['status'] == target.value:
            return record
        time.sleep(0.05)
    raise AssertionError('后台任务未在超时内到达目标状态')


def test_backstage_async_execution():
    system = _build_system()
    task_id = system.backstage.submit(intent='echo', arguments={'a': 7})
    record = _wait_for(system.backstage, task_id, TaskStatus.OK)
    assert record['progress'] == 100
    assert record['result'] == {'echoed': {'a': 7}}
    assert len(system.backstage.list_tasks()) == 1


def test_backstage_records_error():
    system = _build_system()
    task_id = system.backstage.submit(intent='fail_thing')
    record = _wait_for(system.backstage, task_id, TaskStatus.ERROR)
    assert record['error'] == '故意失败'


# ---------------------------------------------------------------------------
# 6. HTTP 接口
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    system = _build_system()
    app = Flask(__name__)
    app.register_blueprint(create_agent_v2_blueprint(system))
    return app.test_client(), system


def test_http_invoke(client):
    test_client, _ = client
    resp = test_client.post('/api/agent/v2/invoke', json={
        'intent': 'echo', 'arguments': {'a': 1}})
    assert resp.status_code == 200
    assert resp.get_json()['data'] == {'echoed': {'a': 1}}


def test_http_structure_and_capabilities(client):
    test_client, _ = client
    structure = test_client.get('/api/agent/v2/structure')
    assert structure.get_json()['orchestrator']['name'] == 'orchestrator'

    caps = test_client.get('/api/agent/v2/capabilities?kind=tool')
    assert all(c['kind'] == 'tool' for c in caps.get_json()['capabilities'])


def test_http_background_task_lifecycle(client):
    test_client, _ = client
    resp = test_client.post('/api/agent/v2/tasks', json={
        'intent': 'echo', 'arguments': {'a': 3}})
    assert resp.status_code == 202
    task_id = resp.get_json()['task_id']

    deadline = time.time() + 5
    while time.time() < deadline:
        record = test_client.get(f'/api/agent/v2/tasks/{task_id}').get_json()
        if record['status'] == 'ok':
            break
        time.sleep(0.05)
    assert record['status'] == 'ok'
    assert record['result'] == {'echoed': {'a': 3}}
