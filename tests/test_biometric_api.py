"""多模态 Web API 冒烟测试（Flask test_client，不依赖 MySQL/摄像头）。"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
import zipfile

import cv2
import numpy as np
from flask import Flask

from tests.synthetic import fingerprint_image
from web_admin.biometric_api import create_biometric_blueprint


class _Config:
    def get_web_admin_config(self):
        return {'token': 'test-token'}

    def get_section(self, name):
        return {}

    def get_encryption_key(self):
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()


class BiometricApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caos_api_')
        os.makedirs(os.path.join(self.tmp, 'dd'), exist_ok=True)
        os.environ['CAOS_ALLOW_UNSIGNED_PLUGINS'] = 'true'
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.app.register_blueprint(create_biometric_blueprint(_Config(), self.tmp))
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['user'] = 'admin'

    def tearDown(self):
        os.environ.pop('CAOS_ALLOW_UNSIGNED_PLUGINS', None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _png(self, seed=0):
        img = fingerprint_image(seed)
        ok, buf = cv2.imencode('.png', img)
        self.assertTrue(ok)
        return buf.tobytes()

    def test_health_and_modalities(self):
        r = self.client.get('/api/biometrics/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['status'], 'ok')
        r = self.client.get('/api/biometrics/modalities')
        self.assertEqual(r.status_code, 200)
        names = [m['name'] for m in r.get_json()['data']]
        self.assertEqual(len(names), 9)

    def test_enroll_and_verify_fingerprint(self):
        data = {'subject': 'api-test', 'modality': 'fingerprint',
                'file': (io.BytesIO(self._png(1)), 'fp.png')}
        r = self.client.post('/api/biometrics/enroll', data=data,
                             content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()['data']['ok'])
        versions = self.client.get(
            '/api/biometrics/captures/versions?subject=api-test&modality=fingerprint&device_id=WEB'
        )
        self.assertEqual(versions.status_code, 200)
        self.assertEqual(len(versions.get_json()['data']), 1)
        image = self.client.get(
            '/api/biometrics/captures/image?subject=api-test&modality=fingerprint&device_id=WEB'
        )
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.data, self._png(1))

        data = {'modality': 'fingerprint',
                'file': (io.BytesIO(self._png(1)), 'fp.png')}
        r = self.client.post('/api/biometrics/verify', data=data,
                             content_type='multipart/form-data')
        body = r.get_json()
        self.assertEqual(r.status_code, 200, body)
        self.assertTrue(body['data']['passed'])
        self.assertEqual(body['data']['match']['subject'], 'api-test')

    def test_token_auth_without_session(self):
        client = self.app.test_client()
        r = client.get('/api/biometrics/health',
                       headers={'Authorization': 'Bearer test-token'})
        self.assertEqual(r.status_code, 200)
        r = client.get('/api/biometrics/health')
        self.assertEqual(r.status_code, 401)

    def test_face_modality_rejected(self):
        r = self.client.post('/api/biometrics/enroll',
                             data={'subject': 'x', 'modality': 'face'})
        self.assertEqual(r.status_code, 409)

    def test_consent_grant_and_withdraw_api(self):
        payload = {
            'subject': 'api-consent',
            'modality': 'iris',
            'consent_version': 'v1.0',
            'consent_hash': 'a' * 64,
        }
        r = self.client.post('/api/biometrics/consent/grant', json=payload)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()['data']['status'], 'granted')
        r = self.client.get(
            '/api/biometrics/consent/latest?subject=api-consent&modality=iris&device_id=WEB'
        )
        self.assertEqual(r.status_code, 200)
        payload['consent_hash'] = 'b' * 64
        r = self.client.post('/api/biometrics/consent/withdraw', json=payload)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['data']['status'], 'withdrawn')
    def test_plugin_install_and_enable_api(self):
        plugin_toml = '''
schema_version = "1.0"
plugin_id = "caos.demo.face"
name = "演示人脸插件"
version = "1.0.0"
vendor = "demo"
modalities = ["face"]
platforms = ["windows-x64"]
adapter_class = "adapter.DemoAdapter"
capabilities = ["detect", "extract"]
permissions = ["camera"]
'''
        adapter_py = '''
from biometrics.adapters import VendorAdapter
class DemoAdapter(VendorAdapter):
    def __init__(self, config):
        super().__init__("face", "demo", config)
    def check_available(self):
        return True, "ok"
    def extract(self, sample):
        raise RuntimeError("test")
'''
        fh = io.BytesIO()
        with zipfile.ZipFile(fh, 'w') as zf:
            zf.writestr('plugin.toml', plugin_toml)
            zf.writestr('adapter.py', adapter_py)
        r = self.client.post(
            '/api/biometrics/plugins/install',
            data={'plugin': (io.BytesIO(fh.getvalue()), 'plugin.zip')},
            content_type='multipart/form-data',
        )
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        r = self.client.post('/api/biometrics/plugins/enable',
                             json={'plugin_id': 'caos.demo.face'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()['data']['enabled'])

    def test_template_import_api(self):
        npy = io.BytesIO()
        np.save(npy, np.ones(6, dtype=np.float32))
        template_toml = '''
subject = "导入测试"
modality = "iris"
device_id = "WEB"
backend = "sdk"
quality = 0.81
raw_file = "raw/sample.jpg"
raw_mime = "image/jpeg"
[arrays.embedding]
file = "arrays/embedding.npy"
'''
        fh = io.BytesIO()
        with zipfile.ZipFile(fh, 'w') as zf:
            zf.writestr('template.toml', template_toml)
            zf.writestr('arrays/embedding.npy', npy.getvalue())
            zf.writestr('raw/sample.jpg', b'iris-raw')
        r = self.client.post(
            '/api/biometrics/templates/import',
            data={'template': (io.BytesIO(fh.getvalue()), 'template.zip')},
            content_type='multipart/form-data',
        )
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()['data']['raw_saved'])

    def test_aliyun_catalog_and_mock_flow(self):
        r = self.client.get('/api/biometrics/cloud-vendors/catalog')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        routes = [item['route'] for item in r.get_json()['data']['aliyun']]
        self.assertEqual(routes, ['facebody', 'imm', 'cloudauth', 'android_aar'])
        for route in routes:
            rr = self.client.post('/api/biometrics/cloud-vendors/aliyun/mock',
                                  json={'route': route})
            self.assertEqual(rr.status_code, 200, rr.get_data(as_text=True))
            data = rr.get_json()['data']
            self.assertGreaterEqual(data['same_score'], 0.9)
            self.assertLess(data['different_score'], 0.5)
            self.assertTrue(data['liveness']['passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
