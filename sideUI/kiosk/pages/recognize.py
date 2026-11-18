"""识别主页：视频 HUD + 实时结果 + 今日概览 + 最近通行。"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ui_kit import (Avatar, Card, MetricTile, SectionHeader, StatusPill, VideoCanvas)
from ..data import EdgeEvent


class EventRow(QWidget):
    def __init__(self, event: EdgeEvent, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(10)
        self.avatar = Avatar(event.subject, 32)
        name = QLabel(event.subject)
        name.setMinimumWidth(70)
        meta = QLabel(f'{event.modality}  {event.time_text}')
        meta.setProperty('class', 'faint')
        state = StatusPill('通过' if event.passed else '拒绝', 'ok' if event.passed else 'danger')
        state.setFixedHeight(24)
        layout.addWidget(self.avatar)
        layout.addWidget(name)
        layout.addWidget(meta, 1)
        layout.addWidget(state)


class RecognizePage(QWidget):
    modeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(14)
        self.canvas = VideoCanvas()
        left.addWidget(self.canvas, 1)

        strip = QHBoxLayout()
        strip.setSpacing(10)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for idx, (key, text) in enumerate((('face', '人脸 1:N'), ('multi', '多模态融合'))):
            btn = QPushButton(text)
            btn.setProperty('class', 'chip')
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            if idx == 0:
                btn.setChecked(True)
            self.mode_group.addButton(btn, idx)
            strip.addWidget(btn)
        strip.addStretch(1)
        left.addLayout(strip)
        root.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(14)
        self.result_card = Card()
        rc = QVBoxLayout(self.result_card)
        rc.setContentsMargins(22, 20, 22, 20)
        rc.setSpacing(12)
        top = QHBoxLayout()
        self.avatar = Avatar('?', 58)
        who = QVBoxLayout()
        who.setSpacing(2)
        self.name_label = QLabel('等待识别')
        self.name_label.setProperty('class', 'title')
        self.name_label.setStyleSheet('font-size:22px;')
        self.sub_label = QLabel('请正对屏幕，保持 0.5–1.2 米距离')
        self.sub_label.setProperty('class', 'muted')
        who.addWidget(self.name_label)
        who.addWidget(self.sub_label)
        top.addWidget(self.avatar)
        top.addLayout(who, 1)
        rc.addLayout(top)

        self.state_pill = StatusPill('待机', 'idle')
        rc.addWidget(self.state_pill, alignment=Qt.AlignLeft)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        self.score_label = QLabel('—')
        self.score_label.setProperty('class', 'metric')
        self.score_label.setStyleSheet('font-size:20px;')
        self.live_label = QLabel('—')
        self.live_label.setProperty('class', 'metric')
        self.live_label.setStyleSheet('font-size:20px;')
        self.latency_label = QLabel('—')
        self.latency_label.setProperty('class', 'mono')
        for col, (title, value) in enumerate((('相似度', self.score_label), ('活体分', self.live_label))):
            cap = QLabel(title)
            cap.setProperty('class', 'faint')
            grid.addWidget(cap, 0, col)
            grid.addWidget(value, 1, col)
        cap = QLabel('推理耗时')
        cap.setProperty('class', 'faint')
        grid.addWidget(cap, 2, 0)
        grid.addWidget(self.latency_label, 2, 1, 1, 2)
        rc.addLayout(grid)
        right.addWidget(self.result_card)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.tile_total = MetricTile('今日通行', '0', '累计识别')
        self.tile_pass = MetricTile('通过', '0', '')
        self.tile_deny = MetricTile('拒绝', '0', '')
        for t in (self.tile_total, self.tile_pass, self.tile_deny):
            t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            stats.addWidget(t)
        right.addLayout(stats)

        recent_card = Card()
        rl = QVBoxLayout(recent_card)
        rl.setContentsMargins(18, 14, 18, 14)
        rl.setSpacing(8)
        rl.addWidget(SectionHeader('最近通行', '实时事件流'))
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(0)
        rl.addLayout(self.recent_box)
        rl.addStretch(1)
        right.addWidget(recent_card, 1)
        root.addLayout(right, 2)

    def set_frame(self, frame) -> None:
        self.canvas.set_frame(frame)

    def set_status(self, text: str, ok: bool) -> None:
        self.canvas.set_status(text, 'ok' if ok else 'danger')

    def set_engine(self, text: str, ok: bool) -> None:
        self.canvas.setToolTip(text if not ok else '人脸引擎就绪')

    def set_detection(self, bbox) -> None:
        self.canvas.set_detection(bbox)

    def set_result(self, name: str, passed: bool, score: float, liveness: float,
                   latency: float, reason: str = '') -> None:
        self.name_label.setText(name or '未识别')
        self.avatar.set_name(name or '?')
        if passed:
            self.state_pill.set_state('ok', '验证通过')
            self.sub_label.setText('门禁已放行')
            self.canvas.show_result(name, True, f'相似度 {score:.2f} · 活体 {liveness:.2f}')
        else:
            state = 'danger' if name else 'warn'
            self.state_pill.set_state(state, reason or '未通过')
            self.sub_label.setText(reason or '请调整姿态后重试')
            self.canvas.show_result(name or '未通过', False,
                                    reason or f'相似度 {score:.2f} · 活体 {liveness:.2f}')
        self.score_label.setText(f'{score:.2f}' if score > 0 else '—')
        self.live_label.setText(f'{liveness:.2f}' if liveness > 0 else '—')
        self.latency_label.setText(f'{latency:.0f} ms')

    def reset_result(self) -> None:
        self.name_label.setText('等待识别')
        self.avatar.set_name('?')
        self.state_pill.set_state('idle', '待机')
        self.sub_label.setText('请正对屏幕，保持 0.5–1.2 米距离')
        self.score_label.setText('—')
        self.live_label.setText('—')
        self.latency_label.setText('—')
        self.canvas.clear_result()

    def set_stats(self, stats: Dict[str, int]) -> None:
        self.tile_total.set_value(str(stats.get('total', 0)))
        self.tile_pass.set_value(str(stats.get('passed', 0)))
        self.tile_deny.set_value(str(stats.get('denied', 0)))

    def set_recent(self, events: List[EdgeEvent]) -> None:
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for event in events[:6]:
            self.recent_box.addWidget(EventRow(event))
        if not events:
            empty = QLabel('暂无通行记录')
            empty.setProperty('class', 'faint')
            self.recent_box.addWidget(empty)
