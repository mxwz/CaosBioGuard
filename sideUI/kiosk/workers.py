"""边缘端线程模型：采集、推理、通用任务池。

关键约束：
- **推理绝不跑在 Qt 主线程**；UI 只负责贴图与画 HUD。
- 推理队列长度为 1，新帧覆盖旧帧（drop-frame），保证低延迟而不是排队积压。
- 采集、推理各自独立线程；关窗时统一 stop + wait。
"""

from __future__ import annotations

import math
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Slot

from biometrics import FaceLivenessDetector, FacePadGate, LivenessPolicy
from biometrics.base import cosine_similarity

from .data import KioskConfig, SubjectRepository


@dataclass
class FaceResult:
    bbox: Optional[Sequence[float]] = None
    name: str = ''
    score: float = 0.0
    liveness: float = 0.0
    passed: bool = False
    reason: str = ''
    faces: int = 0
    crop: Optional[np.ndarray] = None
    embedding: Optional[np.ndarray] = None
    latency_ms: float = 0.0
    ts: float = field(default_factory=time.time)


class CameraWorker(QThread):
    frameReady = Signal(object)
    statusChanged = Signal(str, bool)

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720, parent=None):
        super().__init__(parent)
        self.index = int(index)
        self.width = width
        self.height = height
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        cap = None
        try:
            backend = cv2.CAP_DSHOW if hasattr(cv2, 'CAP_DSHOW') else cv2.CAP_ANY
            cap = cv2.VideoCapture(self.index, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.index)
            if not cap.isOpened():
                self.statusChanged.emit('摄像头不可用，已切换演示画面', False)
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            fails = 0
            self.statusChanged.emit(f'摄像头 #{self.index} 已连接', True)
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    fails += 1
                    if fails > 30:
                        self.statusChanged.emit('视频流中断', False)
                        break
                    self.msleep(20)
                    continue
                fails = 0
                self.frameReady.emit(frame)
        except Exception as exc:
            self.statusChanged.emit(f'摄像头异常: {exc}', False)
        finally:
            if cap is not None:
                cap.release()
            self.statusChanged.emit('视频流已停止', False)


class DemoStreamWorker(QThread):
    """无摄像头/无模型时的演示流，保证 UI 与交互可完整验收。"""

    frameReady = Signal(object)
    statusChanged = Signal(str, bool)

    def __init__(self, width: int = 1280, height: int = 720, parent=None):
        super().__init__(parent)
        self.width = width
        self.height = height
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        self.statusChanged.emit('演示视频流（未连接摄像头）', True)
        t0 = time.time()
        rng = np.random.default_rng(11)
        noise = rng.normal(0, 2.2, (self.height, self.width, 1)).astype(np.float32)
        while self._running:
            t = time.time() - t0
            img = np.zeros((self.height, self.width, 3), np.uint8)
            # 演播室背景：上暗下亮的渐变 + 地面反光
            top = np.array([10, 12, 18], np.float32)
            bottom = np.array([28, 34, 44], np.float32)
            ramp = np.linspace(0, 1, self.height, dtype=np.float32)[:, None, None]
            img[:] = (top[None, None, :] * (1 - ramp) + bottom[None, None, :] * ramp).astype(np.uint8)
            cv2.rectangle(img, (0, int(self.height * 0.74)), (self.width, self.height),
                          (16, 20, 26), -1)
            cx = int(self.width * (0.5 + 0.035 * math.sin(t * 0.7)))
            body_top = int(self.height * 0.30)
            # 身体
            cv2.ellipse(img, (cx, int(self.height * 0.62)), (int(self.width * 0.10), int(self.height * 0.26)),
                        0, 0, 360, (52, 58, 70), -1)
            # 头
            cv2.circle(img, (cx, body_top), int(self.height * 0.085), (78, 84, 96), -1)
            # 肩线高光
            cv2.ellipse(img, (cx, int(self.height * 0.46)), (int(self.width * 0.105), 22),
                        0, 200, 340, (90, 100, 116), 3)
            # 屏幕扫描光
            y = int((t * 70) % self.height)
            cv2.line(img, (0, y), (self.width, y), (40, 90, 110), 2)
            img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
            self.frameReady.emit(img)
            self.msleep(33)
        self.statusChanged.emit('演示流已停止', False)


