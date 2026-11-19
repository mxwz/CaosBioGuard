"""手机端 / 微信小程序聚合 API。

只做「读多写少」的移动端场景：概览、考勤记录、设备、个人模板、注册申请。
写操作复用 ``/api/biometrics``，避免移动端重复实现特征提取。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, session

from biometrics import BioTemplateStore, build_biometric_registry

_LOCK = threading.RLock()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def create_mobile_blueprint(config_manager, db_manager, base_dir: str,
                            url_prefix: str = '/api/mobile') -> Blueprint:
    bp = Blueprint('mobile_api', __name__, url_prefix=url_prefix)
    base = Path(base_dir)
    store = BioTemplateStore(str(base / 'dd' / 'biometrics.db'), config_manager=config_manager)
    registry = build_biometric_registry(config_manager=config_manager)
    requests_path = base / 'dd' / 'mobile_enroll_requests.json'

    def _web_token() -> str:
        try:
            return str((config_manager.get_web_admin_config() or {}).get('token') or '')
        except Exception:
            return ''

    def _provided_token() -> str:
        auth = request.headers.get('Authorization', '')
        if auth:
            return auth.replace('Bearer ', '').strip()
        return request.headers.get('X-Auth-Token', '').strip()

    def _role() -> Optional[str]:
        if session.get('logged_in'):
            return 'admin'
        token = _web_token()
        if token and _provided_token() == token:
            return 'admin'
        if request.headers.get('X-Mobile-Subject') or request.args.get('subject'):
            return 'user'
        return None

    def _guard():
        if not _role():
            return jsonify({'status': 'error', 'error': 'unauthorized'}), 401
        return None

    def _subject(role: str) -> str:
        if role == 'admin':
            return (request.args.get('subject') or request.headers.get('X-Mobile-Subject') or '').strip()
        return (request.args.get('subject') or request.headers.get('X-Mobile-Subject') or '').strip()

    def _read_requests() -> List[Dict[str, Any]]:
        with _LOCK:
            if not requests_path.exists():
                return []
            try:
                return json.loads(requests_path.read_text(encoding='utf-8'))
            except Exception:
                return []

    def _write_requests(items: List[Dict[str, Any]]) -> None:
        with _LOCK:
            requests_path.parent.mkdir(parents=True, exist_ok=True)
            requests_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')

    @bp.get('/version')
    def version():
        return jsonify({'status': 'ok', 'data': {'version': '0.2.0', 'api': 'v1'}})

    @bp.get('/modalities')
    def modalities():
        """公开模态清单：移动端登录前即可渲染采集表单。"""
        return jsonify({'status': 'ok', 'data': registry.specs(with_availability=True)})

    @bp.post('/login')
    def login():
        payload = request.get_json(silent=True) or request.form
        token = str(payload.get('token') or _provided_token())
        subject = str(payload.get('subject') or '').strip()
        if token and token == _web_token():
            session['logged_in'] = True
            session['user'] = 'admin'
            return jsonify({'status': 'ok', 'data': {'role': 'admin', 'subject': 'admin'}})
        if subject:
            # 轻量身份：移动端用户以工号/姓名进入，仅能查看自己的记录与模板
            return jsonify({'status': 'ok', 'data': {'role': 'user', 'subject': subject}})
        return jsonify({'status': 'error', 'error': '缺少 token 或 subject'}), 401

    @bp.get('/overview')
    def overview():
        guard = _guard()
        if guard:
            return guard
        try:
            stats = db_manager.get_statistics()
        except Exception:
            stats = {}
        try:
            devices = db_manager.get_all_devices()
        except Exception:
            devices = []
        try:
            local = db_manager.get_local_device_info()
        except Exception:
            local = {}
        try:
            bio = store.stats()
        except Exception:
            bio = {}
        try:
            recent = db_manager.get_attendance_records(limit=8)
        except Exception:
            recent = []
        try:
            today_rows = db_manager.get_attendance_records(limit=500)
        except Exception:
            today_rows = []
        today = datetime.now().strftime('%Y-%m-%d')
        today_count = sum(1 for r in today_rows if str(_record(r).get('timestamp') or '').startswith(today))
        return jsonify({'status': 'ok', 'data': _json_safe({
            'stats': stats,
            'today_attendance': today_count,
            'devices': devices,
            'local_device': local,
            'biometrics': bio,
            'recent': [_record(r) for r in recent],
            'requests': len(_read_requests()),
        })})

    def _record(row) -> Dict[str, Any]:
        keys = ('id', 'user_name', 'timestamp', 'status', 'remark', 'device_id', 'sync_status', 'sync_timestamp')
        if isinstance(row, dict):
            return {k: row.get(k) for k in keys}
        return {k: (row[i] if i < len(row) else None) for i, k in enumerate(keys)}

    @bp.get('/records')
    def records():
        guard = _guard()
        if guard:
            return guard
        role = _role()
        subject = _subject(role)
        if role != 'admin' and not subject:
            return jsonify({'status': 'error', 'error': '缺少 subject'}), 400
        limit = min(max(int(request.args.get('limit', 50)), 1), 200)
        offset = max(int(request.args.get('offset', 0)), 0)
        try:
            rows = db_manager.get_attendance_records(
                limit=limit, offset=offset,
                start_date=request.args.get('start_date') or None,
                end_date=request.args.get('end_date') or None,
                search=subject,
                device_id=request.args.get('device_id') or '',
            )
        except Exception as exc:
            return jsonify({'status': 'error', 'error': f'查询失败: {exc}'}), 500
        return jsonify({'status': 'ok', 'data': [_record(r) for r in rows]})

    @bp.get('/devices')
    def devices():
        guard = _guard()
        if guard:
            return guard
        try:
            items = db_manager.get_all_devices()
            local = db_manager.get_local_device_info()
        except Exception as exc:
            return jsonify({'status': 'error', 'error': str(exc)}), 500
        return jsonify({'status': 'ok', 'data': _json_safe({'cloud': items, 'local': local})})

    @bp.get('/profile')
    def profile():
        guard = _guard()
        if guard:
            return guard
        subject = _subject(_role())
        if not subject:
            return jsonify({'status': 'error', 'error': '缺少 subject'}), 400
        modalities = store.modalities_of(subject)
        templates = []
        for m in modalities:
            t = store.load(subject, m)
            if t is not None:
                templates.append({
                    'modality': m, 'quality': round(float(t.quality), 3),
                    'created_at': datetime.fromtimestamp(t.created_at).strftime('%Y-%m-%d %H:%M:%S'),
                    'template_bytes': len(t.encode()),
                })
        try:
            rows = db_manager.get_attendance_records(limit=10, search=subject)
        except Exception:
            rows = []
        return jsonify({'status': 'ok', 'data': {
            'subject': subject, 'modalities': modalities, 'templates': templates,
            'recent': [_record(r) for r in rows],
        }})

    @bp.post('/enroll-request')
    def enroll_request():
        guard = _guard()
        if guard:
            return guard
        payload = request.get_json(silent=True) or request.form
        subject = str(payload.get('subject') or '').strip()
        modality = str(payload.get('modality') or '').strip()
        note = str(payload.get('note') or '').strip()
        if not subject or not modality:
            return jsonify({'status': 'error', 'error': '缺少 subject 或 modality'}), 400
        item = {'id': datetime.now().strftime('%Y%m%d%H%M%S%f'), 'subject': subject,
                'modality': modality, 'note': note,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'pending'}
        items = _read_requests()
        items.append(item)
        _write_requests(items[-500:])
        return jsonify({'status': 'ok', 'data': item})

    @bp.get('/enroll-requests')
    def list_requests():
        guard = _guard()
        if guard:
            return guard
        if _role() != 'admin':
            return jsonify({'status': 'error', 'error': 'forbidden'}), 403
        return jsonify({'status': 'ok', 'data': _read_requests()})

    @bp.post('/enroll-requests/<req_id>/approve')
    def approve_request(req_id: str):
        guard = _guard()
        if guard:
            return guard
        if _role() != 'admin':
            return jsonify({'status': 'error', 'error': 'forbidden'}), 403
        items = _read_requests()
        for item in items:
            if item.get('id') == req_id:
                item['status'] = 'approved'
                item['approved_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                _write_requests(items)
                return jsonify({'status': 'ok', 'data': item})
        return jsonify({'status': 'error', 'error': 'request not found'}), 404

    @bp.after_request
    def cors(response):
        origin = request.headers.get('Origin', '')
        allowed = ''
        try:
            allowed = str((config_manager.get_section('WebAdmin') or {}).get('cors_origins') or '')
        except Exception:
            pass
        if allowed and origin and (allowed.strip() == '*' or origin in [o.strip() for o in allowed.split(',')]):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, X-Auth-Token, X-Mobile-Subject'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
            response.headers['Vary'] = 'Origin'
        return response

    return bp
