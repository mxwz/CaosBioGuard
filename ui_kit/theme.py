"""Caos BioGuard 主题系统。

设计目标：
- 一套令牌（颜色/圆角/间距/字号）驱动全部 QSS，组件不写死颜色；
- 主题可热切换，切换后通过 ``ThemeManager.themeChanged`` 通知自绘组件重绘；
- 默认「深空青」贴近商业考勤机/社区门禁机的高科技质感，附赠极光、熔金、晨雾三套。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import Template
from typing import Dict, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from platform_utils import IS_MACOS, IS_WINDOWS

_FONTS_READY = False


def _font_candidates() -> tuple:
    """按平台返回中文字体族优先级，QSS 与 QFont 选择共用。"""
    if IS_WINDOWS:
        return ('Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC', 'sans-serif')
    if IS_MACOS:
        return ('PingFang SC', 'Heiti SC', 'Noto Sans CJK SC', 'sans-serif')
    return ('Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'WenQuanYi Zen Hei',
            'Source Han Sans CN', 'sans-serif')


def ensure_fonts(app: Optional[QApplication]) -> None:
    """显式加载中文字体并选择可用字体族。

    Qt 的 offscreen/服务化环境经常拿不到系统字体库，导致整屏「豆腐块」；
    这里按平台尝试注册本地字体文件（不存在则静默跳过），再从候选字体族中
    选择当前系统实际可用的一个，保证 Kiosk 在无桌面会话时也能正常渲染。
    """
    global _FONTS_READY
    if _FONTS_READY or app is None:
        return
    _FONTS_READY = True
    font_files = (
        'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc',
        'C:/Windows/Fonts/consola.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    )
    for path in font_files:
        try:
            QFontDatabase.addApplicationFont(path)
        except Exception:
            pass
    families = set(QFontDatabase.families())
    family = next((c for c in _font_candidates() if c in families), app.font().family())
    app.setFont(QFont(family, 10))


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    dark: bool = True
    bg: str = '#070b14'
    bg_alt: str = '#0b1220'
    surface: str = '#0f1728'
    surface_2: str = '#141f36'
    border: str = '#1e2c47'
    border_soft: str = '#16233a'
    text: str = '#e8f1ff'
    text_muted: str = '#8ba0bd'
    text_faint: str = '#5b6f8c'
    accent: str = '#25e6d0'
    accent_2: str = '#3d8bff'
    accent_soft: str = '#123c46'
    success: str = '#37e39b'
    warning: str = '#ffc857'
    danger: str = '#ff5f6d'
    glow: str = 'rgba(37, 230, 208, 0.22)'
    radius: int = 16
    radius_sm: int = 10
    font: str = ('"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", '
                 '"Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif')
    extras: Dict[str, str] = field(default_factory=dict)

    def q(self, name: str) -> str:
        return getattr(self, name)


THEMES: Dict[str, Theme] = {
    'obsidian': Theme(
        key='obsidian', name='深空青',
        bg='#05080f', bg_alt='#0a1120', surface='#0d1626', surface_2='#12203a',
        border='#1d2e4c', text='#e9f3ff', text_muted='#8ea4c4', text_faint='#5a6d8a',
        accent='#28e7d1', accent_2='#3f8cff', accent_soft='#0f3b44',
        glow='rgba(40, 231, 209, 0.20)',
    ),
    'aurora': Theme(
        key='aurora', name='极光紫',
        bg='#0a0714', bg_alt='#120b22', surface='#171029', surface_2='#21163a',
        border='#322552', text='#f2ecff', text_muted='#a99bc4', text_faint='#75678f',
        accent='#9d7bff', accent_2='#38d6ff', accent_soft='#2a1c4d',
        glow='rgba(157, 123, 255, 0.22)',
    ),
    'ember': Theme(
        key='ember', name='熔金橙',
        bg='#0c0906', bg_alt='#16100a', surface='#1c140c', surface_2='#2a1d10',
        border='#3d2a17', text='#fff3e4', text_muted='#c2a583', text_faint='#8a7154',
        accent='#ffb13d', accent_2='#ff6a3d', accent_soft='#3d2710',
        glow='rgba(255, 177, 61, 0.20)',
    ),
    'daybreak': Theme(
        key='daybreak', name='晨雾白', dark=False,
        bg='#eef3fa', bg_alt='#e3ebf6', surface='#ffffff', surface_2='#f5f8fd',
        border='#cfdbeb', border_soft='#e0e8f3', text='#0f1b2d', text_muted='#5c6f88',
        text_faint='#8fa0b5', accent='#0b8f86', accent_2='#2b6ee0', accent_soft='#d8f3f0',
        success='#0f9d63', warning='#c77c00', danger='#d93a4a',
        glow='rgba(11, 143, 134, 0.12)',
    ),
}


_QSS = Template('''
* { outline: none; }
QWidget {
    color: $text;
    font-family: $font;
    font-size: 13px;
    selection-background-color: $accent_soft;
    selection-color: $text;
}
#KioskRoot, QMainWindow { background: $bg; }
QFrame[class="card"] {
    background: $surface;
    border: 1px solid $border_soft;
    border-radius: ${radius}px;
}
QFrame[class="cardAlt"] {
    background: $surface_2;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
}
QFrame[class="divider"] { background: $border_soft; border: none; max-height: 1px; min-height: 1px; }
QLabel { background: transparent; }
QLabel[class="title"] { font-size: 26px; font-weight: 700; letter-spacing: 0.5px; }
QLabel[class="subtitle"] { font-size: 15px; color: $text_muted; }
QLabel[class="muted"] { color: $text_muted; }
QLabel[class="faint"] { color: $text_faint; font-size: 12px; }
QLabel[class="mono"] { font-family: "Cascadia Mono", "Consolas", "Noto Sans Mono", "DejaVu Sans Mono", monospace; }
QLabel[class="metric"] { font-size: 30px; font-weight: 700; }
QLabel[class="section"] { font-size: 15px; font-weight: 600; color: $text; }

QPushButton {
    background: $surface_2;
    color: $text;
    border: 1px solid $border;
    border-radius: ${radius_sm}px;
    padding: 9px 16px;
    font-weight: 500;
}
QPushButton:hover { background: $accent_soft; border-color: $accent; }
QPushButton:pressed { padding-top: 10px; padding-bottom: 8px; }
QPushButton:disabled { color: $text_faint; border-color: $border_soft; background: $surface; }
QPushButton[class="primary"] {
    background: $accent; color: #041014; border: none; font-weight: 700;
}
QPushButton[class="primary"]:hover { background: $accent_2; color: #ffffff; }
QPushButton[class="primary"]:disabled { background: $surface_2; color: $text_faint; }
QPushButton[class="ghost"]:disabled { color: $text_faint; }
QPushButton[class="chip"]:disabled { color: $text_faint; border-color: $border_soft; }
QPushButton[class="ghost"] { background: transparent; border: 1px solid transparent; color: $text_muted; }
QPushButton[class="ghost"]:hover { color: $accent; border-color: $border; }
QPushButton[class="danger"] { background: transparent; border: 1px solid $danger; color: $danger; }
QPushButton[class="danger"]:hover { background: $danger; color: #ffffff; }
QPushButton[class="nav"] {
    background: transparent; border: none; border-radius: 12px;
    padding: 11px 18px; color: $text_muted; font-size: 14px; text-align: left;
}
QPushButton[class="nav"]:hover { color: $text; background: $surface_2; }
QPushButton[class="nav"]:checked {
    color: $text; background: $accent_soft; font-weight: 600;
    border-left: 3px solid $accent;
}
QPushButton[class="chip"] {
    background: transparent; border: 1px solid $border; border-radius: 14px;
    padding: 5px 12px; color: $text_muted; font-size: 12px;
}
QPushButton[class="chip"]:checked { border-color: $accent; color: $accent; background: $accent_soft; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: $bg_alt; border: 1px solid $border; border-radius: ${radius_sm}px;
    padding: 9px 12px; color: $text;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QLineEdit::placeholder { color: $text_faint; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border; border-radius: 8px;
    selection-background-color: $accent_soft; padding: 4px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { background: $surface_2; border-radius: 4px; width: 16px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { background: $surface_2; border-radius: 4px; width: 16px; }

QSlider::groove:horizontal { height: 6px; background: $border; border-radius: 3px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 3px; }
QSlider::handle:horizontal {
    background: $text; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
    border: 2px solid $accent;
}
QCheckBox { spacing: 8px; color: $text_muted; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid $border; background: $bg_alt; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }

QTableWidget, QTableView {
    background: transparent; border: none; gridline-color: $border_soft;
    alternate-background-color: $surface_2;
}
QTableWidget::item { padding: 8px; border-bottom: 1px solid $border_soft; }
QTableWidget::item:selected { background: $accent_soft; color: $text; }
QHeaderView::section {
    background: transparent; color: $text_muted; border: none;
    border-bottom: 1px solid $border; padding: 10px 8px; font-weight: 600;
}
QTableCornerButton::section { background: transparent; border: none; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $accent; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QToolTip {
    background: $surface_2; color: $text; border: 1px solid $accent;
    border-radius: 6px; padding: 6px 8px;
}
QProgressBar { background: $border_soft; border: none; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QMenu { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 7px 18px; border-radius: 6px; }
QMenu::item:selected { background: $accent_soft; }
QSplitter::handle { background: transparent; }
''')


def qss_for(theme: Theme) -> str:
    values = theme.__dict__.copy()
    values['radius'] = theme.radius
    values['radius_sm'] = theme.radius_sm
    return _QSS.safe_substitute(values)


class ThemeManager(QObject):
    themeChanged = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._current = THEMES['obsidian']

    @property
    def current(self) -> Theme:
        return self._current

    def apply(self, app: Optional[QApplication], key: str) -> Theme:
        theme = THEMES.get(key, THEMES['obsidian'])
        self._current = theme
        if app is not None:
            ensure_fonts(app)
            app.setStyleSheet(qss_for(theme))
            app.setPalette(_palette_for(theme))
        self.themeChanged.emit(theme)
        return theme


def _palette_for(theme: Theme) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(theme.bg))
    p.setColor(QPalette.WindowText, QColor(theme.text))
    p.setColor(QPalette.Base, QColor(theme.bg_alt))
    p.setColor(QPalette.AlternateBase, QColor(theme.surface))
    p.setColor(QPalette.Text, QColor(theme.text))
    p.setColor(QPalette.Button, QColor(theme.surface_2))
    p.setColor(QPalette.ButtonText, QColor(theme.text))
    p.setColor(QPalette.Highlight, QColor(theme.accent))
    p.setColor(QPalette.HighlightedText, QColor('#041014' if theme.dark else '#ffffff'))
    p.setColor(QPalette.ToolTipBase, QColor(theme.surface_2))
    p.setColor(QPalette.ToolTipText, QColor(theme.text))
    return p


THEME_MANAGER = ThemeManager()


def current_theme() -> Theme:
    return THEME_MANAGER.current


def theme_names() -> list:
    return [(t.key, t.name) for t in THEMES.values()]
