"""通行记录页：筛选、刷新、CSV 导出。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ui_kit import Card, SectionHeader, StatusPill


class RecordsPage(QWidget):
    message = Signal(str, str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        bar.addWidget(SectionHeader('通行记录', '本地事件库（WAL）· 可导出审计'))
        bar.addStretch(1)
        self.result_filter = QComboBox()
        self.result_filter.addItems(['全部结果', '仅通过', '仅拒绝'])
        self.modality_filter = QComboBox()
        self.modality_filter.addItems(['全部模态', 'face', 'voiceprint', 'fingerprint', 'iris',
                                       'palmprint', 'vein', 'gait', 'retina', 'signature'])
        self.refresh_btn = QPushButton('刷新')
        self.export_btn = QPushButton('导出 CSV')
        self.export_btn.setProperty('class', 'primary')
        bar.addWidget(self.result_filter)
        bar.addWidget(self.modality_filter)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.export_btn)
        root.addLayout(bar)

        card = Card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 14, 14)
        cv.setSpacing(8)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['时间', '主体', '模态', '相似度', '活体', '结果', '详情'])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        cv.addWidget(self.table, 1)
        self.footer = QLabel('')
        self.footer.setProperty('class', 'faint')
        cv.addWidget(self.footer)
        root.addWidget(card, 1)

        self.refresh_btn.clicked.connect(self.refresh)
        self.export_btn.clicked.connect(self._export)
        self.result_filter.currentIndexChanged.connect(self.refresh)
        self.modality_filter.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        result = {'仅通过': 'pass', '仅拒绝': 'deny'}.get(self.result_filter.currentText(), '')
        modality = '' if self.modality_filter.currentIndex() == 0 else self.modality_filter.currentText()
        events = self.store.recent(limit=200, result=result, modality=modality)
        self.table.setRowCount(len(events))
        for row, ev in enumerate(events):
            when = datetime.fromtimestamp(ev.ts).strftime('%Y-%m-%d %H:%M:%S')
            values = [when, ev.subject, ev.modality, f'{ev.score:.3f}', f'{ev.liveness:.2f}',
                      ev.result_text, ev.detail]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if col in (0, 1, 6) else Qt.AlignCenter))
                if col == 5:
                    item.setForeground(Qt.green if ev.passed else Qt.red)
                self.table.setItem(row, col, item)
        self.footer.setText(f'共 {len(events)} 条（最多显示 200 条） · 双击可查看详情')

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, '导出通行记录',
                                              f'通行记录_{datetime.now():%Y%m%d_%H%M}.csv',
                                              'CSV (*.csv)')
        if not path:
            return
        try:
            self.store.export_csv(Path(path))
            self.message.emit(f'已导出：{path}', 'ok')
        except Exception as exc:
            self.message.emit(f'导出失败：{exc}', 'danger')
