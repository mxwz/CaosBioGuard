"""Caos BioGuard Kiosk 主壳：顶栏 + Tab 导航 + 页面栈 + 线程编排。

替代旧 ``sideUI_unified.py`` 的单页堆叠 + 弹窗式交互；旧文件保留用于回退。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ui_kit import (AnimatedStackedWidget, Card, IconTabBar, KioskBackground, StatusPill,
                    THEME_MANAGER, Toast, theme_names)
from hardware import HardwareManager
from version import CURRENT_VERSION

from .data import EdgeEvent, EventStore, KioskConfig, SubjectRepository
from .pages.admin import AdminPage
from .pages.enroll import EnrollPage
from .pages.multimodal import MultimodalPage
from .pages.recognize import RecognizePage
from .pages.records import RecordsPage
from .workers import CameraWorker, DemoStreamWorker, FaceResult, InferenceWorker, run_task


class AdminLoginOverlay(QWidget):
    unlocked = Signal()

    def __init__(self, config: KioskConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._first_time = not bool(config.get('Kiosk', 'admin_pin', '').strip())
        self.setAttribute(Qt.WA_StyledBackground, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        card = Card()
        card.setMaximumWidth(400)
        card.setMinimumWidth(360)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(26, 24, 26, 24)
        cv.setSpacing(12)
        self.title = QLabel('设置管理员 PIN' if self._first_time else '管理员验证')
        self.title.setProperty('class', 'section')
        self.hint = QLabel('首次进入请设置 4–8 位 PIN，之后管理页仅管理员可见。'
                           if self._first_time else '输入 PIN 解锁人员、参数与系统设置。')
        self.hint.setProperty('class', 'faint')
        self.hint.setWordWrap(True)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setPlaceholderText('PIN')
        self.pin.setMaxLength(8)
        self.pin.setMinimumHeight(42)
        self.error = QLabel('')
        self.error.setStyleSheet('color:#ff5f6d;')
        row = QHBoxLayout()
        self.cancel = QPushButton('取消')
        self.cancel.setProperty('class', 'ghost')
        self.ok = QPushButton('解锁' if not self._first_time else '设置并进入')
        self.ok.setProperty('class', 'primary')
        row.addWidget(self.cancel)
        row.addWidget(self.ok)
        cv.addWidget(self.title)
        cv.addWidget(self.hint)
        cv.addWidget(self.pin)
        cv.addWidget(self.error)
        cv.addLayout(row)
        wrapper = QHBoxLayout()
        wrapper.addStretch(1)
        wrapper.addWidget(card)
        wrapper.addStretch(1)
        layout.addLayout(wrapper)
        layout.addStretch(1)
        self.ok.clicked.connect(self._submit)
        self.cancel.clicked.connect(self.hide)
        self.pin.returnPressed.connect(self._submit)

    def open(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.error.setText('')
        self.pin.clear()
        self.show()
        self.raise_()
        self.pin.setFocus()

    def _submit(self) -> None:
        value = self.pin.text().strip()
        if not value:
            self.error.setText('请输入 PIN')
            return
        if self._first_time:
            if len(value) < 4:
                self.error.setText('PIN 至少 4 位')
                return
            self.config.set('Kiosk', 'admin_pin', value)
            self._first_time = False
            self.hide()
            self.unlocked.emit()
            return
        if value != self.config.get('Kiosk', 'admin_pin', ''):
            self.error.setText('PIN 不正确')
            self.pin.clear()
            return
        self.hide()
        self.unlocked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 180))


class KioskWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = KioskConfig()
        self.repo = SubjectRepository(self.config)
        self.events = EventStore()
        self._pool = QThreadPool.globalInstance()
        self._camera: Optional[CameraWorker] = None
        self._demo: Optional[DemoStreamWorker] = None
        self._inference: Optional[InferenceWorker] = None
        self.hardware: Optional[HardwareManager] = None
        self._admin_unlocked = False
        self._shutting_down = False
        self._last_emit: Dict[str, float] = {}
        self._frame_count = 0
        self._fps = 0.0
        self._result_clear_timer = QTimer(self)
        self._result_clear_timer.setSingleShot(True)
        self._result_clear_timer.timeout.connect(self._clear_result)
        self._demo_fallback = QTimer(self)
        self._demo_fallback.setSingleShot(True)
        self._demo_fallback.timeout.connect(self._fallback_demo)
        self._demo_kick = QTimer(self)
        self._demo_kick.setSingleShot(True)
        self._demo_kick.timeout.connect(self._start_demo)

        self.setWindowTitle('Caos BioGuard · 多模态门禁终端')
        self.resize(1440, 900)
        self._build_ui()
        if self.config.get_bool('Hardware', 'enabled', True):
            self.hardware = HardwareManager.from_config(self.config)
        self._apply_theme(self.config.get('UI', 'theme', 'obsidian'), persist=False)
        self._start_threads()

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start()
        self._tick_clock()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(2200)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start()
        self._refresh_stats()

        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._tick_fps)
        self._fps_timer.start()
        self._last_fps_count = 0

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = KioskBackground()
        central.setObjectName('KioskRoot')
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 14, 20, 12)
        outer.setSpacing(12)

        top = QFrame()
        top.setProperty('class', 'cardAlt')
        top.setAttribute(Qt.WA_StyledBackground, True)
        top.setFixedHeight(76)
        th = QHBoxLayout(top)
        th.setContentsMargins(20, 10, 16, 10)
        th.setSpacing(14)
        brand = QVBoxLayout()
        brand.setSpacing(1)
        name = QLabel(f'CAOS <span style="color:{THEME_MANAGER.current.accent}">BIOGUARD</span>')
        name.setStyleSheet('font-size:22px; font-weight:800; letter-spacing:1px;')
        self.brand_name = name
        sub = QLabel('MULTIMODAL ACCESS TERMINAL · 多模态门禁终端')
        sub.setProperty('class', 'faint')
        brand.addWidget(name)
        brand.addWidget(sub)
        th.addLayout(brand)
        th.addStretch(1)

        clock_box = QVBoxLayout()
        clock_box.setSpacing(0)
        self.clock = QLabel('--:--:--')
        self.clock.setStyleSheet('font-size:26px; font-weight:700; letter-spacing:1px;')
        self.date = QLabel('')
        self.date.setProperty('class', 'faint')
        self.date.setAlignment(Qt.AlignRight)
        self.clock.setAlignment(Qt.AlignRight)
        clock_box.addWidget(self.clock)
        clock_box.addWidget(self.date)
        th.addLayout(clock_box)
        th.addSpacing(10)

        self.engine_pill = StatusPill('引擎加载中', 'busy')
        self.camera_pill = StatusPill('视频流', 'idle')
        self.cloud_pill = StatusPill('云边待连接', 'idle')
        th.addWidget(self.engine_pill)
        th.addWidget(self.camera_pill)
        th.addWidget(self.cloud_pill)

        self.theme_btn = QPushButton('◐')
        self.theme_btn.setFixedSize(38, 38)
        self.theme_btn.setToolTip('切换主题')
        self.theme_btn.clicked.connect(self._theme_menu)
        self.lock_btn = QPushButton('管理员')
        self.lock_btn.setMinimumHeight(36)
        self.lock_btn.clicked.connect(self._ask_admin)
        th.addWidget(self.theme_btn)
        th.addWidget(self.lock_btn)
        if not self.config.get_bool('Kiosk', 'fullscreen', True):
            close = QPushButton('✕')
            close.setFixedSize(34, 34)
            close.setProperty('class', 'ghost')
            close.clicked.connect(self.close)
            th.addWidget(close)
        outer.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(14)
        nav_card = Card()
        nav_card.setFixedWidth(208)
        nv = QVBoxLayout(nav_card)
        nv.setContentsMargins(6, 12, 6, 12)
        nv.setSpacing(8)
        nav_title = QLabel('导航')
        nav_title.setProperty('class', 'faint')
        nav_title.setContentsMargins(14, 0, 0, 0)
        nv.addWidget(nav_title)
        self.nav = IconTabBar([('◎', '识别'), ('＋', '注册'), ('◇', '多模态'),
                               ('≡', '记录'), ('⚙', '管理')])
        nv.addWidget(self.nav, 1)
        nav_footer = QLabel(f'v{CURRENT_VERSION}\n{self.config.get("Kiosk", "device_id", "EDGE-KIOSK-01")}\n'
                            f'本地模式 · 数据不出设备')
        nav_footer.setProperty('class', 'faint')
        nav_footer.setAlignment(Qt.AlignLeft)
        nav_footer.setContentsMargins(12, 0, 6, 4)
        nv.addWidget(nav_footer)
        body.addWidget(nav_card)

        self.stack = QWidget()
        self.pages = AnimatedStackedWidget()
        self.recognize = RecognizePage()
        self.enroll = EnrollPage()
        self.multimodal = MultimodalPage(self.config, self.repo)
        self.records = RecordsPage(self.events)
        self.admin = AdminPage(self.config, self.repo)
        for page in (self.recognize, self.enroll, self.multimodal, self.records, self.admin):
            self.pages.addWidget(page)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 6, 0)
        self.footer_left = QLabel('')
        self.footer_left.setProperty('class', 'faint')
        self.footer_right = QLabel('')
        self.footer_right.setProperty('class', 'faint')
        footer.addWidget(self.footer_left)
        footer.addStretch(1)
        footer.addWidget(self.footer_right)
        outer.addLayout(footer)

        self.nav.changed.connect(self._switch_page)
        self.nav._buttons[4].setVisible(False)
        self.enroll.enrollRequested.connect(self._enroll_face)
        self.enroll.message.connect(self.toast_message)
        self.multimodal.message.connect(self.toast_message)
        self.multimodal.enrolled.connect(self._after_enroll)
        self.records.message.connect(self.toast_message)
        self.admin.message.connect(self.toast_message)
        self.admin.themeRequested.connect(self._apply_theme)
        self.admin.subjectsChanged.connect(self._after_subjects_changed)
        self.admin.lockRequested.connect(self._lock_admin)
        self.admin.syncRequested.connect(lambda: self.toast_message('云边同步模块将在本批次后续接入', 'info'))

        self.toast = Toast(central)
        self.login = AdminLoginOverlay(self.config, central)
        self.login.unlocked.connect(self._on_unlocked)
        self.login.hide()

    # ------------------------------------------------------------------
    def _switch_page(self, index: int) -> None:
        if index == 4 and not self._admin_unlocked:
            self._ask_admin()
            self.nav.set_current(self.pages.currentIndex())
            return
        self.pages.fade_to(index)

    def _ask_admin(self) -> None:
        if self._admin_unlocked:
            self.nav.set_current(4)
            self.pages.fade_to(4)
            return
        self.login.open()

    def _on_unlocked(self) -> None:
        self._admin_unlocked = True
        self.nav._buttons[4].setVisible(True)
        self.lock_btn.setText('管理已解锁')
        self.nav.set_current(4)
        self.pages.fade_to(4)
        self.admin.refresh()
        self.toast_message('管理员已解锁', 'ok')

    def _lock_admin(self) -> None:
        self._admin_unlocked = False
        self.nav._buttons[4].setVisible(False)
        self.nav.set_current(0)
        self.pages.fade_to(0)
        self.lock_btn.setText('管理员')
        self.toast_message('已锁定管理功能', 'info')

    def _theme_menu(self) -> None:
        menu = QMenu(self)
        for key, name in theme_names():
            action = QAction(name, menu)
            action.triggered.connect(lambda _=False, k=key: self._apply_theme(k))
            menu.addAction(action)
        menu.exec(self.theme_btn.mapToGlobal(self.theme_btn.rect().bottomLeft()))

    def _apply_theme(self, key: str, persist: bool = True) -> None:
        THEME_MANAGER.apply(QApplication.instance(), key)
        if persist:
            self.config.set('UI', 'theme', key)
        theme = THEME_MANAGER.current
        if getattr(self, 'brand_name', None):
            self.brand_name.setText(f'CAOS <span style="color:{theme.accent}">BIOGUARD</span>')
        if persist:
            self.toast_message(f'已切换主题：{theme.name}', 'info')

    # ------------------------------------------------------------------
    def _start_threads(self) -> None:
        self._inference = InferenceWorker(self.repo, self.config)
        self._inference.resultReady.connect(self._on_result)
        self._inference.statusChanged.connect(self._on_engine_status)
        self._inference.start()

        self._camera = CameraWorker(self.config.get_int('Kiosk', 'camera_index', 0))
        self._camera.frameReady.connect(self._on_frame)
        self._camera.statusChanged.connect(self._on_camera_status)
        self._camera.start()
        self._demo_fallback.start(1400)

    def _start_demo(self) -> None:
        if self._demo is not None:
            return
        if self._camera is not None:
            try:
                self._camera.frameReady.disconnect()
                self._camera.statusChanged.disconnect()
                self._camera.stop()
            except Exception:
                pass
        self._demo = DemoStreamWorker()
        self._demo.frameReady.connect(self._on_frame)
        self._demo.statusChanged.connect(self._on_camera_status)
        self._demo.start()
        self.camera_pill.set_state('warn', '演示视频流')
        self.camera_pill.setToolTip('未连接摄像头，当前为内置演示画面')

    def _fallback_demo(self) -> None:
        if self._frame_count == 0:
            if self._camera is not None:
                self._camera.stop()
            self._start_demo()

    def _on_camera_status(self, text: str, ok: bool) -> None:
        sender = self.sender()
        # 摄像头线程收尾时的「已停止」不应覆盖已接管的演示流
        if sender is self._camera and self._demo is not None and not ok and '停止' in text:
            return
        short = text if ok else ('视频流中断' if '中断' in text else '视频流未连接')
        self.camera_pill.set_state('ok' if ok else 'warn', short)
        self.camera_pill.setToolTip(text)
        self.recognize.set_status(text, ok)
        if not ok and sender is self._camera and ('不可用' in text or '中断' in text or '异常' in text):
            self._demo_kick.start(200)

    def _on_engine_status(self, text: str, ok: bool) -> None:
        short = '人脸引擎就绪' if ok else '人脸引擎降级'
        self.engine_pill.set_state('ok' if ok else 'warn', short)
        self.engine_pill.setToolTip(text)
        self.recognize.set_engine(text, ok)
        if not ok:
            self.footer_right.setToolTip(text)

    def _on_frame(self, frame: np.ndarray) -> None:
        if getattr(self, '_shutting_down', False):
            return
        self._frame_count += 1
        if self._frame_count % 2 == 0 and self._inference is not None:
            self._inference.submit(frame)
        self.recognize.set_frame(frame)
        self.enroll.set_frame(frame)
        self.multimodal.set_frame(frame)
        if self.enroll.preview.pixmap().isNull():
            self.enroll.set_preview(frame)

    def _on_result(self, result: FaceResult) -> None:
        if result.bbox is not None:
            self.recognize.set_detection(result.bbox)
        else:
            self.recognize.set_detection(None)
        if result.reason == '人脸引擎未加载':
            self.recognize.set_engine('人脸引擎未加载（可继续多模态）', False)
            return
        if result.faces == 0:
            return
        now = time.time()
        key = result.name or result.reason or 'unknown'
        cooldown = self.config.get_float('Kiosk', 'cooldown', 3.0)
        shown = False
        if now - self._last_emit.get(key, 0) >= cooldown:
            self._last_emit[key] = now
            shown = True
        self.recognize.set_result(result.name, result.passed, result.score,
                                  result.liveness, result.latency_ms, result.reason)
        if shown and (result.passed or result.name or result.liveness < 0.55):
            self.events.add(EdgeEvent(
                ts=now, subject=result.name or '未注册人员', modality='face',
                score=result.score, liveness=result.liveness, passed=result.passed,
                device_id=self.config.get('Kiosk', 'device_id', ''),
                detail=result.reason or ('活体 %.2f' % result.liveness)))
            self._refresh_stats()
            if result.passed and self.hardware is not None:
                self.hardware.unlock()
        self._result_clear_timer.start(2600)

    def _clear_result(self) -> None:
        self.recognize.reset_result()

    # ------------------------------------------------------------------
    def _enroll_face(self, name: str, frame: np.ndarray) -> None:
        self.enroll.set_busy(True)
        self.enroll.set_preview(frame)

        def job():
            from biometrics import BioSample
            from biometrics.engines.face import FaceEngine
            engine = FaceEngine()
            engine.get_face_app()
            tmpl = engine.extract(BioSample.image(frame))
            if tmpl.quality < 0.45:
                raise ValueError(f'人脸质量不足（{tmpl.quality:.2f}），请正对光源重拍')
            bbox = tmpl.arrays['bbox'].reshape(-1).astype(int)
            crop = frame[max(0, bbox[1]):bbox[3], max(0, bbox[0]):bbox[2]].copy()
            emb = tmpl.arrays['embedding'].reshape(-1)
            self.repo.add_face(name, emb, crop if crop.size else None)
            return {'quality': tmpl.quality, 'crop': crop}

        def done(result):
            self.enroll.set_result(True, f'注册成功 · 质量 {result["quality"]:.2f}')
            self.toast_message(f'{name} 已注册人脸模板', 'ok')
            if result.get('crop'):
                self.enroll.set_preview(result['crop'])
            if self._inference:
                self._inference.refresh_gallery()
            self.admin.refresh()
            self.events.add(EdgeEvent(time.time(), name, 'face', 1.0, 1.0, True,
                                      self.config.get('Kiosk', 'device_id', ''), '管理员注册'))

        def failed(text: str):
            self.enroll.set_result(False, text)
            self.toast_message(text, 'danger')

        run_task(self._pool, job, done, failed)

    def _after_enroll(self, subject: str, modality: str) -> None:
        self.admin.refresh()
        self.toast_message(f'{subject} 的 {modality} 模板已入库', 'ok')

    def _after_subjects_changed(self) -> None:
        if self._inference:
            self._inference.refresh_gallery()
        self._refresh_stats()

    # ------------------------------------------------------------------
    def _tick_clock(self) -> None:
        now = datetime.now()
        self.clock.setText(now.strftime('%H:%M:%S'))
        self.date.setText(f'{now:%Y-%m-%d}  星期{"一二三四五六日"[now.weekday()]}')
        self.footer_left.setText(f'{self.config.get("Kiosk", "company", "Caos BioGuard")} · '
                                 f'{self.config.get("Kiosk", "device_id", "EDGE-KIOSK-01")} · '
                                 f'v{CURRENT_VERSION}')
        self.footer_right.setText(f'本地 SQLite WAL · 主题 {THEME_MANAGER.current.name} · FPS {self._fps:.0f}')

    def _tick_fps(self) -> None:
        self._fps = float(self._frame_count - self._last_fps_count)
        self._last_fps_count = self._frame_count

    def _refresh_stats(self) -> None:
        stats = self.events.stats_today()
        self.recognize.set_stats(stats)
        self.recognize.set_recent(self.events.recent(limit=8))
        self.records.refresh()
        self.admin.set_today(stats.get('total', 0))

    def toast_message(self, text: str, state: str = 'ok') -> None:
        self.toast.show_message(text, state)

    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, 'toast', None):
            self.toast.setGeometry(self.centralWidget().rect())
            self.toast._reposition()
        if getattr(self, 'login', None):
            self.login.setGeometry(self.centralWidget().rect())

    def closeEvent(self, event):
        self._shutting_down = True
        for timer in (self._demo_fallback, self._demo_kick, self._result_clear_timer,
                      self._stats_timer, self._fps_timer, self._clock):
            try:
                timer.stop()
            except Exception:
                pass
        for worker in (self._inference, self._camera, self._demo):
            if worker is None:
                continue
            for sig in ('frameReady', 'resultReady', 'statusChanged'):
                try:
                    getattr(worker, sig).disconnect()
                except Exception:
                    pass
            try:
                worker.stop()
                if not worker.wait(5000):
                    worker.terminate()
                    worker.wait(1000)
            except Exception:
                pass
        try:
            QApplication.processEvents()
        except Exception:
            pass
        try:
            if self.hardware is not None:
                self.hardware.shutdown()
        except Exception:
            pass
        try:
            self.events.close()
        except Exception:
            pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName('Caos BioGuard Kiosk')
    app.setStyle('Fusion')
    config = KioskConfig()
    THEME_MANAGER.apply(app, config.get('UI', 'theme', 'obsidian'))
    window = KioskWindow()
    if config.get_bool('Kiosk', 'fullscreen', True):
        window.showFullScreen()
    else:
        window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
