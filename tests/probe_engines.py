"""引擎探针：打印每个模态的质量分与同源/异源相似度，便于调参与回归。

运行：``python -m tests.probe_engines``
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from biometrics import BioSample, build_biometric_registry  # noqa: E402
from tests import synthetic  # noqa: E402


def probe():
    reg = build_biometric_registry()
    cases = {}

    def add(name, sample_a, sample_b, sample_c):
        cases[name] = (sample_a, sample_b, sample_c)

    add('iris', BioSample.image(synthetic.iris_image(1)), BioSample.image(synthetic.iris_image(1, shift=(3, -2))),
        BioSample.image(synthetic.iris_image(7)))
    add('palmprint', BioSample.image(synthetic.palmprint_image(1)), BioSample.image(synthetic.palmprint_image(1)),
        BioSample.image(synthetic.palmprint_image(9)))
    add('vein', BioSample.image(synthetic.vein_image(1)), BioSample.image(synthetic.vein_image(1)),
        BioSample.image(synthetic.vein_image(9)))
    add('retina', BioSample.image(synthetic.retina_image(1)), BioSample.image(synthetic.retina_image(1)),
        BioSample.image(synthetic.retina_image(9)))
    add('fingerprint', BioSample.image(synthetic.fingerprint_image(1)), BioSample.image(synthetic.fingerprint_image(1)),
        BioSample.image(synthetic.fingerprint_image(9)))
    add('gait', BioSample.frames(synthetic.gait_frames(1, count=64, width_scale=0.9, cycles=1.0)),
        BioSample.frames(synthetic.gait_frames(2, count=64, width_scale=0.9, cycles=1.0, phase=0.5)),
        BioSample.frames(synthetic.gait_frames(9, count=64, width_scale=1.35, cycles=1.6, phase=1.4)))
    strokes_a, img_a = synthetic.signature_strokes(1)
    strokes_b, img_b = synthetic.signature_strokes(1)
    strokes_c, img_c = synthetic.signature_strokes(9)
    add('signature', BioSample.strokes(strokes_a, image=img_a), BioSample.strokes(strokes_b, image=img_b),
        BioSample.strokes(strokes_c, image=img_c))
    add('voiceprint', BioSample.audio(synthetic.voice_wave(1, speaker=1), 16000),
        BioSample.audio(synthetic.voice_wave(2, speaker=1), 16000),
        BioSample.audio(synthetic.voice_wave(3, speaker=5), 16000))

    print(f"{'modality':<12} {'avail':<6} {'quality':<8} {'same':<8} {'diff':<8} {'margin':<8} note")
    for name, (sa, sb, sc) in cases.items():
        engine = reg.resolve(name)
        ok, reason = engine.check_available()
        if not ok:
            print(f'{name:<12} NO      -        -        -        -        {reason}')
            continue
        try:
            qa = engine.quality(sa)
            ta = engine.extract(sa)
            tb = engine.extract(sb)
            tc = engine.extract(sc)
            same = engine.compare(ta, tb)
            diff = engine.compare(ta, tc)
            note = '' if same > diff else '⚠ 同源不高于异源'
            print(f'{name:<12} YES     {qa.score:<8.3f} {same:<8.3f} {diff:<8.3f} {same-diff:<8.3f} {note}')
        except Exception as exc:
            print(f'{name:<12} YES     ERROR    {type(exc).__name__}: {exc}')


if __name__ == '__main__':
    probe()
