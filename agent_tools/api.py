"""Agent v2 HTTP 接口：把分层 Agent 系统暴露为 REST 端点。

端点：
- ``POST /api/agent/v2/invoke``      前台同步调用（goal/intent/arguments/confirmed）
- ``GET  /api/agent/v2/structure``   主 Agent 与子 Agent 结构
- ``GET  /api/agent/v2/capabilities`` 能力目录（可用 ?kind=tool/plugin/skill 过滤）
- ``POST /api/agent/v2/tasks``       提交后台任务，返回 task_id
- ``GET  /api/agent/v2/tasks``       后台任务列表（可按 status 过滤）
- ``GET  /api/agent/v2/tasks/<id>``  查询单个后台任务状态与结果
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .agents import AgentSystem, TaskStatus
from .agents.capabilities import CapabilityKind


def create_agent_v2_blueprint(system: AgentSystem) -> Blueprint:
    bp = Blueprint('agent_v2', __name__)

    @bp.route('/api/agent/v2/invoke', methods=['POST'])
    def invoke():
        data = request.get_json(silent=True) or {}
        result = system.frontstage.submit(
            goal=data.get('goal', ''),
            intent=data.get('intent', ''),
            arguments=data.get('arguments') or {},
            confirmed=bool(data.get('confirmed')),
            sender=data.get('sender', 'web'),
            timeout=data.get('timeout'),
        )
        return jsonify(result.to_dict())

    @bp.route('/api/agent/v2/structure', methods=['GET'])
    def structure():
        return jsonify({
            'orchestrator': system.orchestrator.describe(),
            'frontstage': system.frontstage.describe(),
            'backstage': system.backstage.describe(),
        })

    @bp.route('/api/agent/v2/capabilities', methods=['GET'])
    def capabilities():
        kind = request.args.get('kind')
        cap_kind = None
        if kind:
            try:
                cap_kind = CapabilityKind(kind)
            except ValueError:
                return jsonify({'status': 'error', 'error': f'非法 kind: {kind}'}), 400
        return jsonify({'capabilities': system.catalog.list(cap_kind)})

    @bp.route('/api/agent/v2/tasks', methods=['POST'])
    def submit_task():
        data = request.get_json(silent=True) or {}
        task_id = system.backstage.submit(
            goal=data.get('goal', ''),
            intent=data.get('intent', ''),
            arguments=data.get('arguments') or {},
            sender=data.get('sender', 'scheduler'),
        )
        return jsonify({'task_id': task_id, 'status': TaskStatus.PENDING.value}), 202

    @bp.route('/api/agent/v2/tasks', methods=['GET'])
    def list_tasks():
        status = request.args.get('status')
        task_status = TaskStatus(status) if status else None
        return jsonify({'tasks': system.backstage.list_tasks(task_status)})

    @bp.route('/api/agent/v2/tasks/<task_id>', methods=['GET'])
    def get_task(task_id):
        record = system.backstage.get_task(task_id)
        if record is None:
            return jsonify({'status': 'error', 'error': '任务不存在'}), 404
        return jsonify(record)

    return bp
