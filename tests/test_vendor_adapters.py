"""模型/厂商 SDK 双后端测试。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import numpy as np

from biometrics import (BioSample, BioTemplate, BioTemplateStore, HybridEngine,
                        VendorAdapter, VendorAdapterRegistry, normalize_template)
from biometrics.base import ModalityEngine
from biometrics.types import LivenessReport, ModalitySpec, QualityReport


SPEC = ModalitySpec(
    name='fingerprint', label='指纹', kind='image',
    default_threshold=0.5, security_level=4,
)


class FakeModel(ModalityEngine):
    spec = SPEC

    def check_available(self):
        return True, ''

    def quality(self, sample):
        return QualityReport(0.8, True, {}, [])

    def extract(self, sample):
        return BioTemplate(
            modality='fingerprint',
            arrays={'embedding': np.ones((1, 4), dtype=np.float32)},
            meta={}, quality=0.8,
        )

    def compare(self, a, b):
        return 0.8


class FakeAdapter(VendorAdapter):
    def __init__(self, available=True):
        super().__init__('fingerprint', 'fake-vendor', {})
        self._available = available

    def check_available(self):
        return self._available, 'disabled' if not self._available else ''

    def extract(self, sample):
        return BioTemplate(
            modality='fingerprint',
            arrays={'vendor_template': np.frombuffer(b'abc', dtype=np.uint8)},
            meta={}, quality=0.9,
        )

    def compare(self, probe, gallery):
        return 0.7

    def liveness(self, sample):
        return LivenessReport(True, 0.95, mode='sdk', reasons=['SDK PAD'])


class DictConfig:
    def __init__(self, sections):
        self.sections = sections

    def get_section(self, section):
        return dict(self.sections.get(section, {}))


class HybridBackendTests(unittest.TestCase):
    def setUp(self):
        self.sample = BioSample('image', np.zeros((8, 8), dtype=np.uint8))

    def test_model_policy(self):
        engine = HybridEngine(FakeModel(), FakeAdapter(), policy='model')
        template = engine.extract(self.sample)
        self.assertEqual(template.meta['backend'], 'model')
        self.assertIn('embedding', template.arrays)

    def test_sdk_and_auto_policy(self):
        engine = HybridEngine(FakeModel(), FakeAdapter(), policy='sdk')
        template = engine.extract(self.sample)
        self.assertEqual(template.meta['backend'], 'sdk')
        self.assertEqual(template.meta['vendor'], 'fake-vendor')
        engine = HybridEngine(FakeModel(), FakeAdapter(), policy='auto')
        self.assertEqual(engine.extract(self.sample).meta['backend'], 'sdk')

    def test_sdk_failure_policy(self):
        adapter = FakeAdapter(available=False)
        engine = HybridEngine(FakeModel(), adapter, policy='sdk', allow_fallback=False)
        with self.assertRaises(RuntimeError):
            engine.extract(self.sample)
        engine = HybridEngine(FakeModel(), adapter, policy='sdk', allow_fallback=True)
        self.assertEqual(engine.extract(self.sample).meta['backend'], 'model')

    def test_fusion_compare(self):
        engine = HybridEngine(
            FakeModel(), FakeAdapter(), policy='fusion',
            fusion_weights={'model': 0.5, 'sdk': 0.5},
        )
        probe = BioTemplate('fingerprint', arrays={'x': np.ones(1)}, quality=0.8)
        score = engine.compare(probe, probe)
        self.assertAlmostEqual(score, 0.75)

    def test_normalize_bytes_template(self):
        template = normalize_template(b'abc', 'fingerprint', 0.7, {'vendor': 'x'})
        self.assertEqual(template.meta['backend'], 'sdk')
        self.assertEqual(bytes(template.arrays['vendor_template']), b'abc')

    def test_registry_from_config(self):
        config = DictConfig({
            'BiometricBackends': {'default_policy': 'sdk', 'allow_fallback': 'false'},
            'VendorSDK.fingerprint': {
                'enabled': 'true', 'vendor': 'example', 'mode': 'python',
                'python_class': 'vendor.Adapter',
            },
        })
        registry = VendorAdapterRegistry.from_config(config, ['fingerprint'])
        self.assertEqual(registry.policy_for('fingerprint'), 'sdk')
        self.assertFalse(registry.allow_fallback)
        self.assertIn('fingerprint', registry.adapters)


class StoreBackendCoexistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caos_backend_')
        self.store = BioTemplateStore(
            os.path.join(self.tmp, 'bio.db'), allow_plaintext=True
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_model_and_sdk_templates_coexist(self):
        model = BioTemplate(
            'fingerprint', arrays={'embedding': np.ones((1, 2), dtype=np.float32)},
            meta={'backend': 'model'}, quality=0.8,
        )
        sdk = BioTemplate(
            'fingerprint', arrays={'vendor_template': np.frombuffer(b'abc', dtype=np.uint8)},
            meta={'backend': 'sdk', 'vendor': 'fake'}, quality=0.9,
        )
        self.assertTrue(self.store.save('张三', model))
        self.assertTrue(self.store.save('张三', sdk))
        self.assertEqual(len(self.store.gallery('fingerprint')), 1)
        preferred = self.store.gallery('fingerprint')[0][1]
        self.assertEqual(preferred.meta['backend'], 'sdk')
        self.assertEqual(self.store.gallery('fingerprint', backend='model')[0][1].meta['backend'], 'model')
        self.assertIsNotNone(self.store.load('张三', 'fingerprint', backend='sdk'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
