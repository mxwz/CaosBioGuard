"""多模态页：9 种生物特征的选择、采集、注册与 1:N 验证。

硬件未接入时仍可用「当前画面 / 图片 / WAV / 视频 / 签名板」完成全链路联调；
真实指纹/虹膜/掌纹/静脉/视网膜设备通过同一 ``BioSample`` 接口接入。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from biometrics import BioSample, BiometricService, build_biometric_registry
from biometrics.engines.audio_utils import read_wav
from ui_kit import BusyIndicator, Card, SectionHeader, SignaturePad, StatusPill

MODALITIES = [
    ('face', '人脸', 'FACE', '由人脸页管理，支持活体'),
    ('voiceprint', '声纹', 'VOICE', 'WAV / 麦克风'),
    ('fingerprint', '指纹', 'FINGER', '高分辨率指腹图'),
    ('iris', '虹膜', 'IRIS', '近红外虹膜图'),
    ('palmprint', '掌纹', 'PALM', '掌面正拍图'),
    ('vein', '静脉', 'VEIN', '近红外手背/手腕'),
    ('gait', '步态', 'GAIT', '侧面行走视频'),
    ('retina', '视网膜', 'RETINA', '眼底照相'),
    ('signature', '签名', 'SIGN', '签字板 / 纸面扫描'),
]


class ModalityButton(QPushButton):
    def __init__(self, key: str, label: str, code: str, hint: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setProperty('class', 'chip')
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setText(f'{code}\n{label}')
        self.setToolTip(f'{label} · {hint}')
        self.setStyleSheet('text-align:left; padding:8px 10px; font-weight:600;')


class MultimodalPage(QWidget):
    message = Signal(str, str)
    enrolled = Signal(str, str)

    def __init__(self, config, repo, parent=None):
        super().__init__(parent)
        self.config = config
        self.repo = repo
        self.registry = build_biometric_registry(config_manager=config)
        self.store = getattr(repo, 'bio_store', None)
        self.capture_repo = getattr(repo, 'capture_repo', None)
        self.service = BiometricService(self.registry, self.store, config_manager=config) if self.store else None
        self._current: Optional[str] = None
        self._frame: Optional[np.ndarray] = None
        self._sample: Optional[BioSample] = None
        self._sample_label = ''
        self._queue: List[BioSample] = []
        self._n_samples = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        # 左：模态矩阵
        left_card = Card()
        lv = QVBoxLayout(left_card)
        lv.setContentsMargins(18, 18, 18, 18)
        lv.setSpacing(12)
        lv.addWidget(SectionHeader('生物特征模态', '9 种模态统一模板与融合策略'))
        grid = QGridLayout()
        grid.setSpacing(8)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for idx, (key, label, code, hint) in enumerate(MODALITIES):
            btn = ModalityButton(key, label, code, hint)
            self._group.addButton(btn, idx)
            grid.addWidget(btn, idx // 3, idx % 3)
            if key == 'face':
                btn.setEnabled(False)
                btn.setToolTip('人脸在「注册」页管理，避免双入口')
        lv.addLayout(grid)
        self.spec_label = QLabel('选择一种模态查看采集要求')
        self.spec_label.setProperty('class', 'faint')
        self.spec_label.setWordWrap(True)
        lv.addWidget(self.spec_label)
        try:
            avail = sum(1 for s in self.registry.specs() if s.get('available'))
        except Exception:
            avail = 0
        summary = QLabel(f'引擎可用 {avail}/9 · 人脸引擎需 InsightFace 运行时\n'
                         '融合策略：weighted / any / all / sequential，支持活体否决')
        summary.setProperty('class', 'faint')
        summary.setWordWrap(True)
        lv.addWidget(summary)
        lv.addStretch(1)
        root.addWidget(left_card, 2)

        # 中：采集
        mid_card = Card()
        mv = QVBoxLayout(mid_card)
        mv.setContentsMargins(18, 18, 18, 18)
        mv.setSpacing(12)
        mv.addWidget(SectionHeader('样本采集', '无专用硬件时可直接用当前画面/文件联调'))
        self.stack = QStackedWidget()
        self.preview = QLabel('① 选择左侧模态\n② 采集当前画面 / 导入文件\n③ 加入样本队列\n④ 注册模板或 1:N 验证')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(420, 300)
        self.preview.setProperty('class', 'faint')
        self.sign_pad = SignaturePad()
        self.stack.addWidget(self.preview)
        self.stack.addWidget(self.sign_pad)
        mv.addWidget(self.stack, 1)
        self.sample_meta = QLabel('')
        self.sample_meta.setProperty('class', 'mono')
        mv.addWidget(self.sample_meta)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.capture_btn = QPushButton('采集当前画面')
        self.capture_btn.setProperty('class', 'primary')
        self.import_btn = QPushButton('导入文件')
        self.clear_btn = QPushButton('清空')
        self.clear_btn.setProperty('class', 'ghost')
        btns.addWidget(self.capture_btn)
        btns.addWidget(self.import_btn)
        btns.addWidget(self.clear_btn)
        mv.addLayout(btns)
        root.addWidget(mid_card, 3)

        # 右：注册/验证
        right_card = Card()
        rv = QVBoxLayout(right_card)
        rv.setContentsMargins(18, 18, 18, 18)
        rv.setSpacing(12)
        rv.addWidget(SectionHeader('模板与验证', '模板加密入库，支持 1:N'))
        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText('主体姓名 / 工号')
        rv.addWidget(self.subject_edit)
        self.samples_label = QLabel('样本队列：0')
        self.samples_label.setProperty('class', 'muted')
        rv.addWidget(self.samples_label)
        self.add_btn = QPushButton('加入样本队列')
        self.add_btn.setMinimumHeight(38)
        self.enroll_btn = QPushButton('注册该模态模板')
        self.enroll_btn.setProperty('class', 'primary')
        self.enroll_btn.setMinimumHeight(38)
        self.verify_btn = QPushButton('1:N 验证')
        self.verify_btn.setMinimumHeight(38)
        rv.addWidget(self.add_btn)
        rv.addWidget(self.enroll_btn)
        rv.addWidget(self.verify_btn)
        self.status = StatusPill('待机', 'idle')
        rv.addWidget(self.status, alignment=Qt.AlignLeft)
        self.result = QLabel('结果将在此显示')
        self.result.setWordWrap(True)
        self.result.setProperty('class', 'muted')
        rv.addWidget(self.result)
        self.busy = BusyIndicator()
        self.busy.setVisible(False)
        rv.addWidget(self.busy, alignment=Qt.AlignLeft)
        rv.addStretch(1)
        root.addWidget(right_card, 2)

        self._group.idClicked.connect(self._select_modality)
        self.capture_btn.clicked.connect(self._capture)
        self.import_btn.clicked.connect(self._import_file)
        self.clear_btn.clicked.connect(self._clear)
        self.add_btn.clicked.connect(self._add_sample)
        self.enroll_btn.clicked.connect(self._enroll)
        self.verify_btn.clicked.connect(self._verify)
        self._update_buttons()
        self._sync_subjects()

    # ------------------------------------------------------------------
    def _sync_subjects(self) -> None:
        self._subjects = self.repo.names()

    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame

    def _select_modality(self, idx: int) -> None:
        name = MODALITIES[idx][0]
        if name == 'face':
            return
        self._current = name
        self._sample = None
        spec = None
        try:
            spec = self.registry.resolve(name).spec
        except Exception:
            pass
        if spec:
            self.spec_label.setText(
                f'{spec.label} · {spec.description}\n硬件建议：{spec.hardware}\n'
                f'默认阈值 {spec.default_threshold:.2f} · 安全等级 L{spec.security_level}')
        self.stack.setCurrentIndex(1 if name == 'signature' else 0)
        self.clear_btn.setEnabled(True)
        self.import_btn.setText('导入 WAV' if name == 'voiceprint'
                                else ('导入视频' if name == 'gait' else '导入图片'))
        self.capture_btn.setText('采集签名' if name == 'signature' else '采集当前画面')
        self._update_buttons()
        self._clear()

    def _update_buttons(self) -> None:
        has = self._sample is not None
        self.add_btn.setEnabled(has)
        self.enroll_btn.setEnabled(has and bool(self._samples_count()))
        self.verify_btn.setEnabled(has and bool(self.store))
        self.enroll_btn.setText(f'注册该模态模板（{self._samples_count()} 样本）' if has
                                else '注册该模态模板')

    def _samples_count(self) -> int:
        return int(getattr(self, '_n_samples', 0))

    def _clear(self) -> None:
        self._sample = None
        self._queue = []
        self._n_samples = 0
        self.preview.setPixmap(QPixmap())
        self.preview.setText('请采集或导入样本')
        self.sample_meta.setText('')
        self.samples_label.setText('样本队列：0')
        self.status.set_state('idle', '待机')
        self.result.setText('结果将在此显示')
        self._update_buttons()

    def _set_sample(self, sample: BioSample, label: str) -> None:
        self._sample = sample
        self._sample_label = label
        self.status.set_state('ok', '样本就绪')
        self.sample_meta.setText(label)
        self._update_buttons()

    def _capture(self) -> None:
        if not self._current:
            self.message.emit('请先选择模态', 'warn')
            return
        if self._current == 'signature':
            img = self.sign_pad.image()
            strokes = self.sign_pad.dynamic_strokes()
            if img is None or len(strokes) < 2:
                self.message.emit('请先在签名板完成签名', 'warn')
                return
            self._set_sample(BioSample.strokes(strokes, image=img), '签名板 · 动态轨迹')
            self.preview.setPixmap(_to_pixmap(img).scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                          Qt.SmoothTransformation))
            return
        if self._frame is None:
            self.message.emit('尚未收到视频帧', 'warn')
            return
        self._load_image(self._frame)

    def _load_image(self, img: np.ndarray, label: str = '当前画面') -> None:
        self._set_sample(BioSample.image(img.copy()), f'{label} · {img.shape[1]}×{img.shape[0]}')
        self.preview.setPixmap(_to_pixmap(img).scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                      Qt.SmoothTransformation))

    def _import_file(self) -> None:
        if not self._current:
            self.message.emit('请先选择模态', 'warn')
            return
        if self._current == 'voiceprint':
            path, _ = QFileDialog.getOpenFileName(self, '选择声纹 WAV', '', '音频 (*.wav *.flac *.ogg)')
            if not path:
                return
            try:
                wav, sr = read_wav(path)
                self._set_sample(BioSample.audio(wav, sr), f'{Path(path).name} · {sr} Hz')
                self.preview.setText(f'音频已载入\n{Path(path).name}\n{len(wav) / sr:.1f} 秒')
            except Exception as exc:
                self.message.emit(f'音频读取失败: {exc}', 'danger')
            return
        if self._current == 'gait':
            path, _ = QFileDialog.getOpenFileName(self, '选择步态视频', '', '视频 (*.mp4 *.avi *.mov)')
            if not path:
                return
            frames = _read_video_frames(path, 36)
            if len(frames) < 12:
                self.message.emit('视频帧不足，无法用于步态', 'danger')
                return
            self._set_sample(BioSample.frames(frames), f'{Path(path).name} · {len(frames)} 帧')
            self.preview.setPixmap(_to_pixmap(frames[0]).scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                               Qt.SmoothTransformation))
            return
        path, _ = QFileDialog.getOpenFileName(self, '选择图片', '', '图片 (*.jpg *.jpeg *.png *.bmp)')
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            self.message.emit('图片读取失败', 'danger')
            return
        self._load_image(img, Path(path).name)

    def _add_sample(self) -> None:
        if self._sample is None:
            return
        self._queue.append(self._sample)
        self._queue = self._queue[-6:]
        self._n_samples = len(self._queue)
        self.samples_label.setText(f'样本队列：{self._n_samples}')
        self._update_buttons()
        self.message.emit(f'已加入样本队列（{self._n_samples}/6）', 'ok')

    def _run(self, fn, on_done) -> None:
        from ..workers import run_task
        from PySide6.QtCore import QThreadPool
        self.busy.setVisible(True)
        self.busy.start()
        self.enroll_btn.setEnabled(False)
        self.verify_btn.setEnabled(False)
        run_task(QThreadPool.globalInstance(), fn, on_done, self._on_error)

    def _on_error(self, text: str) -> None:
        self.busy.stop()
        self.busy.setVisible(False)
        self.status.set_state('danger', '失败')
        self.result.setText(text)
        self.message.emit(text, 'danger')
        self._update_buttons()

    def _serialize_sample(self, sample: BioSample, modality: str) -> tuple[bytes, str, str]:
        import io
        import json
        import wave
        if sample.kind == 'image':
            ok, buffer = cv2.imencode('.jpg', sample.data, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            if not ok:
                raise RuntimeError('原始图片编码失败')
            return buffer.tobytes(), 'image/jpeg', '.jpg'
        if sample.kind == 'audio':
            waveform, sr = sample.data
            pcm = np.clip(np.asarray(waveform, dtype=np.float32), -1, 1)
            pcm = (pcm * 32767).astype('<i2')
            fh = io.BytesIO()
            with wave.open(fh, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(int(sr))
                wf.writeframes(pcm.tobytes())
            return fh.getvalue(), 'audio/wav', '.wav'
        if sample.kind == 'frames':
            fh = io.BytesIO()
            np.savez(fh, *np.asarray(list(sample.data), dtype=np.uint8))
            return fh.getvalue(), 'application/x-npz', '.npz'
        if sample.kind == 'strokes':
            payload = json.dumps(sample.data, ensure_ascii=False, default=lambda x: x.tolist() if hasattr(x, 'tolist') else str(x))
            return payload.encode('utf-8'), 'application/json', '.json'
        fh = io.BytesIO()
        np.save(fh, np.asarray(sample.data))
        return fh.getvalue(), 'application/octet-stream', '.bin'

    def _serialize_samples(self, samples: List[BioSample], modality: str) -> tuple[bytes, str]:
        if len(samples) == 1:
            blob, mime, _ = self._serialize_sample(samples[0], modality)
            return blob, mime
        import io
        import zipfile
        fh = io.BytesIO()
        with zipfile.ZipFile(fh, 'w', zipfile.ZIP_DEFLATED) as zf:
            for idx, sample in enumerate(samples, start=1):
                blob, _, ext = self._serialize_sample(sample, modality)
                zf.writestr(f'{modality}_{idx}{ext}', blob)
        return fh.getvalue(), 'application/zip'

    def _enroll(self) -> None:
        if not self.service:
            self.message.emit('模板库不可用', 'danger')
            return
        subject = self.subject_edit.text().strip()
        if not subject:
            self.message.emit('请填写主体姓名/工号', 'warn')
            return
        if not self._queue:
            self.message.emit('请先加入至少一个样本', 'warn')
            return
        modality = self._current
        device_id = self.config.get('Kiosk', 'device_id', 'EDGE-KIOSK-01')
        samples = list(self._queue)

        def job():
            result = self.service.enroll(subject, modality, samples, device_id=device_id,
                                         min_samples=1, min_quality=0.45, use_liveness=False)
            if not result.ok:
                return result
            if self.capture_repo is None:
                raise RuntimeError('采集版本仓库不可用，拒绝只写模板不保存原始样本')
            raw_bytes, mime = self._serialize_samples(samples, modality)
            template = self.store.load(subject, modality, device_id) or self.registry.resolve(modality).extract(samples[0])
            self.capture_repo.save_capture(
                subject, modality, raw_bytes, template,
                device_id=device_id, image_mime=mime,
                meta={'source': 'kiosk_multimodal', 'samples': len(samples)},
            )
            return result

        def done(result):
            self.busy.stop()
            self.busy.setVisible(False)
            if result.ok:
                self.status.set_state('ok', '注册成功')
                self.result.setText(f'{subject} · {modality} 模板已加密入库\n质量 {result.quality:.2f}')
                self.message.emit(f'{subject} 的 {modality} 模板注册成功', 'ok')
                self.enrolled.emit(subject, modality)
                self._sync_subjects()
            else:
                self.status.set_state('warn', '注册未通过')
                self.result.setText('；'.join(result.issues) or '质量/活体门控未通过')
                self.message.emit('注册未通过：' + ('；'.join(result.issues) or '质量不足'), 'warn')
            self._update_buttons()

        self._run(job, done)

    def _verify(self) -> None:
        if not self.service:
            self.message.emit('模板库不可用', 'danger')
            return
        if not self._sample:
            return
        modality = self._current
        device_id = self.config.get('Kiosk', 'device_id', 'EDGE-KIOSK-01')
        sample = self._sample

        def job():
            return self.service.verify_1n(modality, sample, device_id=device_id,
                                          require_liveness=False)

        def done(out):
            self.busy.stop()
            self.busy.setVisible(False)
            match = out.get('match', {})
            passed = out.get('passed', False)
            self.status.set_state('ok' if passed else 'danger', '通过' if passed else '拒绝')
            self.result.setText(
                f'主体：{match.get("subject") or "未匹配"}\n'
                f'分数 {match.get("score", 0):.3f} / 阈值 {match.get("threshold", 0):.3f}\n'
                f'质量 {match.get("quality", 0):.2f} · margin {match.get("margin", 0):.3f}')
            self.message.emit(f'{modality} 1:N {"通过" if passed else "未通过"}', 'ok' if passed else 'warn')
            self._update_buttons()

        self._run(job, done)


def _to_pixmap(bgr: np.ndarray) -> QPixmap:
    rgb = bgr[:, :, ::-1].copy() if bgr.ndim == 3 else cv2.cvtColor(bgr, cv2.COLOR_GRAY2RGB)
    from PySide6.QtGui import QImage
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy())


def _read_video_frames(path: str, count: int = 36) -> List[np.ndarray]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames: List[np.ndarray] = []
    if total > 0:
        idxs = np.linspace(0, max(total - 1, 0), count).astype(int)
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
    else:
        while len(frames) < count:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    cap.release()
    return frames
