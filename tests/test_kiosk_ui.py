"""Kiosk UI 冒烟测试（offscreen，无需摄像头/模型）。

验证：主壳可构建、5 个页面可切换、主题热切换、管理员导航默认隐藏。
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui_kit import THEME_MANAGER, theme_names  # noqa: E402
from sideUI.kiosk.app import KioskWindow  # noqa: E402


class _HeadlessWindow(KioskWindow):
    def _start_threads(self) -> None:  # 测试不启动采集/推理线程
        self._camera = None
        self._demo = None
        self._inference = None


class KioskUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        THEME_MANAGER.apply(self.app, 'obsidian')
        self.win = _HeadlessWindow()
        self.win.resize(1280, 800)
        self.win.show()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def test_pages_and_nav(self):
        self.assertEqual(self.win.pages.count(), 5)
        self.assertFalse(self.win.nav._buttons[4].isVisible())
        for idx in (1, 2, 3):
            self.win.nav.set_current(idx)
            self.win._switch_page(idx)
            self.app.processEvents()
            self.assertEqual(self.win.pages.currentIndex(), idx)

    def test_admin_gate(self):
        self.win._on_unlocked()
        self.assertTrue(self.win._admin_unlocked)
        self.assertTrue(self.win.nav._buttons[4].isVisible())
        self.assertEqual(self.win.pages.currentIndex(), 4)
        self.win._lock_admin()
        self.assertFalse(self.win._admin_unlocked)
        self.assertFalse(self.win.nav._buttons[4].isVisible())
        self.assertEqual(self.win.pages.currentIndex(), 0)

    def test_theme_switch(self):
        for key, _name in theme_names():
            THEME_MANAGER.apply(self.app, key)
            self.app.processEvents()
            self.assertTrue(self.app.styleSheet())
            self.assertEqual(THEME_MANAGER.current.key, key)

    def test_multimodal_modalities(self):
        page = self.win.multimodal
        self.assertEqual(len(page.registry.specs()), 9)
        page._select_modality(4)  # palmprint
        self.assertEqual(page._current, 'palmprint')
        self.assertFalse(page.enroll_btn.isEnabled())


if __name__ == '__main__':
    unittest.main(verbosity=2)
