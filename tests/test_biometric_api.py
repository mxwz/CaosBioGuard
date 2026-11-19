"""多模态 Web API 冒烟测试（Flask test_client，不依赖 MySQL/摄像头）。"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest

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
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.app.register_blueprint(create_biometric_blueprint(_Config(), self.tmp))
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['user'] = 'admin'

    def tearDown(self):
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
