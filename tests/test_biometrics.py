"""多生物特征核心包的回归测试（合成数据，无需采集硬件）。

覆盖：
- 8 个非人脸模态的质量/提取/比对链路，且「同源分数 > 异源分数」；
- 模板序列化、加密存储、1:N 检索；
- 分数融合四种规则与 FAR/FRR 评估；
- 活体门禁在「有模型/无模型 + strict/degraded」下的兼容行为。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import numpy as np

from biometrics import (BioSample, BioTemplate, BioTemplateStore, BiometricService,
                        FaceLivenessDetector, FacePadGate, FusionPolicy, LivenessPolicy,
                        build_biometric_registry, evaluate_thresholds, fuse)
from biometrics.types import MatchResult
from tests import synthetic


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = build_biometric_registry()

    def _pair(self, name, a, b, c):
        engine = self.registry.resolve(name)
        ta, tb, tc = engine.extract(a), engine.extract(b), engine.extract(c)
        same = engine.compare(ta, tb)
        diff = engine.compare(ta, tc)
        self.assertGreater(same, diff, f'{name}: 同源 {same:.3f} 应高于异源 {diff:.3f}')
        self.assertGreaterEqual(same, engine.threshold, f'{name}: 同源分数未过阈值 {engine.threshold}')
        self.assertLess(diff, engine.threshold, f'{name}: 异源分数误过阈值')
        return ta

    def test_iris(self):
        self._pair('iris', BioSample.image(synthetic.iris_image(1)),
                   BioSample.image(synthetic.iris_image(1, shift=(3, -2))),
                   BioSample.image(synthetic.iris_image(7)))

    def test_palmprint(self):
        self._pair('palmprint', BioSample.image(synthetic.palmprint_image(1)),
                   BioSample.image(synthetic.palmprint_image(1)),
                   BioSample.image(synthetic.palmprint_image(9)))

    def test_vein(self):
        self._pair('vein', BioSample.image(synthetic.vein_image(1)),
                   BioSample.image(synthetic.vein_image(1)),
                   BioSample.image(synthetic.vein_image(9)))

    def test_retina(self):
        self._pair('retina', BioSample.image(synthetic.retina_image(1)),
                   BioSample.image(synthetic.retina_image(1)),
                   BioSample.image(synthetic.retina_image(9)))

    def test_fingerprint(self):
        self._pair('fingerprint', BioSample.image(synthetic.fingerprint_image(1)),
                   BioSample.image(synthetic.fingerprint_image(1)),
                   BioSample.image(synthetic.fingerprint_image(9)))

    def test_gait(self):
        self._pair('gait',
                   BioSample.frames(synthetic.gait_frames(1, count=64, width_scale=0.9)),
                   BioSample.frames(synthetic.gait_frames(2, count=64, width_scale=0.9, phase=0.4)),
                   BioSample.frames(synthetic.gait_frames(9, count=64, width_scale=1.35, cycles=1.6)))

    def test_signature(self):
        a, ia = synthetic.signature_strokes(1)
        b, ib = synthetic.signature_strokes(1)
        c, ic = synthetic.signature_strokes(9)
        self._pair('signature', BioSample.strokes(a, image=ia), BioSample.strokes(b, image=ib),
                   BioSample.strokes(c, image=ic))

    def test_voiceprint(self):
        self._pair('voiceprint', BioSample.audio(synthetic.voice_wave(1, speaker=1), 16000),
                   BioSample.audio(synthetic.voice_wave(2, speaker=1), 16000),
                   BioSample.audio(synthetic.voice_wave(3, speaker=5), 16000))

    def test_blank_image_rejected(self):
        engine = self.registry.resolve('palmprint')
        blank = np.full((160, 160, 3), 128, np.uint8)
        report = engine.quality(BioSample.image(blank))
        self.assertFalse(report.passed)
        with self.assertRaises(ValueError):
            engine.extract(BioSample.image(blank))

    def test_specs_listed(self):
        specs = self.registry.specs()
        names = {s['name'] for s in specs}
        self.assertEqual(names, {'face', 'voiceprint', 'fingerprint', 'iris', 'palmprint',
                                 'vein', 'gait', 'retina', 'signature'})


class TemplateTests(unittest.TestCase):
    def test_roundtrip(self):
        t = BioTemplate(modality='test', arrays={'a': np.arange(6, dtype=np.float32).reshape(2, 3)},
                        meta={'x': '值'}, quality=0.8)
        blob = t.encode()
        back = BioTemplate.decode(blob)
        self.assertEqual(back.modality, 'test')
        self.assertTrue(np.allclose(back.arrays['a'], t.arrays['a']))
        self.assertEqual(back.meta['x'], '值')
        self.assertEqual(back.digest(), t.digest())
        self.assertEqual(t.to_bytes(), blob)

    def test_digest_changes(self):
        a = BioTemplate(modality='m', arrays={'a': np.zeros(4, np.float32)})
        b = BioTemplate(modality='m', arrays={'a': np.ones(4, np.float32)})
        self.assertNotEqual(a.digest(), b.digest())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caosbio_')
        self.store = BioTemplateStore(os.path.join(self.tmp, 'bio.db'))
        self.engine = build_biometric_registry().resolve('palmprint')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_load_gallery_delete(self):
        t1 = self.engine.extract(BioSample.image(synthetic.palmprint_image(1)))
        self.assertTrue(self.store.save('张三', t1))
        loaded = self.store.load('张三', 'palmprint')
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.modality, 'palmprint')
        entries = self.store.gallery('palmprint')
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][0], '张三')
        self.assertIn('palmprint', self.store.modalities_of('张三'))
        stats = self.store.stats()
        self.assertEqual(stats['total'], 1)
        self.assertEqual(self.store.delete('张三'), 1)
        self.assertEqual(self.store.stats()['total'], 0)

    def test_1n_match(self):
        t1 = self.engine.extract(BioSample.image(synthetic.palmprint_image(1)))
        t9 = self.engine.extract(BioSample.image(synthetic.palmprint_image(9)))
        self.store.save('张三', t1)
        result = self.store.locate_gallery('palmprint', self.engine, t1)
        self.assertTrue(result.passed)
        self.assertEqual(result.subject, '张三')
        result2 = self.store.locate_gallery('palmprint', self.engine, t9)
        self.assertFalse(result2.passed)

    def test_skip_lower_quality(self):
        t1 = self.engine.extract(BioSample.image(synthetic.palmprint_image(1)))
        t1.quality = 0.9
        t2 = self.engine.extract(BioSample.image(synthetic.palmprint_image(1)))
        t2.quality = 0.5
        self.store.save('李四', t1)
        self.assertFalse(self.store.save('李四', t2))
        self.assertAlmostEqual(self.store.get_entry('李四', 'palmprint').quality, 0.9)


class FusionTests(unittest.TestCase):
    def _r(self, modality, score, quality=0.9):
        return MatchResult(modality, score, 0.6, score >= 0.6, 'u', quality)

    def test_weighted(self):
        results = [self._r('face', 0.9), self._r('voiceprint', 0.5)]
        out = fuse(results, FusionPolicy(rule='weighted', threshold=0.7))
        self.assertTrue(0.5 < out.score < 0.9)
        self.assertFalse(out.passed)
        out2 = fuse(results, FusionPolicy(rule='weighted', threshold=0.6))
        self.assertTrue(out2.passed)

    def test_any_all(self):
        results = [self._r('face', 0.9), self._r('voiceprint', 0.5)]
        self.assertTrue(fuse(results, FusionPolicy(rule='any', threshold=0.6)).passed)
        self.assertFalse(fuse(results, FusionPolicy(rule='all', threshold=0.6)).passed)

    def test_liveness_veto(self):
        results = [self._r('face', 0.99)]
        out = fuse(results, FusionPolicy(rule='any', require_liveness=True), liveness_ok=False)
        self.assertFalse(out.passed)

    def test_eer(self):
        rng = np.random.default_rng(7)
        genuine = rng.normal(0.82, 0.06, 500).clip(0, 1)
        impostor = rng.normal(0.45, 0.08, 500).clip(0, 1)
        report = evaluate_thresholds(genuine, impostor)
        self.assertIn('eer', report)
        self.assertLess(report['eer'], 0.05)


class LivenessTests(unittest.TestCase):
    def _face(self):
        """构造带纹理的「人脸」区域：平坦纯色会被启发式判为打印/糊图。"""
        import cv2
        rng = np.random.default_rng(3)
        img = np.full((240, 320, 3), 110, np.uint8)
        for x in range(0, 320, 20):
            cv2.line(img, (x, 0), (x + 40, 240), (140, 120, 100), 2)
        cv2.circle(img, (160, 110), 60, (150, 130, 110), -1)
        cv2.circle(img, (140, 95), 8, (40, 40, 40), -1)
        cv2.circle(img, (180, 95), 8, (40, 40, 40), -1)
        noise = rng.normal(0, 8, img.shape)
        return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    def test_degraded_without_model(self):
        policy = LivenessPolicy(mode='degraded', consecutive=1, heuristic_threshold=0.5)
        gate = FacePadGate(FaceLivenessDetector(None, policy), policy)
        bbox = [100, 60, 200, 180]
        report = gate.check(self._face(), bbox)
        self.assertEqual(report.mode.startswith('heuristic'), True)
        self.assertTrue(report.passed)
        self.assertTrue(any('降级' in r for r in report.reasons))

    def test_strict_without_model(self):
        policy = LivenessPolicy(mode='strict', consecutive=1)
        gate = FacePadGate(FaceLivenessDetector(None, policy), policy)
        report = gate.check(self._face(), [100, 60, 200, 180])
        self.assertFalse(report.passed)

    def test_temporal_requires_streak(self):
        policy = LivenessPolicy(mode='degraded', consecutive=3, heuristic_threshold=0.5)
        gate = FacePadGate(FaceLivenessDetector(None, policy), policy)
        reports = [gate.check(self._face(), [100, 60, 200, 180]) for _ in range(4)]
        self.assertFalse(reports[0].passed)
        self.assertTrue(reports[-1].passed)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='caosbio_svc_')
        self.store = BioTemplateStore(os.path.join(self.tmp, 'bio.db'))
        self.service = BiometricService(build_biometric_registry(), self.store)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enroll_and_verify(self):
        samples = [BioSample.image(synthetic.palmprint_image(1))]
        result = self.service.enroll('王五', 'palmprint', samples, min_samples=1)
        self.assertTrue(result.ok, result.issues)
        v = self.service.verify_1n('palmprint', BioSample.image(synthetic.palmprint_image(1)),
                                   require_liveness=False)
        self.assertTrue(v['passed'])
        self.assertEqual(v['match']['subject'], '王五')

    def test_multi_factor(self):
        self.service.enroll('赵六', 'palmprint', [BioSample.image(synthetic.palmprint_image(1))])
        self.service.enroll('赵六', 'voiceprint', [BioSample.audio(synthetic.voice_wave(1, speaker=1), 16000)])
        out = self.service.verify_subject('赵六', {
            'palmprint': BioSample.image(synthetic.palmprint_image(1)),
            'voiceprint': BioSample.audio(synthetic.voice_wave(2, speaker=1), 16000),
        }, policy=FusionPolicy(rule='weighted', threshold=0.6), require_liveness=False)
        self.assertTrue(out['passed'], out)
        out2 = self.service.verify_subject('赵六', {
            'palmprint': BioSample.image(synthetic.palmprint_image(9)),
            'voiceprint': BioSample.audio(synthetic.voice_wave(3, speaker=5), 16000),
        }, policy=FusionPolicy(rule='all', threshold=0.6), require_liveness=False)
        self.assertFalse(out2['passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
