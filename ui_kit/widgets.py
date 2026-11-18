"""可复用的高科技风 Kiosk 组件（全部基于主题令牌，支持热切换）。"""

from __future__ import annotations

import math
import time
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF,
                            QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QBrush, QFont, QLinearGradient, QPainter, QPainterPath,
                          QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from .theme import THEME_MANAGER, Theme


def _c(color: str, alpha: int = 255) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


class Card(QFrame):
    def __init__(self, parent: Optional[QWidget] = None, *, alt: bool = False, shadow: bool = False):
        super().__init__(parent)
        self.setProperty('class', 'cardAlt' if alt else 'card')
        self.setAttribute(Qt.WA_StyledBackground, True)
        if shadow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(28)
            effect.setOffset(0, 10)
            effect.setColor(_c(THEME_MANAGER.current.bg, 160))
            self.setGraphicsEffect(effect)
        THEME_MANAGER.themeChanged.connect(lambda _t: self.update())


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = '', parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.title = QLabel(title)
        self.title.setProperty('class', 'section')
        self.subtitle = QLabel(subtitle)
        self.subtitle.setProperty('class', 'faint')
        self.subtitle.setVisible(bool(subtitle))
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


class StatusPill(QLabel):
    """状态胶囊：idle / ok / warn / danger / busy。"""

    def __init__(self, text: str = '', state: str = 'idle', parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._state = state
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(26)
        self.setContentsMargins(10, 2, 10, 2)
        THEME_MANAGER.themeChanged.connect(lambda _t: self.update())

    def set_state(self, state: str, text: Optional[str] = None) -> None:
        self._state = state
        if text is not None:
            self.setText(text)
        self.update()

    def paintEvent(self, event):
        theme = THEME_MANAGER.current
        color = {
            'ok': theme.success, 'warn': theme.warning, 'danger': theme.danger,
            'busy': theme.accent_2, 'idle': theme.text_faint,
        }.get(self._state, theme.text_faint)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(_c(color, 120), 1))
        p.setBrush(QBrush(_c(color, 26)))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(QPen(_c(color, 255)))
        f = self.font()
        f.setPointSizeF(8.6)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, self.text())


