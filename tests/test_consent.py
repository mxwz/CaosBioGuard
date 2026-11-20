import os
import tempfile
import unittest

from biometrics import ConsentRepository


class ConsentRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caos_consent_')
        self.repo = ConsentRepository(os.path.join(self.tmp, 'consent.db'))

    def test_grant_latest_and_withdraw(self):
        granted = self.repo.grant(
            '张三', 'fingerprint', 'v1.0', 'a' * 64,
            device_id='edge-01', source_ip='127.0.0.1'
        )
        self.assertEqual(granted.status, 'granted')
        self.assertEqual(len(granted.record_hash), 64)
        latest = self.repo.latest('张三', 'fingerprint', 'edge-01')
        self.assertEqual(latest.id, granted.id)

        withdrawn = self.repo.withdraw(
            '张三', 'fingerprint', 'v1.0', 'b' * 64, device_id='edge-01'
        )
        self.assertEqual(withdrawn.status, 'withdrawn')
        latest = self.repo.latest('张三', 'fingerprint', 'edge-01')
        self.assertEqual(latest.id, withdrawn.id)
        history = self.repo.list_for('张三', 'edge-01')
        self.assertEqual([item.status for item in history], ['withdrawn', 'granted'])

    def test_invalid_grant(self):
        with self.assertRaises(ValueError):
            self.repo.grant('张三', 'fingerprint', '', 'hash')


if __name__ == '__main__':
    unittest.main()