class InferenceWorker(QThread):
    """人脸检测 + 活体 + 1:N 识别，全程后台线程。"""

    resultReady = Signal(object)
    statusChanged = Signal(str, bool)

    def __init__(self, repo: SubjectRepository, config: KioskConfig, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.config = config
        self._queue: 'queue.Queue[np.ndarray]' = queue.Queue(maxsize=1)
        self._running = False
        self._model = None
        self._model_error = ''
        self._gate = self._build_gate()
        self._names: list = []
        self._matrix: Optional[np.ndarray] = None
        self._refresh()

    def _build_gate(self) -> FacePadGate:
        mode = self.config.get('Kiosk', 'liveness_mode', 'degraded')
        policy = LivenessPolicy(mode=mode,
                                passive_threshold=self.config.get_float('Kiosk', 'liveness_threshold', 0.72),
                                consecutive=2, ema_alpha=0.55)
        return FacePadGate(FaceLivenessDetector(None, policy), policy)

    def _refresh(self) -> None:
        self._names, self._matrix = self.repo.gallery()

    def refresh_gallery(self) -> None:
        self._refresh()

    def submit(self, frame: np.ndarray) -> None:
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                pass

    def stop(self) -> None:
        self._running = False
        self._queue.put(np.zeros((2, 2, 3), np.uint8))

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sideUI.face_core import get_face_analysis_model
            self._model = get_face_analysis_model()
            self.statusChanged.emit('人脸识别引擎已加载', True)
        except Exception as exc:
            self._model_error = str(exc)
            self.statusChanged.emit(f'人脸引擎不可用：{exc}', False)

    def _recognize(self, emb: np.ndarray) -> tuple:
        if self._matrix is None or not len(self._names):
            return '', 0.0, 1.0
        sims = self._matrix @ emb / (np.linalg.norm(self._matrix, axis=1) * np.linalg.norm(emb) + 1e-9)
        best = int(np.argmax(sims))
        score = float(sims[best])
        second = float(np.sort(sims)[-2]) if len(sims) > 1 else 0.0
        return self._names[best], score, score - second

    def run(self) -> None:
        self._running = True
        self._load_model()
        while self._running:
            try:
                frame = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not self._running:
                break
            if frame is None or frame.size == 0 or frame.shape[0] < 4:
                continue
            t0 = time.perf_counter()
            try:
                res = self._process(frame)
            except Exception as exc:
                res = FaceResult(reason=f'推理异常: {exc}')
                traceback.print_exc()
            res.latency_ms = (time.perf_counter() - t0) * 1000
            self.resultReady.emit(res)

    def _process(self, frame: np.ndarray) -> FaceResult:
        if self._model is None:
            return FaceResult(reason='人脸引擎未加载')
        faces = self._model.get(frame)
        if not faces:
            return FaceResult(faces=0)
        # 取面积最大的人脸
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        bbox = [float(v) for v in face.bbox]
        emb = np.asarray(face.embedding, dtype=np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        crop = None
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            x1, y1 = max(0, x1), max(0, y1)
            crop = frame[y1:y2, x1:x2].copy()
        except Exception:
            pass

        live = self._gate.check(frame, bbox, getattr(face, 'kps', None))
        name, score, margin = self._recognize(emb)
        threshold = self.config.get_float('Kiosk', 'threshold', 0.40)
        matched = bool(name) and score >= threshold and margin >= 0.04
        passed = matched and live.passed
        reason = ''
        if not live.passed:
            reason = '活体未通过'
        elif not matched:
            reason = '未匹配到人员' if score < threshold else '相似度差距过小'
        return FaceResult(bbox=bbox, name=name if matched else '', score=score,
                          liveness=live.score, passed=passed, reason=reason,
                          faces=len(faces), crop=crop, embedding=emb)


class TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class TaskRunner(QRunnable):
    """把注册/删除/同步等阻塞操作丢进 QThreadPool，避免卡 UI。"""

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


_ACTIVE_TASKS = set()


def run_task(pool: QThreadPool, fn: Callable[[], Any],
             on_done: Optional[Callable[[Any], None]] = None,
             on_error: Optional[Callable[[str], None]] = None) -> None:
    runner = TaskRunner(fn)
    _ACTIVE_TASKS.add(runner)
    if on_done:
        runner.signals.finished.connect(on_done)
    if on_error:
        runner.signals.failed.connect(on_error)
    runner.signals.finished.connect(lambda *_: _ACTIVE_TASKS.discard(runner))
    runner.signals.failed.connect(lambda *_: _ACTIVE_TASKS.discard(runner))
    pool.start(runner)
