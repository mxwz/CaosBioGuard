"""PyInstaller 入口：以包方式加载 Kiosk，避免相对导入失效。"""

from __future__ import annotations

import multiprocessing
import sys

from sideUI.kiosk.app import main

if __name__ == '__main__':
    multiprocessing.freeze_support()
    sys.exit(main())
