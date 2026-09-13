"""Agent 工具层（平台无关）。

以独立 Flask Blueprint 形式复用云端单例（db_manager / config_manager / face_store），
对外暴露统一端点：
  GET  /api/agent/tools   工具清单（JSON Schema，供 Dify / n8n / Coze 导入）
  GET  /api/agent/health  健康检查
  POST /api/agent/call    统一工具执行 {tool, arguments}

读写分离：
  - 读工具直接放行；
  - 写工具 requires_confirmation=True，未带 _confirmed 标记时返回 pending_confirmation，
    需编排层二次确认后再次调用。

新增工具只需两步（改完重启进程即自动生效，OpenAPI/MCP 清单实时生成，无需手动上传）：
  1) 在下方 TOOLS 列表追加一条元数据（name/description/parameters；写工具加 requires_confirmation=True）；
  2) 实现 handler 函数，并注册进 _HANDLERS 映射。

  示例（读工具）：
    def _query_foo(args):
        return {'total': 0, 'items': []}

    TOOLS.append({
        'name': 'query_foo',
        'description': '查询 foo 数据。',
        'requires_confirmation': False,
        'parameters': {'type': 'object', 'properties': {}},
    })
    _HANDLERS['query_foo'] = _query_foo

  （可选）在 _TOOL_DISPLAY / _TOOL_TAGS 补中文名与标签，仅影响注册中心展示。
"""
import logging
from datetime import datetime, date

from flask import Blueprint, request, jsonify

from registry.base import Registry

logger = logging.getLogger(__name__)

agent_bp = Blueprint('agent', __name__)

# 注入的云端单例（由 web_admin/app.py 调用 init_agent_tools 注入）
_db_manager = None
_config_manager = None
_face_store = None


def init_agent_tools(db_manager, config_manager, face_store):
    """注入云端单例，必须在注册 Blueprint 前调用。"""
    global _db_manager, _config_manager, _face_store
    _db_manager = db_manager
    _config_manager = config_manager
    _face_store = face_store


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------

_ATTENDANCE_COLS = ['id', 'user_name', 'timestamp', 'status', 'remark', 'device_id', 'sync_status', 'sync_timestamp']
_ACCESS_COLS = ['id', 'user_name', 'timestamp', 'direction', 'status', 'remark', 'device_id', 'sync_status', 'sync_timestamp']
_SYSTEM_LOG_COLS = ['id', 'level', 'message', 'timestamp', 'module', 'device_id', 'sync_status', 'sync_timestamp']
_ADMIN_LOG_COLS = ['id', 'admin_name', 'action', 'target', 'details', 'sensitivity', 'timestamp', 'device_id', 'sync_status', 'sync_timestamp']


