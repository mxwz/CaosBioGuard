"""人脸注册页：抓拍 → 质量校验 → 后台提特征入库。"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ui_kit import BusyIndicator, Card, SectionHeader, StatusPill, THEME_MANAGER


class EnrollPage(QWidget):
    enrollRequested = Signal(str, object)
    message = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame: Optional[np.ndarray] = None
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        form_card = Card()
        form = QVBoxLayout(form_card)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(14)
        form.addWidget(SectionHeader('人脸注册', '抓拍一张清晰正脸，自动提取 512 维特征'))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('姓名 / 工号（唯一）')
        self.name_edit.setMinimumHeight(42)
        form.addWidget(self.name_edit)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.capture_btn = QPushButton('抓拍当前画面')
        self.capture_btn.setProperty('class', 'primary')
        self.capture_btn.setMinimumHeight(42)
        self.file_btn = QPushButton('从图片导入')
        self.file_btn.setMinimumHeight(42)
        row.addWidget(self.capture_btn)
        row.addWidget(self.file_btn)
        form.addLayout(row)

        self.status = StatusPill('等待采集', 'idle')
        form.addWidget(self.status, alignment=Qt.AlignLeft)

        self.hint = QLabel('要求：正脸、无遮挡、光线均匀；建议同时录入声纹/掌纹作为第二因子。')
        self.hint.setProperty('class', 'faint')
        self.hint.setWordWrap(True)
        form.addWidget(self.hint)

        steps = Card(alt=True)
        sv = QVBoxLayout(steps)
        sv.setContentsMargins(16, 14, 16, 14)
        sv.setSpacing(8)
        for idx, text in enumerate(('填写姓名 / 工号', '正对屏幕完成抓拍',
                                    '质量门控校验（姿态/清晰度/占比）', '特征加密入库并刷新 1:N 图库')):
            row = QHBoxLayout()
            num = QLabel(f'0{idx + 1}')
            num.setStyleSheet(f'color:{THEME_MANAGER.current.accent}; font-weight:700;')
            label = QLabel(text)
            label.setProperty('class', 'muted')
            row.addWidget(num)
            row.addWidget(label, 1)
            sv.addLayout(row)
        form.addWidget(steps)

        self.busy = BusyIndicator()
        self.busy.setVisible(False)
        form.addWidget(self.busy, alignment=Qt.AlignLeft)
        form.addStretch(1)
        root.addWidget(form_card, 1)

        preview_card = Card()
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(18, 18, 18, 18)
        pv.setSpacing(10)
        pv.addWidget(SectionHeader('采集预览', '注册前确认人脸区域'))
        self.preview = QLabel('等待抓拍')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(420, 320)
        self.preview.setProperty('class', 'faint')
        pv.addWidget(self.preview, 1)
        self.meta = QLabel('')
        self.meta.setProperty('class', 'mono')
        pv.addWidget(self.meta)
        root.addWidget(preview_card, 1)

        self.capture_btn.clicked.connect(self._capture)
        self.file_btn.clicked.connect(self._pick_file)

    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame

    def _capture(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.message.emit('请先填写姓名或工号', 'warn')
            self.name_edit.setFocus()
            return
        if self._frame is None:
            self.message.emit('尚未收到视频帧', 'warn')
            return
        self.enrollRequested.emit(name, self._frame.copy())

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, '选择人脸图片', '', '图片 (*.jpg *.jpeg *.png *.bmp)')
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            self.message.emit('图片读取失败', 'danger')
            return
        self._frame = img
        self.set_preview(img)
        self.status.set_state('ok', '已载入图片')
        name = self.name_edit.text().strip()
        if name:
            self.enrollRequested.emit(name, img)

    def set_preview(self, frame: np.ndarray) -> None:
        if frame is None:
            return
        rgb = frame[:, :, ::-1].copy()
        h, w = rgb.shape[:2]
        img = QPixmap.fromImage(_qimage(rgb))
        self.preview.setPixmap(img.scaled(self.preview.width(), self.preview.height(),
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.meta.setText(f'{w}×{h}  px')

    def set_busy(self, busy: bool) -> None:
        self.busy.setVisible(busy)
        if busy:
            self.busy.start()
        else:
            self.busy.stop()
        self.capture_btn.setEnabled(not busy)
        self.file_btn.setEnabled(not busy)

    def set_result(self, ok: bool, text: str) -> None:
        self.set_busy(False)
        self.status.set_state('ok' if ok else 'danger', text)

    def reset(self) -> None:
        self.name_edit.clear()
        self.preview.setText('等待抓拍')
        self.preview.setPixmap(QPixmap())
        self.status.set_state('idle', '等待采集')
        self.set_busy(False)


def _qimage(rgb: np.ndarray):
    from PySide6.QtGui import QImage
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
