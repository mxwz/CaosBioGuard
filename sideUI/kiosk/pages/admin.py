"""管理员页：人员、识别参数、外观、同步、系统诊断。

所有设置集中在这里，未解锁时导航项不可见；识别主页不再暴露任何配置项。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QSlider, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ui_kit import Card, MetricTile, SectionHeader, StatusPill, theme_names
from ..data import KioskConfig, SubjectRepository


class AdminPage(QWidget):
    message = Signal(str, str)
    subjectsChanged = Signal()
    themeRequested = Signal(str)
    syncRequested = Signal()
    lockRequested = Signal()

    def __init__(self, config: KioskConfig, repo: SubjectRepository, parent=None):
        super().__init__(parent)
        self.config = config
        self.repo = repo
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(SectionHeader('管理中心', '仅管理员可见 · 所有配置集中于此'))
        head.addStretch(1)
        self.lock_btn = QPushButton('锁定管理')
        self.lock_btn.setProperty('class', 'ghost')
        head.addWidget(self.lock_btn)
        root.addLayout(head)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.tile_subjects = MetricTile('主体', '0', '人脸 + 多模态')
        self.tile_templates = MetricTile('模板', '0', '加密模板数')
        self.tile_today = MetricTile('今日通行', '0', '含拒绝')
        for t in (self.tile_subjects, self.tile_templates, self.tile_today):
            stats.addWidget(t)
        root.addLayout(stats)

        nav = QHBoxLayout()
        nav.setSpacing(8)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for idx, text in enumerate(('人员', '识别参数', '外观主题', '云边同步', '系统诊断')):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setProperty('class', 'chip')
            btn.setMinimumHeight(34)
            self._nav_group.addButton(btn, idx)
            nav.addWidget(btn)
        nav.addStretch(1)
        root.addLayout(nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_people())
        self.stack.addWidget(self._build_recognition())
        self.stack.addWidget(self._build_appearance())
        self.stack.addWidget(self._build_sync())
        self.stack.addWidget(self._build_system())
        self._nav_group.idClicked.connect(self.stack.setCurrentIndex)
        self._nav_group.button(0).setChecked(True)
        self.lock_btn.clicked.connect(self.lockRequested.emit)
        self.refresh()

    # ------------------------------------------------------------------
    def _build_people(self) -> QWidget:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(SectionHeader('人员与模板', '删除会同时清理人脸库与多模态模板'))
        bar.addStretch(1)
        self.people_filter = QLineEdit()
        self.people_filter.setPlaceholderText('搜索姓名/工号')
        self.people_filter.setFixedWidth(200)
        self.refresh_btn = QPushButton('刷新')
        self.del_btn = QPushButton('删除选中')
        self.del_btn.setProperty('class', 'danger')
        bar.addWidget(self.people_filter)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.del_btn)
        layout.addLayout(bar)

        self.people_table = QTableWidget(0, 4)
        self.people_table.setHorizontalHeaderLabels(['主体', '人脸模板', '多模态模板', '最近更新'])
        self.people_table.verticalHeader().setVisible(False)
        self.people_table.setShowGrid(False)
        self.people_table.setAlternatingRowColors(True)
        self.people_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.people_table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.people_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.people_table, 1)
        self.refresh_btn.clicked.connect(self.refresh)
        self.people_filter.textChanged.connect(self._filter_people)
        self.del_btn.clicked.connect(self._delete_selected)
        return card

    def _build_recognition(self) -> QWidget:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)
        layout.addWidget(SectionHeader('识别参数', '修改后立即生效；阈值过低会增加误识风险'))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)

        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(20, 85)
        self.threshold_slider.setValue(int(self.config.get_float('Kiosk', 'threshold', 0.40) * 100))
        self.threshold_value = QLabel(f'{self.threshold_slider.value() / 100:.2f}')
        self.threshold_value.setProperty('class', 'mono')
        row = QHBoxLayout()
        row.addWidget(self.threshold_slider, 1)
        row.addWidget(self.threshold_value)
        grid.addWidget(QLabel('人脸 1:N 阈值'), 0, 0)
        grid.addLayout(row, 0, 1)

        self.live_combo = QComboBox()
        self.live_combo.addItems(['strict', 'degraded', 'off'])
        self.live_combo.setCurrentText(self.config.get('Kiosk', 'liveness_mode', 'strict'))
        grid.addWidget(QLabel('活体检测模式'), 1, 0)
        grid.addWidget(self.live_combo, 1, 1)

        self.live_threshold = QSlider(Qt.Horizontal)
        self.live_threshold.setRange(40, 95)
        self.live_threshold.setValue(int(self.config.get_float('Kiosk', 'liveness_threshold', 0.72) * 100))
        self.live_value = QLabel(f'{self.live_threshold.value() / 100:.2f}')
        self.live_value.setProperty('class', 'mono')
        row2 = QHBoxLayout()
        row2.addWidget(self.live_threshold, 1)
        row2.addWidget(self.live_value)
        grid.addWidget(QLabel('活体阈值'), 2, 0)
        grid.addLayout(row2, 2, 1)

        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0.5, 30.0)
        self.cooldown_spin.setSingleStep(0.5)
        self.cooldown_spin.setValue(self.config.get_float('Kiosk', 'cooldown', 3.0))
        self.cooldown_spin.setSuffix(' 秒')
        grid.addWidget(QLabel('同一人重复识别冷却'), 3, 0)
        grid.addWidget(self.cooldown_spin, 3, 1)

        self.camera_spin = QSpinBox()
        self.camera_spin.setRange(0, 8)
        self.camera_spin.setValue(self.config.get_int('Kiosk', 'camera_index', 0))
        grid.addWidget(QLabel('摄像头索引（重启生效）'), 4, 0)
        grid.addWidget(self.camera_spin, 4, 1)
        layout.addLayout(grid)
        self.param_status = StatusPill('参数未修改', 'idle')
        layout.addWidget(self.param_status, alignment=Qt.AlignLeft)
        save = QPushButton('保存识别参数')
        save.setProperty('class', 'primary')
        save.setMaximumWidth(180)
        save.clicked.connect(self._save_params)
        layout.addWidget(save)
        layout.addStretch(1)
        self.threshold_slider.valueChanged.connect(
            lambda v: self.threshold_value.setText(f'{v / 100:.2f}'))
        self.live_threshold.valueChanged.connect(
            lambda v: self.live_value.setText(f'{v / 100:.2f}'))
        return card

    def _build_appearance(self) -> QWidget:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        layout.addWidget(SectionHeader('外观主题', '主题即时切换并写入 config.ini'))
        self.theme_combo = QComboBox()
        for key, name in theme_names():
            self.theme_combo.addItem(name, key)
        current = self.config.get('UI', 'theme', 'obsidian')
        idx = self.theme_combo.findData(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        layout.addWidget(self.theme_combo)
        apply_btn = QPushButton('应用主题')
        apply_btn.setProperty('class', 'primary')
        apply_btn.setMaximumWidth(160)
        layout.addWidget(apply_btn)
        hint = QLabel('深空青 / 极光紫 / 熔金橙适合门禁机常亮；晨雾白适合前台办公环境。')
        hint.setProperty('class', 'faint')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        apply_btn.clicked.connect(self._apply_theme)
        return card

    def _build_sync(self) -> QWidget:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        layout.addWidget(SectionHeader('云边同步', 'Outbox + 幂等键 + 指数退避（协议见 docs/cloud-edge-protocol.md）'))
        form = QGridLayout()
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(12)
        self.sync_interval = QSpinBox()
        self.sync_interval.setRange(5, 3600)
        self.sync_interval.setSuffix(' 秒')
        self.sync_interval.setValue(30)
        form.addWidget(QLabel('同步周期'), 0, 0)
        form.addWidget(self.sync_interval, 0, 1)
        endpoint = QLabel(self.config.get('WebAdmin', 'endpoint', '未配置'))
        endpoint.setProperty('class', 'mono')
        form.addWidget(QLabel('云端地址'), 1, 0)
        form.addWidget(endpoint, 1, 1)
        self.sync_pill = StatusPill('待连接', 'idle')
        form.addWidget(QLabel('连接状态'), 2, 0)
        form.addWidget(self.sync_pill, 2, 1, alignment=Qt.AlignLeft)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.sync_now = QPushButton('立即同步')
        self.sync_now.setProperty('class', 'primary')
        self.sync_now.setMaximumWidth(150)
        self.outbox_btn = QPushButton('查看待发送队列')
        row.addWidget(self.sync_now)
        row.addWidget(self.outbox_btn)
        row.addStretch(1)
        layout.addLayout(row)
        note = QLabel('断网时事件先落本地 Outbox，恢复后按幂等键补传；人脸/模板只同步摘要与模板，不传原图。')
        note.setProperty('class', 'faint')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.sync_now.clicked.connect(self.syncRequested.emit)
        self.outbox_btn.clicked.connect(lambda: self.message.emit('Outbox 队列将在同步模块接入后显示', 'info'))
        return card

    def _build_system(self) -> QWidget:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(SectionHeader('系统诊断', '版本、设备标识与运行环境'))
        self.sys_labels = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(9)
        for row, key in enumerate(('版本', '设备 ID', '运行模式', '人脸引擎', '模板库', '数据库')):
            cap = QLabel(key)
            cap.setProperty('class', 'faint')
            val = QLabel('—')
            val.setProperty('class', 'mono')
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(cap, row, 0)
            grid.addWidget(val, row, 1)
            self.sys_labels[key] = val
        layout.addLayout(grid)
        self.pin_edit = QLineEdit()
        self.pin_edit.setPlaceholderText('修改管理员 PIN（留空则不修改）')
        self.pin_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pin_edit)
        save_pin = QPushButton('更新 PIN')
        save_pin.setMaximumWidth(140)
        layout.addWidget(save_pin)
        layout.addStretch(1)
        save_pin.clicked.connect(self._save_pin)
        return card

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        names = self.repo.names()
        bio = self.repo.bio_summary()
        self.tile_subjects.set_value(str(len(names)))
        total_templates = int(sum(bio.values())) if bio else len([n for n in names if self.repo.embedding(n) is not None])
        self.tile_templates.set_value(str(total_templates))
        self.people_table.setRowCount(len(names))
        for row, name in enumerate(names):
            emb = self.repo.embedding(name)
            mods = 0
            if self.repo.bio_store:
                try:
                    mods = len(self.repo.bio_store.modalities_of(name))
                except Exception:
                    mods = 0
            values = [name, '有' if emb is not None else '—', str(mods), '—']
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if col == 0 else Qt.AlignCenter))
                self.people_table.setItem(row, col, item)
        self._filter_people(self.people_filter.text())
        try:
            from version import CURRENT_VERSION
            self.sys_labels['版本'].setText(f'v{CURRENT_VERSION}')
        except Exception:
            self.sys_labels['版本'].setText('未知')
        self.sys_labels['设备 ID'].setText(self.config.get('Kiosk', 'device_id', 'EDGE-KIOSK-01'))
        self.sys_labels['运行模式'].setText('Kiosk' if self.config.get_bool('Kiosk', 'fullscreen', True) else '窗口')
        self.sys_labels['人脸引擎'].setText('InsightFace buffalo_l（惰性加载）')
        self.sys_labels['模板库'].setText(str(self.repo.bio_store is not None))
        self.sys_labels['数据库'].setText('SQLite WAL · dd/kiosk_events.db')

    def set_today(self, total: int) -> None:
        self.tile_today.set_value(str(total))

    def set_sync_state(self, text: str, state: str) -> None:
        self.sync_pill.set_state(state, text)

    def _filter_people(self, text: str) -> None:
        text = (text or '').strip().lower()
        for row in range(self.people_table.rowCount()):
            item = self.people_table.item(row, 0)
            self.people_table.setRowHidden(row, bool(text) and text not in item.text().lower())

    def _delete_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.people_table.selectedIndexes()})
        if not rows:
            self.message.emit('请先选择要删除的主体', 'warn')
            return
        names = [self.people_table.item(r, 0).text() for r in rows]
        for name in names:
            self.repo.remove(name)
        self.message.emit(f'已删除 {len(names)} 个主体及其模板', 'ok')
        self.refresh()
        self.subjectsChanged.emit()

    def _save_params(self) -> None:
        self.config.set('Kiosk', 'threshold', f'{self.threshold_slider.value() / 100:.2f}')
        self.config.set('Kiosk', 'liveness_mode', self.live_combo.currentText())
        self.config.set('Kiosk', 'liveness_threshold', f'{self.live_threshold.value() / 100:.2f}')
        self.config.set('Kiosk', 'cooldown', f'{self.cooldown_spin.value():.1f}')
        self.config.set('Kiosk', 'camera_index', str(self.camera_spin.value()))
        self.param_status.set_state('ok', '已保存')
        self.message.emit('识别参数已保存（摄像头索引重启后生效）', 'ok')

    def _apply_theme(self) -> None:
        key = self.theme_combo.currentData()
        self.config.set('UI', 'theme', key)
        self.themeRequested.emit(key)

    def _save_pin(self) -> None:
        pin = self.pin_edit.text().strip()
        if not pin:
            return
        self.config.set('Kiosk', 'admin_pin', pin)
        self.pin_edit.clear()
        self.message.emit('管理员 PIN 已更新', 'ok')