class IconTabBar(QWidget):
    """左侧/顶部通用的导航条，选中项带发光下划线。"""

    changed = Signal(int)

    def __init__(self, items: Sequence[Tuple[str, str]], vertical: bool = True,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._items = list(items)
        self._buttons: List[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QVBoxLayout(self) if vertical else QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        for idx, (icon, label) in enumerate(self._items):
            btn = QPushButton(f'  {icon}   {label}' if icon else label)
            btn.setProperty('class', 'nav')
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(42)
            if not vertical:
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._group.addButton(btn, idx)
            layout.addWidget(btn)
            self._buttons.append(btn)
        if self._buttons:
            self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self.changed.emit)
        layout.addStretch(0) if vertical else None

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def current(self) -> int:
        return self._group.checkedId()


class AnimatedStackedWidget(QStackedWidget):
    """页面切换带淡入 + 轻微上滑，避免生硬闪切。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._anim: Optional[QPropertyAnimation] = None
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_target: Optional[QWidget] = None
        self._restore_timer.timeout.connect(self._restore)

    def _restore(self) -> None:
        if self._restore_target is not None:
            try:
                self._restore_target.setGraphicsEffect(None)
            except Exception:
                pass
            self._restore_target = None

    def fade_to(self, index: int, duration: int = 200) -> None:
        if index == self.currentIndex() or not (0 <= index < self.count()):
            return
        self._restore_timer.stop()
        self._restore()
        self.setCurrentIndex(index)
        page = self.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.88)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b'opacity', self)
        anim.setDuration(duration)
        anim.setStartValue(0.88)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim = anim
        self._restore_target = page
        anim.finished.connect(self._restore)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        # 兜底：即使动画因窗口隐藏/远程桌面掉帧未触发 finished，也要恢复不透明
        self._restore_timer.start(duration + 80)


class Toast(QWidget):
    """非阻塞浮层提示，替代 QMessageBox。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setVisible(False)
        self._label = QLabel('', self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._state = 'ok'

    def show_message(self, text: str, state: str = 'ok', msec: int = 2600) -> None:
        theme = THEME_MANAGER.current
        color = {'ok': theme.success, 'warn': theme.warning, 'danger': theme.danger,
                 'info': theme.accent}.get(state, theme.accent)
        self._state = state
        self._label.setText(text)
        self._label.setStyleSheet(
            f'color:{color}; background:{theme.surface_2}; border:1px solid {color};'
            f'border-radius:12px; padding:11px 20px; font-weight:600;')
        self._label.adjustSize()
        self._label.resize(min(self._label.width() + 8, max(360, self.parentWidget().width() - 120)),
                           self._label.height() + 4)
        self._reposition()
        self.setVisible(True)
        self.raise_()
        self._timer.start(msec)

    def _reposition(self) -> None:
        pw = self.parentWidget()
        if not pw:
            return
        w = self._label.width()
        h = self._label.height()
        self.setGeometry(0, 0, pw.width(), pw.height())
        self._label.move(max(0, (pw.width() - w) // 2), pw.height() - h - 48)

    def _fade_out(self) -> None:
        self.setVisible(False)


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b'knob', self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if value == self._checked:
            return
        self._checked = value
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = float(v)
        self.update()

    knob = property(_get_knob, _set_knob)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        theme = THEME_MANAGER.current
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = theme.accent
        off = theme.border
        c = QColor(off)
        c = QColor(
            int(QColor(off).red() + (QColor(on).red() - QColor(off).red()) * self._pos),
            int(QColor(off).green() + (QColor(on).green() - QColor(off).green()) * self._pos),
            int(QColor(off).blue() + (QColor(on).blue() - QColor(off).blue()) * self._pos),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, 4, 44, 16), 8, 8)
        x = 3 + self._pos * 23
        p.setBrush(_c(theme.text))
        p.drawEllipse(QRectF(x, 3, 18, 18))


class BusyIndicator(QWidget):
    def __init__(self, parent: Optional[QWidget] = None, size: int = 34):
        super().__init__(parent)
        self._angle = 0
        self._size = size
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()
        self.setVisible(True)

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def paintEvent(self, event):
        theme = THEME_MANAGER.current
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self._angle)
        for i in range(8):
            p.setPen(Qt.NoPen)
            p.setBrush(_c(theme.accent, 40 + i * 22))
            p.drawEllipse(QRectF(-2, -self._size / 2 + 3, 4, 4))
            p.rotate(45)
        p.end()


class VideoCanvas(QWidget):
    """视频画面 + HUD：角括号、扫描线、状态胶囊、识别结果浮层。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pixmap: Optional[QPixmap] = None
        self._bbox: Optional[Sequence[float]] = None
        self._status = '等待视频流'
        self._state = 'idle'
        self._result = ''
        self._detail = ''
        self._scan = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        THEME_MANAGER.themeChanged.connect(lambda _t: self.update())

    def set_frame(self, frame: np.ndarray) -> None:
        if frame is None or frame.size == 0:
            return
        if frame.ndim == 3 and frame.shape[2] == 3:
            rgb = frame[:, :, ::-1].copy()
        else:
            rgb = frame
        h, w = rgb.shape[:2]
        img = QPixmap.fromImage(_qimage(rgb))
        self._pixmap = img
        self._active = True
        self._status_state('ok', '视频流在线')
        self.update()

    def set_status(self, text: str, state: str = 'idle') -> None:
        self._status = text
        self._state = state
        self.update()

    def set_detection(self, bbox: Optional[Sequence[float]]) -> None:
        self._bbox = list(bbox) if bbox is not None else None
        self.update()

    def show_result(self, text: str, passed: bool, detail: str = '') -> None:
        self._result = text
        self._detail = detail
        self._state = 'ok' if passed else 'danger'
        self._scan = 0.0
        self.update()

    def clear_result(self) -> None:
        self._result = ''
        self._detail = ''
        self._state = 'idle'
        self.update()

    def _status_state(self, state: str, text: str) -> None:
        if self._state == 'danger' and self._result:
            return
        self._status = text
        self._state = state

    def _tick(self) -> None:
        if not self.isVisible():
            return
        if self._result or self._active:
            self._scan = (self._scan + 0.9) % 100.0
            self.update()

    def paintEvent(self, event):
        theme = THEME_MANAGER.current
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, theme.radius, theme.radius)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(theme.bg_alt))

        if self._pixmap is not None:
            p.drawPixmap(self.rect(), self._pixmap)
        else:
            # 无视频时的科技网格 + 提示
            self._paint_placeholder(p, rect)

        # 顶部渐隐
        grad = QLinearGradient(0, 0, 0, self.height() * 0.28)
        grad.setColorAt(0, _c('#000000', 150))
        grad.setColorAt(1, _c('#000000', 0))
        p.fillRect(self.rect(), QBrush(grad))

        # 扫描线
        if self._active and not self._result:
            y = rect.top() + (self._scan / 100.0) * rect.height()
            for i in range(10):
                alpha = int(90 * (1 - i / 10))
                p.setPen(QPen(_c(theme.accent, alpha), 1))
                p.drawLine(QPointF(rect.left() + 18, y - i), QPointF(rect.right() - 18, y - i))

        # 角括号
        p.setPen(QPen(_c(theme.accent, 200), 2))
        ln = 26
        for (ox, oy, dx, dy) in ((0, 0, 1, 1), (1, 0, -1, 1), (0, 1, 1, -1), (1, 1, -1, -1)):
            x = rect.left() + 16 if ox == 0 else rect.right() - 16
            y = rect.top() + 16 if oy == 0 else rect.bottom() - 16
            p.drawLine(QPointF(x, y), QPointF(x + dx * ln, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * ln))

        # 检测框
        if self._bbox and self._pixmap is not None:
            sx = self.width() / max(self._pixmap.width(), 1)
            sy = self.height() / max(self._pixmap.height(), 1)
            b = self._bbox
            r = QRectF(b[0] * sx, b[1] * sy, (b[2] - b[0]) * sx, (b[3] - b[1]) * sy)
            p.setPen(QPen(_c(theme.accent, 220), 2))
            p.drawRoundedRect(r, 10, 10)

        # 顶部 LIVE + 状态
        self._paint_chip(p, QPointF(rect.left() + 28, rect.top() + 26), '●  LIVE', theme.danger if self._active else theme.text_faint)
        chip_color = {'ok': theme.success, 'danger': theme.danger, 'warn': theme.warning}.get(self._state, theme.text_faint)
        self._paint_chip(p, QPointF(rect.left() + 104, rect.top() + 26), self._status, chip_color)

        # 识别结果浮层
        if self._result:
            self._paint_result(p, rect, chip_color)

        p.end()

    def _paint_chip(self, p: QPainter, pos: QPointF, text: str, color: str) -> None:
        f = p.font()
        f.setPointSizeF(8.8)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 20
        h = 24
        r = QRectF(pos.x(), pos.y(), w, h)
        p.setPen(QPen(_c(color, 110), 1))
        p.setBrush(_c('#000000', 120) if THEME_MANAGER.current.dark else _c('#ffffff', 180))
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(_c(color))
        p.drawText(r, Qt.AlignCenter, text)

    def _paint_placeholder(self, p: QPainter, rect: QRectF) -> None:
        theme = THEME_MANAGER.current
        p.setPen(QPen(_c(theme.accent, 26), 1))
        step = 42
        x = rect.left()
        while x < rect.right():
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = rect.top()
        while y < rect.bottom():
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step
        glow = QRadialGradient(rect.center(), rect.width() * 0.55)
        glow.setColorAt(0, _c(theme.accent, 26))
        glow.setColorAt(1, _c(theme.accent, 0))
        p.fillRect(rect, QBrush(glow))
        p.setPen(_c(theme.text_muted))
        f = p.font()
        f.setPointSizeF(12)
        p.setFont(f)
        p.drawText(rect.adjusted(0, 0, 0, -8), Qt.AlignCenter, self._status)

    def _paint_result(self, p: QPainter, rect: QRectF, color: str) -> None:
        theme = THEME_MANAGER.current
        w = min(rect.width() - 80, 460)
        h = 118
        r = QRectF(rect.center().x() - w / 2, rect.bottom() - h - 34, w, h)
        p.setPen(QPen(_c(color, 160), 1.5))
        p.setBrush(_c(theme.surface, 235))
        p.drawRoundedRect(r, 18, 18)
        p.setPen(_c(color))
        f = p.font()
        f.setPointSizeF(22)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.drawText(r.adjusted(0, 16, 0, -40), Qt.AlignCenter, self._result)
        p.setPen(_c(theme.text_muted))
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.drawText(r.adjusted(0, 58, 0, -14), Qt.AlignCenter, self._detail)


def _qimage(rgb: np.ndarray):
    from PySide6.QtGui import QImage
    h, w = rgb.shape[:2]
    if rgb.ndim == 2:
        return QImage(rgb.data, w, h, w, QImage.Format_Grayscale8).copy()
    return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()


class MetricTile(Card):
    def __init__(self, label: str, value: str = '0', hint: str = '', parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)
        self.label = QLabel(label)
        self.label.setProperty('class', 'faint')
        self.value = QLabel(value)
        self.value.setProperty('class', 'metric')
        self.hint = QLabel(hint)
        self.hint.setProperty('class', 'muted')
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.hint)

    def set_value(self, value: str, hint: Optional[str] = None) -> None:
        self.value.setText(value)
        if hint is not None:
            self.hint.setText(hint)


class Avatar(QWidget):
    def __init__(self, name: str = '', size: int = 40, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = name
        self._size = size
        self.setFixedSize(size, size)

    def set_name(self, name: str) -> None:
        self._name = name
        self.update()

    def paintEvent(self, event):
        theme = THEME_MANAGER.current
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self._size, self._size)
        p.setPen(QPen(_c(theme.accent, 90), 1))
        p.setBrush(_c(theme.accent_soft))
        p.drawEllipse(r)
        p.setPen(_c(theme.accent))
        f = p.font()
        f.setPointSizeF(self._size * 0.38)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, (self._name or '?')[:1])


class SignaturePad(QWidget):
    """签名采集：同时保留轨迹点（动态特征）与渲染图（静态特征）。"""

    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self._strokes: List[List[Tuple[float, float, float]]] = []
        self._current: Optional[List[Tuple[float, float, float]]] = None
        self.setCursor(Qt.CrossCursor)

    def clear(self) -> None:
        self._strokes.clear()
        self._current = None
        self.update()
        self.changed.emit()

    def has_ink(self) -> bool:
        return any(len(s) > 1 for s in self._strokes)

    def dynamic_strokes(self) -> List[List[Tuple[float, float, float]]]:
        return [[(x, y, t) for (x, y, t) in s] for s in self._strokes if len(s) > 1]

    def image(self) -> Optional[np.ndarray]:
        if not self.has_ink():
            return None
        # 离屏渲染成白底黑字，交给签名引擎
        pm = QPixmap(self.size())
        pm.fill(QColor('#ffffff'))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#111111'), 2.2))
        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            for i in range(1, len(stroke)):
                p.drawLine(QPointF(stroke[i - 1][0], stroke[i - 1][1]),
                           QPointF(stroke[i][0], stroke[i][1]))
        p.end()
        img = pm.toImage().convertToFormat(4)  # Format_RGB32
        ptr = img.bits()
        arr = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.width(), 4)
        return arr[:, :, :3].copy()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._current = [(event.position().x(), event.position().y(), time.perf_counter())]
            self._strokes.append(self._current)
            self.update()

    def mouseMoveEvent(self, event):
        if self._current is not None and event.buttons() & Qt.LeftButton:
            self._current.append((event.position().x(), event.position().y(), time.perf_counter()))
            self.update()

    def mouseReleaseEvent(self, event):
        if self._current is not None and len(self._current) < 2:
            self._strokes.remove(self._current)
        self._current = None
        self.changed.emit()
        self.update()

    def paintEvent(self, event):
        theme = THEME_MANAGER.current
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(_c(theme.border), 1))
        p.setBrush(_c(theme.bg_alt))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.setPen(QPen(_c(theme.border), 1, Qt.DashLine))
        p.drawLine(24, int(self.height() * 0.72), self.width() - 24, int(self.height() * 0.72))
        p.setPen(_c(theme.accent))
        for stroke in self._strokes:
            for i in range(1, len(stroke)):
                p.drawLine(QPointF(stroke[i - 1][0], stroke[i - 1][1]),
                           QPointF(stroke[i][0], stroke[i][1]))
        if not self.has_ink():
            p.setPen(_c(theme.text_faint))
            p.drawText(self.rect(), Qt.AlignCenter, '在此处签名')


class KioskBackground(QWidget):
    """根背景：深色渐变 + 呼吸光晕 + 细网格。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        THEME_MANAGER.themeChanged.connect(lambda _t: self.update())

    def _tick(self):
        if self.isVisible():
            self._phase = (self._phase + 0.012) % (math.pi * 2)
            self.update()

    def paintEvent(self, event):
        theme = THEME_MANAGER.current
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.bg))
        # 左上、右下两团呼吸光
        r1 = QRadialGradient(self.width() * 0.18, self.height() * 0.12, self.width() * 0.55)
        r1.setColorAt(0, _c(theme.accent, int(26 + 10 * math.sin(self._phase))))
        r1.setColorAt(1, _c(theme.accent, 0))
        p.fillRect(self.rect(), QBrush(r1))
        r2 = QRadialGradient(self.width() * 0.9, self.height() * 0.95, self.width() * 0.5)
        r2.setColorAt(0, _c(theme.accent_2, 22))
        r2.setColorAt(1, _c(theme.accent_2, 0))
        p.fillRect(self.rect(), QBrush(r2))
        # 网格
        p.setPen(QPen(_c(theme.accent, 12), 1))
        step = 56
        for x in range(0, self.width(), step):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            p.drawLine(0, y, self.width(), y)
