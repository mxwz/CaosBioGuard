"""MCP（Model Context Protocol）适配层。

以最小化的 Streamable HTTP 服务暴露与 OpenAPI 完全相同的一批工具，
复用 agent_tools.tools 里的元数据（TOOLS）与统一分发（_dispatch），
供 Claude Desktop / Cursor / Dify 等任意 MCP 客户端消费。

传输选择：Stateless JSON（application/json），POST 到 /api/agent/mcp。
不启用会话（不返回 Mcp-Session-Id），每次请求/响应自包含，最省事且兼容 Dify 客户端。
"""
import json
import logging

from flask import Blueprint, Response, request

from .tools import TOOLS, _dispatch, _jsonable

logger = logging.getLogger(__name__)

mcp_bp = Blueprint('agent_mcp', __name__)

_PROTOCOL_VERSION = '2025-06-18'
_SERVER_INFO = {'name': 'CaosBioGuard', 'version': '1.0.0'}


def _mcp_tools_list():
    """tools/list：把 TOOLS 元数据转成 MCP 工具清单。"""
    return {
        'tools': [
            {
                'name': t['name'],
                'description': t['description'],
                'inputSchema': t['parameters'],
            }
            for t in TOOLS
        ]
    }


def _mcp_tool_call(name, arguments):
    """tools/call：复用统一分发，返回 MCP 标准 CallToolResult。"""
    if not name:
        return {
            'content': [{'type': 'text', 'text': json.dumps({'status': 'error', 'error': '缺少工具名'}, ensure_ascii=False)}],
            'isError': True,
        }

    body, _code = _dispatch(name, arguments or {})
    # pending_confirmation（写工具待确认）不算错误，作为普通结果回给 LLM 由它决策
    is_error = body.get('status') == 'error'
    text = json.dumps(_jsonable(body), ensure_ascii=False)
    return {
        'content': [{'type': 'text', 'text': text}],
        'isError': is_error,
    }


def _handle_message(message):
    """处理单条 JSON-RPC 消息，返回响应 dict（通知返回 None）。"""
    if not isinstance(message, dict):
        return {'jsonrpc': '2.0', 'id': None,
                'error': {'code': -32600, 'message': 'Invalid Request'}}

    method = message.get('method')
    msg_id = message.get('id')
    params = message.get('params') or {}

    # 通知（无 id）：按协议不返回内容
    if msg_id is None:
        return None

    if method == 'initialize':
        result = {
            'protocolVersion': _PROTOCOL_VERSION,
            'capabilities': {'tools': {}},
            'serverInfo': _SERVER_INFO,
        }
    elif method == 'tools/list':
        result = _mcp_tools_list()
    elif method == 'tools/call':
        result = _mcp_tool_call(params.get('name'), params.get('arguments') or {})
    elif method == 'ping':
        result = {}
    else:
        return {'jsonrpc': '2.0', 'id': msg_id,
                'error': {'code': -32601, 'message': f'Method not found: {method}'}}

    return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}


def _json_response(payload, status=200):
    return Response(json.dumps(payload, ensure_ascii=False), status=status, mimetype='application/json')


@mcp_bp.route('/api/agent/mcp', methods=['POST'])
def mcp_endpoint():
    data = request.get_json(silent=True)

    if data is None:
        return _json_response(
            {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}, 400)

    # 单条消息
    if isinstance(data, dict):
        response = _handle_message(data)
        if response is None:
            return Response('', status=202)  # 通知，无内容
        return _json_response(response)

    # 批处理（数组）
    if isinstance(data, list):
        responses = [r for r in (_handle_message(m) for m in data) if r is not None]
        if not responses:
            return Response('', status=202)
        return _json_response(responses)

    return _json_response(
        {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}, 400)


@mcp_bp.route('/api/agent/mcp', methods=['GET'])
def mcp_info():
    """便于浏览器直接打开确认可达性。"""
    return _json_response({
        'transport': 'streamable-http',
        'protocol': 'json-rpc 2.0',
        'protocolVersion': _PROTOCOL_VERSION,
        'server': _SERVER_INFO,
        'endpoint': '/api/agent/mcp',
        'methods': 'POST',
    })
