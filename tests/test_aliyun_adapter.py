"""阿里云四条产品线的无密钥 mock 与配置测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from biometrics import (BioSample, PluginManifest, VendorAdapterRegistry,
                        build_aliyun_adapter)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTES = ('facebody', 'imm', 'cloudauth', 'android_aar')


class AliyunMockAdapterTests(unittest.TestCase):
    def setUp(self):
        self.sample_a = BioSample.image(np.zeros((16, 16, 3), dtype=np.uint8))
        self.sample_b = BioSample.image(np.ones((16, 16, 3), dtype=np.uint8) * 255)

    def test_all_routes_mock_minimal_flow(self):
        for route in ROUTES:
            with self.subTest(route=route):
                adapter = build_aliyun_adapter(route, {'mock': True})
                ok, message = adapter.check_available()
                self.assertTrue(ok, message)
                quality = adapter.quality(self.sample_a)
                self.assertIsNotNone(quality)
                self.assertTrue(quality.passed)
                template_a = adapter.extract(self.sample_a)
                template_b = adapter.extract(self.sample_b)
                self.assertEqual(template_a.meta['route'], route)
                self.assertIn('reference_hash', template_a.arrays)
                self.assertGreaterEqual(adapter.compare(template_a, template_a), 0.9)
                self.assertLess(adapter.compare(template_a, template_b), 0.5)
                liveness = adapter.liveness(self.sample_a)
                self.assertIsNotNone(liveness)
                self.assertTrue(liveness.passed)

    def test_real_cloud_routes_require_credentials(self):
        with patch.dict('os.environ', {
            'ALIBABA_CLOUD_ACCESS_KEY_ID': '',
            'ALIBABA_CLOUD_ACCESS_KEY_SECRET': '',
            'AccessKeyId': '',
            'AccessKeySecret': '',
        }):
            for route in ('facebody', 'imm', 'cloudauth'):
                adapter = build_aliyun_adapter(route, {'mock': False})
                ok, message = adapter.check_available()
                self.assertFalse(ok)
                self.assertIn('AccessKey', message)

    def test_android_aar_requires_native_bridge(self):
        adapter = build_aliyun_adapter('android_aar', {'mock': False})
        ok, message = adapter.check_available()
        self.assertFalse(ok)
        self.assertIn('原生插件', message)
        with self.assertRaises(RuntimeError):
            adapter.compare(
                adapter.extract(self.sample_a),
                adapter.extract(self.sample_a),
            )

    def test_invalid_route_and_config_redaction(self):
        with self.assertRaises(ValueError):
            build_aliyun_adapter('unknown', {})
        adapter = build_aliyun_adapter('facebody', {
            'mock': True, 'access_key_secret': 'secret-value',
        })
        self.assertEqual(adapter.describe()['config']['access_key_secret'], '***redacted***')

    def test_plugin_manifests(self):
        for route in ROUTES:
            path = PROJECT_ROOT / 'plugins' / 'available' / f'aliyun_{route}' / 'plugin.toml'
            manifest = PluginManifest.load(path)
            self.assertEqual(manifest.vendor, 'aliyun')
            self.assertIn('face', manifest.modalities)

    def test_registry_from_config_selects_aliyun_route(self):
        class Config:
            def get_section(self, name):
                if name == 'BiometricBackends':
                    return {'default_policy': 'sdk', 'allow_fallback': 'true'}
                if name == 'VendorSDK.face':
                    return {
                        'enabled': 'true', 'vendor': 'aliyun',
                        'route': 'cloudauth', 'mock': 'true',
                    }
                return {}

        registry = VendorAdapterRegistry.from_config(Config(), ['face'])
        adapter = registry.get('face')
        self.assertEqual(adapter.route, 'cloudauth')
        self.assertTrue(adapter.check_available()[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
