"""部署模式解析与校验测试。"""

from __future__ import annotations

import unittest

from deployment import DeploymentProfile


class DictConfig:
    def __init__(self, sections):
        self._sections = sections

    def get_section(self, section):
        return dict(self._sections.get(section, {}))


def base_sections(**overrides):
    sections = {
        'General': {'mode': 'standalone', 'networkmode': 'offline'},
        'Deployment': {'operation_mode': 'offline', 'network_scope': 'lan', 'topology': 'integrated'},
        'WebAdmin': {'protocol': 'http', 'host': '0.0.0.0', 'port': '6100', 'token': '', 'salt': ''},
        'Cloud': {'enabled': 'false'},
        'Sync': {'endpoint': '', 'secret': ''},
    }
    sections.update(overrides)
    return sections


class DeploymentTests(unittest.TestCase):
    def test_offline_integrated_profile(self):
        profile = DeploymentProfile.from_config(DictConfig(base_sections()))
        self.assertTrue(profile.ok)
        self.assertEqual(profile.operation_mode, 'offline')
        self.assertEqual(profile.network_scope, 'lan')
        self.assertEqual(profile.topology, 'integrated')
        self.assertIn('offline_identify', profile.capabilities)

    def test_public_separated_profile(self):
        sections = base_sections(
            General={'networkmode': 'online'},
            Deployment={'operation_mode': 'online', 'network_scope': 'public', 'topology': 'separated',
                        'public_base_url': 'https://guard.example.com'},
            WebAdmin={'protocol': 'https', 'token': 'strong-token', 'salt': 'salt', 'cors_origins': 'https://app.example.com'},
            Cloud={'enabled': 'true'},
            Sync={'endpoint': 'https://guard.example.com/api/sync/events', 'secret': 'hmac-secret'},
        )
        profile = DeploymentProfile.from_config(DictConfig(sections))
        self.assertTrue(profile.ok, profile.errors)
        self.assertIn('cloud_authority', profile.capabilities)
        self.assertIn('tls', profile.capabilities)

    def test_public_requires_https_and_sync_secret(self):
        sections = base_sections(
            General={'networkmode': 'online'},
            Deployment={'operation_mode': 'online', 'network_scope': 'public', 'topology': 'separated'},
            WebAdmin={'protocol': 'http', 'token': 'strong-token', 'salt': 'salt'},
            Cloud={'enabled': 'true'},
            Sync={'endpoint': 'http://guard.example.com/api/sync', 'secret': ''},
        )
        profile = DeploymentProfile.from_config(DictConfig(sections))
        self.assertFalse(profile.ok)
        messages = '\n'.join(profile.errors)
        self.assertIn('https', messages)
        self.assertIn('public_base_url', messages)
        self.assertIn('secret', messages)

    def test_backward_compatible_cloud_flag(self):
        sections = {
            'General': {},
            'WebAdmin': {'protocol': 'http', 'token': '', 'salt': ''},
            'Cloud': {'enabled': 'true'},
            'Sync': {'endpoint': 'https://cloud.example.com/sync', 'secret': 'secret'},
        }
        profile = DeploymentProfile.from_config(DictConfig(sections))
        self.assertTrue(profile.ok, profile.errors)
        self.assertEqual(profile.operation_mode, 'online')
        self.assertEqual(profile.network_scope, 'lan')
        self.assertEqual(profile.topology, 'separated')


if __name__ == '__main__':
    unittest.main(verbosity=2)
