"""多生物特征 Web API（Flask Blueprint）。

供 Web 后台、手机 PWA、微信小程序共用：
- 模态清单 / 可用性
- 模板注册（图片 / WAV / 视频 / 签名轨迹）
- 1:N 验证
- 主体与统计

鉴权：管理员 session，或 ``Authorization: Bearer <WebAdmin token>``。
人脸模态仍由既有 ``/faces`` 体系管理，这里明确返回 409，避免双写。
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
from flask import Blueprint, jsonify, request, session

from biometrics import (BioSample, BioTemplateStore, BiometricService,
                        build_biometric_registry)
from biometrics.engines.audio_utils import read_wav

FACE_MODALITIES = {'face'}


def create_biometric_blueprint(config_manager, base_dir: str, url_prefix: str = '/api/biometrics') -> Blueprint:
    bp = Blueprint('biometric_api', __name__, url_prefix=url_prefix)
    base = Path(base_dir)
    store = BioTemplateStore(str(base / 'dd' / 'biometrics.db'), config_manager=config_manager)
    registry = build_biometric_registry(config_manager=config_manager)
    service = BiometricService(registry, store, config_manager=config_manager)

    def _token_ok() -> bool:
        if session.get('logged_in'):
            return True
        try:
            web = config_manager.get_web_admin_config() or {}
        except Exception:
            web = {}
        token = str(web.get('token') or '')
        auth = request.headers.get('Authorization', '')
        provided = auth.replace('Bearer ', '').strip() if auth else request.headers.get('X-Auth-Token', '')
        return bool(token and provided == token)

    def _guard():
        if not _token_ok():
            return jsonify({'status': 'error', 'error': 'unauthorized'}), 401
        return None

    def _err(message: str, code: int = 400):
        return jsonify({'status': 'error', 'error': message}), code

    def _decode_image(payload: Dict[str, Any]) -> Optional[np.ndarray]:
        import cv2
        raw = None
        f = request.files.get('file')
        if f is not None and f.filename:
            raw = f.read()
        if raw is None:
            b64 = payload.get('image_base64') or payload.get('image')
            if b64:
                if ',' in b64 and b64.strip().startswith('data:'):
                    b64 = b64.split(',', 1)[1]
                raw = base64.b64decode(b64)
        if not raw:
            return None
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        return img

    def _decode_audio(payload: Dict[str, Any]) -> Optional[BioSample]:
        f = request.files.get('file')
        raw = f.read() if (f is not None and f.filename) else None
        if raw is None:
            b64 = payload.get('audio_base64') or payload.get('audio')
            if b64:
                if ',' in b64 and b64.strip().startswith('data:'):
                    b64 = b64.split(',', 1)[1]
                raw = base64.b64decode(b64)
        if not raw:
            return None
        wav, sr = read_wav(raw)
        return BioSample.audio(wav, sr)

    def _decode_frames(payload: Dict[str, Any]) -> Optional[BioSample]:
        import cv2
        frames = []
        raw_list = payload.get('frames_base64') or []
        for b64 in raw_list:
            if ',' in b64 and b64.strip().startswith('data:'):
                b64 = b64.split(',', 1)[1]
            img = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                frames.append(img)
        if frames:
            return BioSample.frames(frames)
        f = request.files.get('file')
        if f is not None and f.filename:
            suffix = Path(f.filename).suffix or '.mp4'
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                f.save(tmp.name)
                cap = cv2.VideoCapture(tmp.name)
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                picks = np.linspace(0, max(total - 1, 0), min(36, max(total, 1))).astype(int) if total else []
                for idx in picks:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        frames.append(frame)
                if total == 0:
                    while len(frames) < 36:
                        ok, frame = cap.read()
                        if not ok:
                            break
                        frames.append(frame)
                cap.release()
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
        return BioSample.frames(frames) if frames else None

    def _decode_strokes(payload: Dict[str, Any]) -> Optional[BioSample]:
        import cv2
        strokes = payload.get('strokes')
        if isinstance(strokes, str):
            try:
                strokes = json.loads(strokes)
            except Exception:
                return None
        if not strokes:
            return None
        image = None
        b64 = payload.get('image_base64')
        if b64:
            if ',' in b64 and b64.strip().startswith('data:'):
                b64 = b64.split(',', 1)[1]
            image = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_GRAYSCALE)
        return BioSample.strokes(strokes, image=image)

    def _build_sample(modality: str, payload: Dict[str, Any]) -> Optional[BioSample]:
        if modality == 'voiceprint':
            return _decode_audio(payload)
        if modality == 'gait':
            return _decode_frames(payload)
        if modality == 'signature':
            return _decode_strokes(payload)
        img = _decode_image(payload)
        return BioSample.image(img) if img is not None else None

    def _payload() -> Dict[str, Any]:
        data = request.get_json(silent=True) if request.is_json else None
        if isinstance(data, dict):
            return data
        return {k: v for k, v in request.form.items()}

    @bp.get('/health')
    def health():
        guard = _guard()
        if guard:
            return guard
        available = 0
        try:
            available = len(registry.available_names())
        except Exception:
            pass
        return jsonify({'status': 'ok', 'data': {
            'engines': len(registry.specs(with_availability=False)),
            'available': available,
            'store': store.stats(),
            'version': '0.2.0',
        }})

    @bp.get('/modalities')
    def modalities():
        guard = _guard()
        if guard:
            return guard
        return jsonify({'status': 'ok', 'data': registry.specs(with_availability=True)})

    @bp.get('/subjects')
    def subjects():
        guard = _guard()
        if guard:
            return guard
        names = store.subjects()
        return jsonify({'status': 'ok', 'data': [
            {'subject': n, 'modalities': store.modalities_of(n)} for n in names
        ]})

    @bp.delete('/subjects/<path:subject>')
    def delete_subject(subject: str):
        guard = _guard()
        if guard:
            return guard
        count = store.delete(subject)
        return jsonify({'status': 'ok', 'data': {'deleted': count}})

    @bp.get('/stats')
    def stats():
        guard = _guard()
        if guard:
            return guard
        return jsonify({'status': 'ok', 'data': store.stats()})

    @bp.post('/quality')
    def quality():
        guard = _guard()
        if guard:
            return guard
        payload = _payload()
        modality = str(payload.get('modality') or '').strip()
        if modality in FACE_MODALITIES:
            return _err('人脸质量由 /faces 体系评估', 409)
        if modality not in {s['name'] for s in registry.specs(with_availability=False)}:
            return _err(f'未知模态: {modality}')
        sample = _build_sample(modality, payload)
        if sample is None:
            return _err('缺少可解析的样本')
        try:
            report = registry.resolve(modality).quality(sample)
        except Exception as exc:
            return _err(f'质量评估失败: {exc}')
        return jsonify({'status': 'ok', 'data': report.to_dict()})

    @bp.post('/enroll')
    def enroll():
        guard = _guard()
        if guard:
            return guard
        payload = _payload()
        subject = str(payload.get('subject') or '').strip()
        modality = str(payload.get('modality') or '').strip()
        if not subject:
            return _err('缺少 subject')
        if modality in FACE_MODALITIES:
            return _err('人脸请在 Web「人脸管理」或边缘端注册', 409)
        if modality not in {s['name'] for s in registry.specs(with_availability=False)}:
            return _err(f'未知模态: {modality}')
        sample = _build_sample(modality, payload)
        if sample is None:
            return _err('缺少可解析的样本')
        device_id = str(payload.get('device_id') or 'WEB')
        try:
            result = service.enroll(subject, modality, [sample], device_id=device_id,
                                    min_samples=1, min_quality=float(payload.get('min_quality') or 0.45),
                                    use_liveness=False)
        except Exception as exc:
            return _err(f'注册失败: {exc}', 500)
        code = 200 if result.ok else 422
        return jsonify({'status': 'ok' if result.ok else 'error', 'data': result.to_dict()}), code

    @bp.post('/verify')
    def verify():
        guard = _guard()
        if guard:
            return guard
        payload = _payload()
        modality = str(payload.get('modality') or '').strip()
        if modality in FACE_MODALITIES:
            return _err('人脸 1:N 请使用现有 /face_compare 接口', 409)
        if modality not in {s['name'] for s in registry.specs(with_availability=False)}:
            return _err(f'未知模态: {modality}')
        sample = _build_sample(modality, payload)
        if sample is None:
            return _err('缺少可解析的样本')
        device_id = str(payload.get('device_id') or 'WEB')
        try:
            out = service.verify_1n(modality, sample, device_id=device_id,
                                    threshold=float(payload['threshold']) if payload.get('threshold') else None,
                                    require_liveness=False)
        except Exception as exc:
            return _err(f'验证失败: {exc}', 500)
        return jsonify({'status': 'ok', 'data': out})

    @bp.after_request
    def cors(response):
        try:
            origins = str((config_manager.get_section('WebAdmin') or {}).get('cors_origins') or '')
        except Exception:
            origins = ''
        origin = request.headers.get('Origin', '')
        if origins and origin and (origins.strip() == '*' or origin in [o.strip() for o in origins.split(',')]):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, X-Auth-Token'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
            response.headers['Vary'] = 'Origin'
        return response

    return bp
