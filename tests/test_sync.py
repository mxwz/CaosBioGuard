"""云边同步 outbox / HMAC / 退避测试。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest

from biometrics.sync import (SyncClient, SyncConfig, SyncOutbox, canonical_json,
                             sign_payload, verify_signature)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caos_sync_')
        self.outbox = SyncOutbox(os.path.join(self.tmp, 'outbox.db'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enqueue_deduplicates(self):
        k1 = self.outbox.enqueue('attendance', {'user': '张三'}, key='k-1')
        k2 = self.outbox.enqueue('attendance', {'user': '张三'}, key='k-1')
        self.assertEqual(k1, k2)
        self.assertEqual(len(self.outbox.pending()), 1)

    def test_hmac_roundtrip(self):
        ts = int(time.time())
        body = canonical_json({'a': 1, 'b': '中文'})
        sig = sign_payload('secret', ts, body)
        self.assertTrue(verify_signature('secret', ts, body, sig))
        self.assertFalse(verify_signature('secret', ts, body, 'bad'))
        self.assertFalse(verify_signature('secret', ts - 600, body, sig))

    def test_flush_ack_and_signature(self):
        self.outbox.enqueue('attendance', {'user': '张三'}, key='k-1')
        captured = {}

        def transport(url, body, headers, timeout):
            captured.update({'url': url, 'body': body, 'headers': headers})
            env = json.loads(body)
            return {'accepted': [e['idempotency_key'] for e in env['events']], 'duplicates': []}

        cfg = SyncConfig(endpoint='https://cloud.example/api/sync/events', secret='s3cret',
                         device_id='edge-1', batch_size=10)
        out = SyncClient(cfg, self.outbox, transport).flush()
        self.assertEqual(out['acked'], 1)
        self.assertEqual(self.outbox.stats().get('acked'), 1)
        ts = int(captured['headers']['X-Caos-Timestamp'])
        self.assertTrue(verify_signature('s3cret', ts, captured['body'],
                                         captured['headers']['X-Caos-Signature']))

    def test_failure_schedules_retry(self):
        self.outbox.enqueue('attendance', {'user': '李四'}, key='k-2')

        def transport(url, body, headers, timeout):
            raise RuntimeError('network down')

        cfg = SyncConfig(endpoint='https://cloud.example/x', secret='s', base_delay=1.0, max_attempts=3)
        out = SyncClient(cfg, self.outbox, transport).flush()
        self.assertEqual(out['failed'], 1)
        self.assertEqual(self.outbox.stats().get('retry'), 1)
        row = self.outbox.pending(now=time.time())
        self.assertEqual(len(row), 0)  # next_at 未到
        row = self.outbox.pending(now=time.time() + 30)
        self.assertEqual(len(row), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
