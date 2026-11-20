"""加密原始采集样本与模板版本库测试。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from biometrics import BioSample, CaptureRepository, build_biometric_registry
from tests.synthetic import palmprint_image


class CaptureRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caos_capture_')
        self.repo = CaptureRepository(
            os.path.join(self.tmp, 'captures.db'), allow_plaintext=True
        )
        self.engine = build_biometric_registry().resolve('palmprint')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _capture(self, seed):
        image = palmprint_image(seed)
        sample = BioSample.image(image)
        template = self.engine.extract(sample)
        ok, encoded = __import__('cv2').imencode('.jpg', image)
        self.assertTrue(ok)
        return encoded.tobytes(), template

    def test_first_second_rollback_and_reenroll(self):
        image1, template1 = self._capture(1)
        first = self.repo.save_capture('张三', 'palmprint', image1, template1)
        self.assertEqual(first.version, 1)
        self.assertTrue(first.active)
        self.assertIsNone(self.repo.get_version('张三', 'palmprint', 'admin', 0))
        self.assertEqual(self.repo.active_version('张三', 'palmprint', 'admin').digest,
                         template1.digest())

        image2, template2 = self._capture(2)
        second = self.repo.save_capture('张三', 'palmprint', image2, template2)
        self.assertEqual(second.version, 1)
        versions = self.repo.list_versions('张三', 'palmprint', 'admin')
        self.assertEqual([v.version for v in versions], [0, 1])
        self.assertEqual(versions[0].digest, template1.digest())
        self.assertEqual(versions[1].digest, template2.digest())
        self.assertEqual(versions[0].image_bytes, image1)
        self.assertEqual(versions[1].image_bytes, image2)

        rolled_back = self.repo.rollback('张三', 'palmprint', 'admin')
        self.assertEqual(rolled_back.version, 0)
        self.assertEqual(self.repo.active_version('张三', 'palmprint', 'admin').digest,
                         template1.digest())
        self.assertEqual(len(self.repo.list_versions('张三', 'palmprint', 'admin')), 2)

        image3, template3 = self._capture(3)
        self.repo.save_capture('张三', 'palmprint', image3, template3)
        versions = self.repo.list_versions('张三', 'palmprint', 'admin')
        self.assertEqual([v.version for v in versions], [0, 1])
        self.assertEqual(versions[0].digest, template1.digest())
        self.assertEqual(versions[1].digest, template3.digest())
        self.assertEqual(self.repo.active_version('张三', 'palmprint', 'admin').digest,
                         template3.digest())

    def test_plaintext_rejected_by_default(self):
        with self.assertRaises(RuntimeError):
            CaptureRepository(os.path.join(self.tmp, 'secure.db'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
