"""阿里云人脸相关云端与 Android AAR 适配器。

覆盖四条不同产品线：

1. ``facebody``：VIAPI Facebody ``CompareFace``，通用云端人脸 1:1 比对；
2. ``imm``：IMM 2020-09-30 ``CompareImageFaces``，配合 OSS URI 使用；
3. ``cloudauth``：金融级实人认证，包含实人、活体、工单和风控流程；
4. ``android_aar``：Android 端侧 AAR，Python 服务端只做桥接契约和 mock，真实调用发生在 App 原生层。

阿里云 SDK 为可选依赖：未安装 SDK 或未提供密钥时，可通过 ``mock=true`` 跑通最小链路。
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..types import BioSample, BioTemplate, LivenessReport, QualityReport
from .base import VendorAdapter

ALIYUN_VENDOR = 'aliyun'
VALID_ALIYUN_ROUTES = {'facebody', 'imm', 'cloudauth', 'android_aar'}

REDACTED_KEYS = ('secret', 'token', 'key', 'password', 'credential')
ENV_AK_NAMES = ('ALIBABA_CLOUD_ACCESS_KEY_ID', 'AccessKeyId')
ENV_SK_NAMES = ('ALIBABA_CLOUD_ACCESS_KEY_SECRET', 'AccessKeySecret')


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def env_first(names: Tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ''


def redact_config(config: Dict[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for key, value in config.items():
        if any(mark in key.lower() for mark in REDACTED_KEYS):
            output[key] = '***redacted***' if value else ''
        else:
            output[key] = value
    return output


def encode_image(sample: BioSample) -> bytes:
    if sample.kind != 'image':
        raise TypeError('阿里云人脸适配器需要 image 类型样本')
    image = np.asarray(sample.data)
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    import cv2

    ok, buffer = cv2.imencode('.jpg', image)
    if not ok:
        raise RuntimeError('样本图像编码为 JPEG 失败')
    return buffer.tobytes()


def sample_hash(sample: BioSample) -> str:
    if sample.kind == 'image':
        raw = encode_image(sample)
    elif sample.meta.get('image_url'):
        raw = str(sample.meta['image_url']).encode('utf-8')
    elif sample.meta.get('oss_uri'):
        raw = str(sample.meta['oss_uri']).encode('utf-8')
    else:
        raw = repr(sample.data).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


class AliyunBaseAdapter(VendorAdapter):
    route = 'facebody'

    def __init__(self, modality: str = 'face', vendor: str = ALIYUN_VENDOR,
                 config: Optional[Dict[str, Any]] = None):
        super().__init__(modality, vendor, config)
        self.mock = as_bool(
            self.config.get('mock', self.config.get('dry_run')),
            default=as_bool(os.environ.get('CAOS_ALIYUN_MOCK'), default=False),
        )
        self._client: Any = None

    @property
    def access_key_id(self) -> str:
        return str(self.config.get('access_key_id') or env_first(ENV_AK_NAMES))

    @property
    def access_key_secret(self) -> str:
        return str(self.config.get('access_key_secret') or env_first(ENV_SK_NAMES))

    @property
    def region_id(self) -> str:
        return str(self.config.get('region_id') or self.config.get('region') or 'cn-shanghai')

    @property
    def endpoint(self) -> str:
        if self.config.get('endpoint'):
            return str(self.config['endpoint'])
        return f'{self.route}.{self.region_id}.aliyuncs.com'

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.access_key_id or not self.access_key_secret:
            raise RuntimeError('缺少阿里云 AccessKey ID/Secret；无密钥阶段可设置 mock=true')
        openapi_models = importlib.import_module('alibabacloud_tea_openapi.models')
        config = openapi_models.Config(
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
            region_id=self.region_id,
            endpoint=self.endpoint,
        )
        client_module = importlib.import_module(self._client_module)
        self._client = client_module.Client(config)
        return self._client

    @property
    def _client_module(self) -> str:
        return f'alibabacloud_{self.route}20191230.client'

    def check_available(self) -> Tuple[bool, str]:
        if self.mock:
            return True, 'mock 模式：无需阿里云密钥和 SDK'
        try:
            self._build_client()
            return True, ''
        except Exception as exc:
            return False, str(exc)

    def quality(self, sample: BioSample) -> Optional[QualityReport]:
        if self.mock:
            return QualityReport(0.91, True, {'mock': 1.0}, [])
        return None

    def _reference_template(self, sample: BioSample) -> BioTemplate:
        digest = sample_hash(sample)
        meta = {
            'backend': 'sdk',
            'vendor': ALIYUN_VENDOR,
            'route': self.route,
            'reference_hash': digest,
            'mock': self.mock,
        }
        for key in ('image_url', 'oss_uri', 'source_path', 'certify_id', 'subject'):
            if sample.meta.get(key):
                meta[key] = str(sample.meta[key])
        return BioTemplate(
            modality=self.modality,
            arrays={'reference_hash': np.frombuffer(bytes.fromhex(digest), dtype=np.uint8)},
            meta=meta,
            quality=float(sample.meta.get('quality', 0.91 if self.mock else 0.0)),
        )

    def extract(self, sample: BioSample) -> BioTemplate:
        return self._reference_template(sample)

    def compare(self, probe: BioTemplate, gallery: BioTemplate) -> Optional[float]:
        if self.mock:
            if probe.meta.get('reference_hash') == gallery.meta.get('reference_hash'):
                return 0.96
            return 0.42
        try:
            return float(self._real_compare(probe, gallery))
        except Exception as exc:
            raise RuntimeError(f'阿里云 {self.route} 调用失败: {exc}') from exc

    def liveness(self, sample: BioSample) -> Optional[LivenessReport]:
        if self.mock:
            return LivenessReport(
                True, 0.92, mode='active',
                reasons=[f'{self.route} mock 活体通过'],
            )
        return None

    def _real_compare(self, probe: BioTemplate, gallery: BioTemplate) -> float:
        raise NotImplementedError

    @staticmethod
    def _meta_value(template: BioTemplate, key: str) -> str:
        return str(template.meta.get(key) or '')

    @staticmethod
    def _read_file(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode('ascii')

    def describe(self) -> Dict[str, Any]:
        return {
            'modality': self.modality,
            'vendor': self.vendor,
            'route': self.route,
            'mock': self.mock,
            'config': redact_config(self.config),
        }


class AliyunFacebodyAdapter(AliyunBaseAdapter):
    """VIAPI Facebody 1:1 人脸比对。"""

    route = 'facebody'

    @property
    def endpoint(self) -> str:
        if self.config.get('endpoint'):
            return str(self.config['endpoint'])
        return f'facebody.{self.region_id}.aliyuncs.com'

    def _real_compare(self, probe: BioTemplate, gallery: BioTemplate) -> float:
        sdk = importlib.import_module('alibabacloud_facebody20191230')
        util = importlib.import_module('alibabacloud_tea_util.models')
        client = self._build_client()
        kwargs: Dict[str, Any] = {}

        url_a = self._meta_value(probe, 'image_url')
        url_b = self._meta_value(gallery, 'image_url')
        if url_a and url_b:
            kwargs['image_urla'] = url_a
            kwargs['image_urlb'] = url_b
        else:
            path_a = self._meta_value(probe, 'source_path')
            path_b = self._meta_value(gallery, 'source_path')
            if path_a and path_b:
                kwargs['image_data_a'] = self._read_file(path_a)
                kwargs['image_data_b'] = self._read_file(path_b)
            else:
                raise RuntimeError('Facebody CompareFace 需要 image_url 或本地 source_path')

        request = sdk.models.CompareFaceRequest(**kwargs)
        response = client.compare_face_with_options(request, util.RuntimeOptions())
        confidence = float(response.body.data.confidence)
        return max(0.0, min(1.0, confidence / 100.0))


class AliyunIMMAdapter(AliyunBaseAdapter):
    """IMM 人脸相似度比对，输入必须是同地域 OSS URI。"""

    route = 'imm'

    @property
    def region_id(self) -> str:
        return str(self.config.get('region_id') or self.config.get('region') or 'cn-beijing')

    @property
    def endpoint(self) -> str:
        if self.config.get('endpoint'):
            return str(self.config['endpoint'])
        return f'imm.{self.region_id}.aliyuncs.com'

    @property
    def _client_module(self) -> str:
        return 'alibabacloud_imm20200930.client'

    def _real_compare(self, probe: BioTemplate, gallery: BioTemplate) -> float:
        sdk = importlib.import_module('alibabacloud_imm20200930')
        util = importlib.import_module('alibabacloud_tea_util.models')
        uri1 = self._meta_value(probe, 'oss_uri')
        uri2 = self._meta_value(gallery, 'oss_uri')
        if not uri1 or not uri2:
            raise RuntimeError('IMM CompareImageFaces 需要两张图片的 oss_uri；本地图片需先上传 OSS')
        project_name = str(self.config.get('project_name') or '').strip()
        if not project_name:
            raise RuntimeError('IMM 适配器缺少 project_name')
        source = sdk.models.CompareImageFacesRequestSource(uri1=uri1, uri2=uri2)
        request = sdk.models.CompareImageFacesRequest(
            project_name=project_name, source=source,
        )
        client = self._build_client()
        response = client.compare_image_faces_with_options(request, util.RuntimeOptions())
        return float(response.body.similarity)


class AliyunCloudAuthAdapter(AliyunBaseAdapter):
    """金融级实人认证服务端适配器。"""

    route = 'cloudauth'

    @property
    def endpoint(self) -> str:
        if self.config.get('endpoint'):
            return str(self.config['endpoint'])
        return f'cloudauth.{self.region_id}.aliyuncs.com'

    @property
    def _client_module(self) -> str:
        return 'alibabacloud_cloudauth20190307.client'

    def _request_kwargs(self, sample: Optional[BioTemplate] = None) -> Dict[str, Any]:
        scene_id = self.config.get('scene_id')
        if scene_id is None:
            raise RuntimeError('CloudAuth 缺少 scene_id')
        kwargs: Dict[str, Any] = {
            'scene_id': int(scene_id),
            'outer_order_no': str(self.config.get('outer_order_no') or uuid.uuid4()),
            'product_code': str(self.config.get('product_code') or 'ID_MIN'),
            'model': str(self.config.get('model') or 'NO_LIVENESS'),
            'cert_type': str(self.config.get('cert_type') or 'IDENTITY_CARD'),
            'cert_name': str(self.config.get('cert_name') or ''),
            'cert_no': str(self.config.get('cert_no') or ''),
        }
        if sample is not None:
            image_url = self._meta_value(sample, 'image_url')
            if image_url:
                kwargs['face_contrast_picture_url'] = image_url
            elif self._meta_value(sample, 'source_path'):
                kwargs['face_contrast_picture'] = self._read_file(
                    self._meta_value(sample, 'source_path')
                )
            elif self._meta_value(sample, 'certify_id'):
                kwargs['certify_id'] = self._meta_value(sample, 'certify_id')
        return {k: v for k, v in kwargs.items() if v != ''}

    def _real_compare(self, probe: BioTemplate, gallery: BioTemplate) -> float:
        sdk = importlib.import_module('alibabacloud_cloudauth20190307')
        util = importlib.import_module('alibabacloud_tea_util.models')
        request = sdk.models.ContrastFaceVerifyRequest(**self._request_kwargs(probe))
        client = self._build_client()
        response = client.contrast_face_verify_with_options(request, util.RuntimeOptions())
        body = response.body
        if str(body.code) != '200':
            raise RuntimeError(f'CloudAuth 拒绝: {body.code} {body.message}')
        result = body.result_object
        return 1.0 if result is not None and as_bool(getattr(result, 'passed', False)) else 0.0

    def init_face_verify(self, meta_info: str, return_url: str = '') -> Dict[str, Any]:
        sdk = importlib.import_module('alibabacloud_cloudauth20190307')
        util = importlib.import_module('alibabacloud_tea_util.models')
        kwargs = self._request_kwargs()
        kwargs['meta_info'] = meta_info
        if return_url:
            kwargs['return_url'] = return_url
        request = sdk.models.InitFaceVerifyRequest(**kwargs)
        client = self._build_client()
        response = client.init_face_verify_with_options(request, util.RuntimeOptions())
        result = response.body.result_object
        return {
            'certify_id': getattr(result, 'certify_id', ''),
            'certify_url': getattr(result, 'certify_url', ''),
        }

    def describe_face_verify(self, certify_id: str) -> Dict[str, Any]:
        sdk = importlib.import_module('alibabacloud_cloudauth20190307')
        util = importlib.import_module('alibabacloud_tea_util.models')
        request = sdk.models.DescribeFaceVerifyRequest(
            scene_id=int(self.config['scene_id']),
            certify_id=certify_id,
        )
        client = self._build_client()
        response = client.describe_face_verify_with_options(request, util.RuntimeOptions())
        result = response.body.result_object
        return {
            'passed': getattr(result, 'passed', False),
            'sub_code': getattr(result, 'sub_code', ''),
            'certify_id': certify_id,
        }

    def contrast_face_verify(self) -> Dict[str, Any]:
        sdk = importlib.import_module('alibabacloud_cloudauth20190307')
        util = importlib.import_module('alibabacloud_tea_util.models')
        request = sdk.models.ContrastFaceVerifyRequest(**self._request_kwargs())
        client = self._build_client()
        response = client.contrast_face_verify_with_options(request, util.RuntimeOptions())
        result = response.body.result_object
        return {
            'code': response.body.code,
            'message': response.body.message,
            'passed': getattr(result, 'passed', False),
            'certify_id': getattr(result, 'certify_id', ''),
        }


class AliyunAndroidAARAdapter(AliyunBaseAdapter):
    """阿里云 Android AAR 端侧 SDK 的服务端占位与桥接契约。"""

    route = 'android_aar'

    @property
    def aar_dir(self) -> Path:
        return Path(self.config.get('aar_dir') or 'mobile/capacitor/android/app/libs')

    def check_available(self) -> Tuple[bool, str]:
        if self.mock:
            return True, 'mock 模式：Android AAR 原生链路由本地 mock 代替'
        bridge_ready = as_bool(self.config.get('native_bridge_ready'))
        if not bridge_ready:
            return False, 'Android AAR 不能由 Python 直接加载；需先实现 Capacitor 原生插件并设置 native_bridge_ready'
        if not self.aar_dir.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            aar_dir = project_root / self.aar_dir
        else:
            aar_dir = self.aar_dir
        if not aar_dir.is_dir() or not list(aar_dir.glob('*.aar')):
            return False, f'AAR 目录不存在或没有 .aar 文件: {aar_dir}'
        return True, '原生桥接已配置，真实活体和认证结果需真机验收'

    def _real_compare(self, probe: BioTemplate, gallery: BioTemplate) -> float:
        raise RuntimeError('AAR 比对必须由 Android 原生插件执行，服务端仅接收认证回调')

    def liveness(self, sample: BioSample) -> Optional[LivenessReport]:
        if self.mock:
            return LivenessReport(True, 0.9, mode='active', reasons=['Android AAR mock 活体通过'])
        return None


def build_aliyun_adapter(route: str = 'facebody',
                         config: Optional[Dict[str, Any]] = None) -> AliyunBaseAdapter:
    route = str(route or 'facebody').strip().lower()
    if route not in VALID_ALIYUN_ROUTES:
        raise ValueError(f'未知阿里云路线: {route}；可选: {sorted(VALID_ALIYUN_ROUTES)}')
    mapping = {
        'facebody': AliyunFacebodyAdapter,
        'imm': AliyunIMMAdapter,
        'cloudauth': AliyunCloudAuthAdapter,
        'android_aar': AliyunAndroidAARAdapter,
    }
    return mapping[route](config=config)