def _jsonable(obj):
    """把 datetime/date/bytes 转成 JSON 可序列化类型。"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def _rows_to_dicts(rows, columns):
    """把 records 查询返回的元组列表转成 dict 列表。"""
    return [_jsonable(dict(zip(columns, r))) for r in rows]


def _mask(value):
    """脱敏敏感字段，避免把密钥/密码喂给 LLM。"""
    if not value:
        return ''
    if len(value) <= 4:
        return '****'
    return value[:2] + '****' + value[-2:]


# ---------------------------------------------------------------------------
# 工具执行函数（读工具）
# ---------------------------------------------------------------------------

def _health_check(args):
    mysql_ok = False
    try:
        conn = _db_manager.get_mysql_connection()
        mysql_ok = conn is not None
        if conn:
            conn.close()
    except Exception:
        mysql_ok = False

    s3 = _config_manager.get_s3_config()
    s3_configured = bool(s3.get('access_key') and '<' not in s3.get('access_key', '') and s3.get('secret_key'))

    return {
        'service': 'ok',
        'cloud_enabled': _config_manager.get_cloud_enabled(),
        'mysql_connectable': mysql_ok,
        's3_configured': s3_configured,
        'face_store': type(_face_store).__name__ if _face_store else None,
    }


def _query_attendance(args):
    rows = _db_manager.get_attendance_records(
        limit=args.get('limit', 100),
        offset=args.get('offset', 0),
        start_date=args.get('start_date'),
        end_date=args.get('end_date'),
        search=args.get('search', ''),
        device_id=args.get('device_id', ''),
    )
    return {'total': len(rows), 'records': _rows_to_dicts(rows, _ATTENDANCE_COLS)}


def _query_access(args):
    rows = _db_manager.get_access_records(
        limit=args.get('limit', 100),
        offset=args.get('offset', 0),
        start_date=args.get('start_date'),
        end_date=args.get('end_date'),
        search=args.get('search', ''),
        status=args.get('status', ''),
        device_id=args.get('device_id', ''),
    )
    return {'total': len(rows), 'records': _rows_to_dicts(rows, _ACCESS_COLS)}


def _query_statistics(args):
    stats = _db_manager.get_statistics(
        start_date=args.get('start_date'),
        end_date=args.get('end_date'),
        device_id=args.get('device_id'),
    )
    return _jsonable(stats)


def _query_devices(args):
    devices = _db_manager.get_all_devices()
    return {'total': len(devices), 'devices': _jsonable(devices)}


def _query_device_details(args):
    device_id = args.get('device_id')
    if not device_id:
        raise ValueError('缺少 device_id 参数')
    return _jsonable(_db_manager.get_device_details(device_id))


def _query_system_logs(args):
    rows = _db_manager.get_system_logs(
        limit=args.get('limit', 100),
        offset=args.get('offset', 0),
        device_id=args.get('device_id', ''),
    )
    return {'total': len(rows), 'records': _rows_to_dicts(rows, _SYSTEM_LOG_COLS)}


def _query_admin_logs(args):
    rows = _db_manager.get_admin_logs(
        limit=args.get('limit', 100),
        offset=args.get('offset', 0),
        start_date=args.get('start_date'),
        end_date=args.get('end_date'),
        search=args.get('search', ''),
        device_id=args.get('device_id', ''),
    )
    return {'total': len(rows), 'records': _rows_to_dicts(rows, _ADMIN_LOG_COLS)}


def _list_faces(args):
    device_id = args.get('device_id') or None
    meta = _face_store.get_meta(device_id) if _face_store else []
    return {'total': len(meta), 'faces': _jsonable(meta)}


def _get_config(args):
    mysql = _config_manager.get_mysql_config()
    s3 = _config_manager.get_s3_config()
    web = _config_manager.get_web_admin_config()

    data = {
        'mode': _config_manager.get_mode(),
        'network_mode': _config_manager.get_network_mode(),
        'start_mode': _config_manager.get_start_mode(),
        'sync_interval': _config_manager.get_sync_interval(),
        'cloud_enabled': _config_manager.get_cloud_enabled(),
        'mysql': {
            'host': mysql['host'],
            'user': mysql['user'],
            'database': mysql['database'],
            'port': mysql['port'],
            'password': _mask(mysql['password']),
        },
        's3': {
            'endpoint': s3['endpoint'],
            'bucket': s3['bucket'],
            'region': s3['region'],
            'access_key': _mask(s3['access_key']),
            'secret_key': _mask(s3['secret_key']),
        },
        'web_admin': {
            'host': web['host'],
            'port': web['port'],
            'token': _mask(web['token']),
            'salt': _mask(web['salt']),
        },
    }

    section = args.get('section')
    if section:
        return {section: data.get(section)}
    return data


# 写工具（P3 实现，先返回明确占位）
def _planned(args):
    raise NotImplementedError('该写工具规划于后续阶段（P3）实现')


# ---------------------------------------------------------------------------
# 工具元数据（JSON Schema）
# ---------------------------------------------------------------------------

TOOLS = [
    {
        'name': 'health_check',
        'description': '检查云端服务健康状态：MySQL 连通性、对象存储（R2）是否已配置、当前人脸存储后端。',
        'requires_confirmation': False,
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'query_attendance',
        'description': '查询考勤记录，支持按时间范围、设备、姓名关键字过滤。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {
                'start_date': {'type': 'string', 'description': '开始时间，格式 YYYY-MM-DD HH:MM:SS'},
                'end_date': {'type': 'string', 'description': '结束时间，格式 YYYY-MM-DD HH:MM:SS'},
                'device_id': {'type': 'string', 'description': '设备 ID，留空查全部'},
                'search': {'type': 'string', 'description': '姓名或备注关键字'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 100'},
                'offset': {'type': 'integer', 'description': '偏移量，默认 0'},
            },
        },
    },
    {
        'name': 'query_access',
        'description': '查询门禁通行记录，支持按时间、设备、通行状态（Allowed/Denied）过滤。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {
                'start_date': {'type': 'string', 'description': '开始时间'},
                'end_date': {'type': 'string', 'description': '结束时间'},
                'device_id': {'type': 'string', 'description': '设备 ID'},
                'search': {'type': 'string', 'description': '姓名或备注关键字'},
                'status': {'type': 'string', 'description': 'Allowed 或 Denied'},
                'limit': {'type': 'integer'},
                'offset': {'type': 'integer'},
            },
        },
    },
    {
        'name': 'query_statistics',
        'description': '查询考勤/门禁/系统聚合统计（用户总数、出勤趋势、通行放行/拒绝、错误日志数）。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {
                'start_date': {'type': 'string', 'description': '开始时间'},
                'end_date': {'type': 'string', 'description': '结束时间'},
                'device_id': {'type': 'string', 'description': '设备 ID，留空查全部'},
            },
        },
    },
    {
        'name': 'query_devices',
        'description': '查询所有已注册设备及在线状态。',
        'requires_confirmation': False,
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'query_device_details',
        'description': '查询单个设备的详细信息。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {'device_id': {'type': 'string', 'description': '设备 ID'}},
            'required': ['device_id'],
        },
    },
    {
        'name': 'query_system_logs',
        'description': '查询系统日志，可按设备过滤。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {
                'device_id': {'type': 'string'},
                'limit': {'type': 'integer'},
                'offset': {'type': 'integer'},
            },
        },
    },
    {
        'name': 'query_admin_logs',
        'description': '查询管理员操作审计日志。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {
                'start_date': {'type': 'string'},
                'end_date': {'type': 'string'},
                'search': {'type': 'string'},
                'device_id': {'type': 'string'},
                'limit': {'type': 'integer'},
                'offset': {'type': 'integer'},
            },
        },
    },
    {
        'name': 'list_faces',
        'description': '查询人脸库元数据清单（姓名、设备、更新时间），不返回特征向量。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {'device_id': {'type': 'string', 'description': '设备 ID，留空查全部'}},
        },
    },
    {
        'name': 'get_config',
        'description': '读取系统配置（敏感字段已脱敏），可选按 section 过滤：mode/network_mode/start_mode/sync_interval/cloud_enabled/mysql/s3/web_admin。',
        'requires_confirmation': False,
        'parameters': {
            'type': 'object',
            'properties': {'section': {'type': 'string', 'description': '配置分组名，留空返回全部'}},
        },
    },
    {
        'name': 'add_face',
        'description': '新增人脸（按设备）。高风险写操作，需二次确认。',
        'requires_confirmation': True,
        'confirm_hint': '将新增人脸，请确认姓名与目标设备无误',
        'parameters': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': '姓名'},
                'image': {'type': 'string', 'description': '人脸底图（base64）'},
                'groups': {'type': 'string', 'description': '分组，默认 all'},
                'list_type': {'type': 'string', 'description': '名单类型 white/black，默认 white'},
                'device_id': {'type': 'string', 'description': '设备 ID，默认 admin'},
            },
            'required': ['name', 'image'],
        },
    },
    {
        'name': 'delete_face',
        'description': '删除人脸（按姓名和设备）。高风险写操作，需二次确认。',
        'requires_confirmation': True,
        'confirm_hint': '将删除人脸，该操作不可恢复，请确认',
        'parameters': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'device_id': {'type': 'string', 'description': '设备 ID，留空删除该姓名所有设备'},
            },
            'required': ['name'],
        },
    },
    {
        'name': 'set_config',
        'description': '修改系统配置。高风险写操作，需二次确认。',
        'requires_confirmation': True,
        'confirm_hint': '将修改配置，请确认 section/key/value 无误',
        'parameters': {
            'type': 'object',
            'properties': {
                'section': {'type': 'string'},
                'key': {'type': 'string'},
                'value': {'type': 'string'},
            },
            'required': ['section', 'key', 'value'],
        },
    },
    {
        'name': 'trigger_sync',
        'description': '立即触发一次数据同步。',
        'requires_confirmation': True,
        'confirm_hint': '将触发数据同步',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'trigger_reconcile',
        'description': '触发云端人脸库对账。',
        'requires_confirmation': True,
        'confirm_hint': '将触发人脸库对账',
        'parameters': {
            'type': 'object',
            'properties': {'device_id': {'type': 'string', 'description': '设备 ID，留空对账全部'}},
        },
    },
]

# 中文名与标签：仅用于注册中心展示（name 保持不变，供 OpenAPI/分发使用）
_TOOL_DISPLAY = {
    'health_check': '服务健康检查',
    'query_attendance': '考勤记录查询',
    'query_access': '门禁记录查询',
    'query_statistics': '数据统计查询',
    'query_devices': '设备列表查询',
    'query_device_details': '设备详情查询',
    'query_system_logs': '系统日志查询',
    'query_admin_logs': '管理日志查询',
    'list_faces': '人脸库查询',
    'get_config': '配置读取',
    'add_face': '新增人脸',
    'delete_face': '删除人脸',
    'set_config': '修改配置',
    'trigger_sync': '触发同步',
    'trigger_reconcile': '触发对账',
}

_TOOL_TAGS = {
    'health_check': ['健康', '诊断'],
    'query_attendance': ['考勤'],
    'query_access': ['门禁'],
    'query_statistics': ['统计'],
    'query_devices': ['设备'],
    'query_device_details': ['设备'],
    'query_system_logs': ['日志'],
    'query_admin_logs': ['日志', '审计'],
    'list_faces': ['人脸'],
    'get_config': ['配置'],
    'add_face': ['人脸', '写操作'],
    'delete_face': ['人脸', '写操作'],
    'set_config': ['配置', '写操作'],
    'trigger_sync': ['同步', '写操作'],
    'trigger_reconcile': ['对账', '写操作'],
}

for _t in TOOLS:
    _t['display_name'] = _TOOL_DISPLAY.get(_t['name'], _t['name'])
    _t['tags'] = list(_TOOL_TAGS.get(_t['name'], []))

_HANDLERS = {
    'health_check': _health_check,
    'query_attendance': _query_attendance,
    'query_access': _query_access,
    'query_statistics': _query_statistics,
    'query_devices': _query_devices,
    'query_device_details': _query_device_details,
    'query_system_logs': _query_system_logs,
    'query_admin_logs': _query_admin_logs,
    'list_faces': _list_faces,
    'get_config': _get_config,
    # 写工具（P3 实现）
    'add_face': _planned,
    'delete_face': _planned,
    'set_config': _planned,
    'trigger_sync': _planned,
    'trigger_reconcile': _planned,
}

_TOOL_BY_NAME = {t['name']: t for t in TOOLS}


# ---------------------------------------------------------------------------
# 分发与路由
# ---------------------------------------------------------------------------

def _coerce_args(meta, args):
    """把 GET query 传入的字符串参数按 schema 转成对应类型（主要是 integer）。"""
    props = meta.get('parameters', {}).get('properties', {})
    result = dict(args)
    for key, val in list(result.items()):
        prop = props.get(key) or {}
        if prop.get('type') == 'integer':
            try:
                result[key] = int(val)
            except (TypeError, ValueError):
                pass
    return result


def _dispatch(tool, args):
    """统一工具分发：返回 (json_dict, status_code)。"""
    meta = _TOOL_BY_NAME.get(tool)
    if not meta:
        return {'status': 'error', 'error': f'unknown tool: {tool}'}, 404

    args = _coerce_args(meta, args)

    # 二次确认骨架：写工具未带 _confirmed 标记时返回 pending，由编排层确认后再次调用
    if meta.get('requires_confirmation') and not args.get('_confirmed'):
        return {
            'status': 'pending_confirmation',
            'tool': tool,
            'arguments': args,
            'message': meta.get('confirm_hint', '该操作需要二次确认'),
        }, 200

    handler = _HANDLERS.get(tool)
    if handler is None:
        return {'status': 'error', 'error': f'tool {tool} 未实现'}, 501

    try:
        result = handler(args)
        return {'status': 'ok', 'tool': tool, 'result': _jsonable(result)}, 200
    except NotImplementedError as e:
        return {'status': 'error', 'tool': tool, 'error': str(e)}, 501
    except Exception as e:
        logger.exception('agent tool %s failed', tool)
        return {'status': 'error', 'tool': tool, 'error': str(e)}, 500


@agent_bp.route('/api/agent/tools', methods=['GET'])
def agent_list_tools():
    return jsonify({'tools': TOOLS})


@agent_bp.route('/api/agent/health', methods=['GET'])
def agent_health():
    return jsonify(_health_check({}))


@agent_bp.route('/api/agent/call', methods=['POST'])
def agent_call():
    data = request.get_json(silent=True) or {}
    tool = data.get('tool')
    args = data.get('arguments') or {}
    body, code = _dispatch(tool, args)
    return jsonify(body), code


def _make_tool_endpoint(tool_name):
    """为单个工具生成独立端点（供 OpenAPI / n8n / Coze 按工具调用）。

    同时支持 GET（query 参数）与 POST（JSON body），以兼容 Dify 自定义工具
    对 GET + query parameters 的导入偏好。
    """
    def endpoint():
        if request.method == 'GET':
            args = request.args.to_dict()
        else:
            data = request.get_json(silent=True) or {}
            args = data.get('arguments') if isinstance(data, dict) and 'arguments' in data else data
        body, code = _dispatch(tool_name, args)
        return jsonify(body), code
    endpoint.__name__ = f'agent_tool_{tool_name}'
    return endpoint


for _tool in TOOLS:
    _name = _tool['name']
    agent_bp.add_url_rule(
        f'/api/agent/tools/{_name}',
        f'agent_tool_{_name}',
        _make_tool_endpoint(_name),
        methods=['GET', 'POST'],
    )


def _openapi_parameters(params):
    """把工具 parameters（JSON Schema）转成 OpenAPI query 参数数组（GET 风格）。"""
    properties = params.get('properties', {})
    required = set(params.get('required', []))
    result = []
    for name, prop in properties.items():
        item = {
            'name': name,
            'in': 'query',
            'required': name in required,
            'schema': {
                'type': prop.get('type', 'string'),
            },
            'description': prop.get('description', ''),
        }
        result.append(item)
    return result


def build_openapi_spec(base_url=''):
    """生成 OpenAPI 3.1 规范，供 Dify「自定义工具」直接导入。

    Dify 自定义工具更偏好 GET + query parameters（而非 POST + requestBody），
    故此处将每个工具暴露为 GET 端点，参数全部放在 query string。
    """
    paths = {}
    for tool in TOOLS:
        name = tool['name']
        paths[f'/api/agent/tools/{name}'] = {
            'get': {
                'summary': tool['description'],
                'operationId': name,
                'parameters': _openapi_parameters(tool['parameters']),
                'responses': {
                    '200': {
                        'description': '执行结果',
                        'content': {
                            'application/json': {
                                'schema': {'type': 'object'}
                            }
                        },
                    },
                },
            },
        }

    return {
        'openapi': '3.1.0',
        'info': {
            'title': 'CaosBioGuard Agent Tools',
            'description': '门禁考勤系统云端工具集（考勤/门禁/设备/日志/人脸库/配置/健康检查）',
            'version': '1.0.0',
        },
        'servers': [{'url': base_url}],
        'paths': paths,
        'components': {'schemas': {}},
    }


@agent_bp.route('/api/agent/openapi.json', methods=['GET'])
def agent_openapi():
    # 经 Cloudflare Tunnel 转发时，用 X-Forwarded-Proto / CF-Visitor 识别真实协议，
    # 避免 servers.url 写成 http，导致 Dify 调 POST 工具时被 301 改写成 GET。
    proto = request.scheme
    if request.headers.get('X-Forwarded-Proto', '').lower() == 'https' \
            or 'https' in request.headers.get('CF-Visitor', '').lower():
        proto = 'https'
    base_url = f"{proto}://{request.host}"
    return jsonify(build_openapi_spec(base_url=base_url))


# ---------------------------------------------------------------------------
# Agent 工具注册器（供注册中心统一管理）
# ---------------------------------------------------------------------------

class ToolRegistry(Registry):
    """Agent 工具注册器：登记全部工具（内置 + 自定义），按名分发。"""

    name = 'agent_tools'
    label = 'Agent 工具'
    custom_plugin_package = 'custom_plugins.agent_tools'

    def schema_list(self):
        """返回工具 JSON Schema 清单（供 Dify 等编排层导入）。"""
        return TOOLS

    def dispatch(self, name, args):
        # 内置工具复用统一分发
        if name in _TOOL_BY_NAME:
            body, code = _dispatch(name, args)
            return body, code
        # 自定义工具：INFO.entry 为可调用对象，约定签名 fn(args) -> dict
        info = self._items.get(name)
        if info and callable(info.entry):
            try:
                result = info.entry(args or {})
                return {'status': 'ok', 'tool': name, 'result': _jsonable(result)}, 200
            except Exception as e:
                logger.exception('custom tool %s failed', name)
                return {'status': 'error', 'tool': name, 'error': str(e)}, 500
        return {'status': 'error', 'error': f'unknown tool: {name}'}, 404


def build_tool_registry():
    """基于既有 TOOLS 元数据构建工具注册器，并发现自定义工具插件。"""
    registry = ToolRegistry()
    for meta in TOOLS:
        registry.register(meta, name=meta['name'])
    registry.discover()
    return registry

