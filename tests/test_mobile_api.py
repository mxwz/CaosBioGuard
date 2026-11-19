"""手机端聚合 API 冒烟测试。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime

from flask import Flask

from web_admin.mobile_api import create_mobile_blueprint


class _Config:
    def get_web_admin_config(self):
        return {'token': 'mobile-token'}

    def get_section(self, name):
        if name == 'UserPins':
            return {'张三': '1234'}
        return {}

    def get_encryption_key(self):
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()


class _DB:
    def get_statistics(self):
        return {'user': {'total': 3}, 'attendance': {}, 'access': {}, 'system': {}}

    def get_all_devices(self):
        return [{'device_id': 'edge-1', 'is_online': True, 'last_seen': '2026-11-18 10:00:00'}]

    def get_local_device_info(self):
        return {'device_id': 'local-1', 'ip': '127.0.0.1'}

    def get_attendance_records(self, limit=100, offset=0, start_date=None,
                                end_date=None, search='', device_id=''):
        today = datetime.now().strftime('%Y-%m-%d')
        return [(1, search or '张三', f'{today} 09:01:00', '正常', '', 'edge-1', 'synced', None)]

    def get_all_names(self):
        return ['张三']


class MobileApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caos_mobile_')
        os.makedirs(os.path.join(self.tmp, 'dd'), exist_ok=True)
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.app.register_blueprint(create_mobile_blueprint(_Config(), _DB(), self.tmp))
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_login_and_overview(self):
        r = self.client.post('/api/mobile/login', json={'token': 'mobile-token'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['data']['role'], 'admin')
        r = self.client.get('/api/mobile/overview',
                            headers={'Authorization': 'Bearer mobile-token'})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()['data']
        self.assertEqual(d['stats']['user']['total'], 3)
        self.assertEqual(d['today_attendance'], 1)

    def test_user_records(self):
        r = self.client.post('/api/mobile/login',
                             json={'subject': '张三', 'pin': '1234'})
        self.assertEqual(r.status_code, 200)
        token = r.get_json()['data']['token']
        r = self.client.get('/api/mobile/records',
                            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()['data']), 1)

    def test_enroll_request(self):
        r = self.client.post('/api/mobile/login',
                             json={'subject': '张三', 'pin': '1234'})
        token = r.get_json()['data']['token']
        r = self.client.post('/api/mobile/enroll-request',
                             json={'modality': 'voiceprint'},
                             headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/api/mobile/enroll-requests',
                            headers={'Authorization': 'Bearer mobile-token'})
        self.assertEqual(len(r.get_json()['data']), 1)

    def test_modalities_public(self):
        r = self.client.get('/api/mobile/modalities')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()['data']), 9)


if __name__ == '__main__':
    unittest.main(verbosity=2)
