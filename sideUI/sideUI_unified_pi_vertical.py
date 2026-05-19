#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2026/03/17
# @Author  : Unified Pi Version
# @File    : sideUI_unified_pi.py
# @Desc    : 树莓派整合版，基于 sideUI_unified.py 修改，使用 Picamera2
import logging
import sys
import pyttsx3
import os
import asyncio
import concurrent.futures
import functools

# 设置 OpenCV 环境变量以避免 MSMF 警告
os.environ["OPENCV_VIDEOIO_PRIORITY_MSMF"] = "0"
import hashlib
import configparser
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QLineEdit,
    QGroupBox, QFormLayout, QStatusBar, QProgressBar, QListWidget,
    QDialog, QDialogButtonBox, QAbstractItemView, QComboBox, QStackedWidget, QSplashScreen,
    QGridLayout, QScrollArea, QFrame, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPropertyAnimation, QEasingCurve, Property, QSize, QDateTime, QObject
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QIcon, QFont
import cv2
import numpy as np
from insightface.app import FaceAnalysis
import pickle
from sklearn.neighbors import NearestNeighbors

# 添加活体检测相关导入
import torch
import torchvision.transforms as transforms
import yaml
from collections import OrderedDict
from PIL import Image
import requests

# 树莓派相机导入
import libcamera
from picamera2 import Picamera2

# 默认管理员密码 (admin123 的 MD5)
DEFAULT_ADMIN_PASSWORD_HASH = "0192023a7bbd73250516f069df18b500"

# 全局缓存的人脸识别模型
face_analysis_model = None

# 添加当前目录到Python路径，以便导入models模块
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sideUI'))
# 添加父目录到Python路径，以便导入managers模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from managers import SyncDatabaseManager, AsyncDatabaseManager, ConfigManager, DatabaseLogHandler
except ImportError:
    # Fallback if running from same directory
    from managers import SyncDatabaseManager, AsyncDatabaseManager, ConfigManager, DatabaseLogHandler

import models


class FaceAntiSpoofing:
    def __init__(self, config_path, model_path, arch='moilenetv2'):
        """
        初始化面部反欺诈检测器

        Args:
            config_path (str): 配置文件路径
            model_path (str): 模型文件路径
            arch (str): 模型架构名称
        """
        self.config_path = config_path
        self.model_path = model_path
        self.arch = arch
        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        self.model = self._load_model()

        # 定义预处理操作
        self.normalize = transforms.Normalize(mean=[0.14300402, 0.1434545, 0.14277956],
                                              std=[0.10050353, 0.100842826, 0.10034215])
        self.ratio = 224.0 / float(224)
        self.preprocess = transforms.Compose([
            transforms.Resize(int(256 * self.ratio)),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            self.normalize,
        ])

    def _load_model(self):
        """加载模型"""
        # 检查配置文件和模型文件是否存在
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"模型文件不存在: {self.model_path}")

        # 加载配置文件
        with open(self.config_path, 'r') as f:
            config = yaml.load(f, Loader=yaml.FullLoader)

        # 创建模型
        if "model" in config.keys():
            model = models.__dict__[self.arch](**config['model'])
        else:
            model = models.__dict__[self.arch]()

        # 加载模型权重
        checkpoint = torch.load(self.model_path, map_location=self.device)

        # 处理DataParallel模型保存的state_dict
        state_dict = checkpoint['state_dict'] if 'state_dict' in checkpoint else checkpoint

        new_state_dict = OrderedDict()
        for k, v in state_dict.items():
            # 如果键以"module."开头，则移除"module."
            if k.startswith('module.'):
                name = k[7:]  # 去掉 'module.' 前缀
            else:
                name = k
            new_state_dict[name] = v

        model.load_state_dict(new_state_dict)
        model.to(self.device)
        model.eval()
        return model

    def predict_frame(self, frame):
        """
        对单帧图像进行预测

        Args:
            frame (np.ndarray): 图像数组 (BGR格式)

        Returns:
            str: 预测类别 ('Genuine' 或 'Spoofing')
            np.ndarray: 预测概率
        """
        # 转换颜色空间 BGR -> RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # 转换为PIL Image
        pil_image = Image.fromarray(rgb_frame)
        # 预处理
        input_tensor = self.preprocess(pil_image)
        input_batch = input_tensor.unsqueeze(0)
        input_batch = input_batch.to(self.device)

        # 执行预测
        with torch.no_grad():
            output = self.model(input_batch)
            softmax_output = torch.softmax(output, dim=-1)
            prediction = softmax_output.cpu().numpy()[0]

            # 返回预测类别和概率
            label = 'Genuine' if np.argmax(prediction) == 1 else 'Spoofing'
            return label, prediction


def detect_face(frame):
    """
    使用Haar级联分类器检测人脸

    Args:
        frame (np.ndarray): 输入图像

    Returns:
        list: 包含检测到的人脸位置的列表 [(x, y, w, h), ...]
    """
    # 加载预训练的人脸检测器
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    # 将图像转换为灰度图
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 检测人脸
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30)
    )

    return faces


class LoadingAnimation(QWidget):
    """加载动画窗口"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(300, 200)
        self.setStyleSheet("background-color: #2d2d2d; border-radius: 10px;")
        self.angle = 0

        # 动画文本
        self.loading_texts = ["正在加载模型.", "正在加载模型..", "正在加载模型..."]
        self.text_index = 0

        # 创建布局和标签
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # 添加提示文本
        self.tip_label = QLabel("首次加载约需3分钟，请耐心等待")
        self.tip_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        self.tip_label.setAlignment(Qt.AlignCenter)
        layout.addStretch()  # 添加弹性空间
        layout.addWidget(self.tip_label)

        # 启动动画
        self.animation = QPropertyAnimation(self, b"angle")
        # 圆圈旋转动画间隔（ms）
        self.animation.setDuration(2000)
        self.animation.setStartValue(0)
        self.animation.setEndValue(360)
        self.animation.setLoopCount(-1)  # 无限循环
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.animation.start()

        # 启动文本动画
        self.text_timer = QTimer()
        self.text_timer.timeout.connect(self.update_text)
        self.text_timer.start(500)  # 每500ms更新一次文本

    def update_text(self):
        """更新加载文本"""
        self.text_index = (self.text_index + 1) % len(self.loading_texts)
        # 更新窗口标题来显示文本（我们将在paintEvent中绘制文本）
        self.setWindowTitle(self.loading_texts[self.text_index])
        self.update()  # 触发重绘

    def paintEvent(self, event):
        """绘制旋转动画和文本"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制文字
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        text = self.loading_texts[self.text_index]
        text_rect = painter.boundingRect(self.rect(), Qt.AlignHCenter | Qt.AlignTop, text)
        text_rect.moveTop(30)  # 调整文字位置
        painter.drawText(text_rect, Qt.AlignCenter, text)

        # 绘制旋转圆圈
        painter.translate(self.width() // 2, self.height() // 2 + 20)  # 调整位置避免与文字重叠
        painter.rotate(self.angle)

        # 绘制多个圆点形成加载动画
        for i in range(12):
            painter.save()
            painter.rotate(i * 30)  # 12个点，每个间隔30度
            painter.setBrush(QColor(0, 200, 255, 255 - i * 20))  # 不同透明度
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(60, -5, 10, 10)  # 绘制圆点
            painter.restore()

    def get_angle(self):
        return self._angle

    def set_angle(self, value):
        self._angle = value
        self.update()  # 触发重绘

    # 定义属性
    angle = Property(int, get_angle, set_angle)

    def closeEvent(self, event):
        # 停止所有动画和定时器
        self.animation.stop()
        self.text_timer.stop()
        event.accept()


def preload_face_analysis_model():
    """在UI构建之前预加载人脸识别模型"""
    global face_analysis_model
    if face_analysis_model is None:
        try:
            # 检查GPU是否可用
            ctx_id = -1  # 默认使用CPU
            try:
                import onnxruntime
                providers = onnxruntime.get_available_providers()
                if 'CUDAExecutionProvider' in providers:
                    ctx_id = 0  # 使用GPU
            except ImportError:
                pass  # 没有onnxruntime，继续使用CPU

            # 初始化模型
            face_analysis_model = FaceAnalysis(name='buffalo_l')
            face_analysis_model.prepare(ctx_id=ctx_id, det_size=(640, 640))
            return True, "模型加载成功"
        except Exception as e:
            return False, f"模型加载失败: {str(e)}"
    return True, "模型已缓存"


def get_face_analysis_model():
    """获取人脸分析模型，如果不存在则创建并缓存"""
    global face_analysis_model
    if face_analysis_model is None:
        # 如果模型未加载，则加载模型
        success, message = preload_face_analysis_model()
        if not success:
            raise Exception(message)
    return face_analysis_model


def process_image_for_recognition(image_path):
    """处理上传的图片进行人脸识别"""
    try:
        # 获取预加载的人脸识别模型
        face_app = get_face_analysis_model()

        # 读取图片
        img = cv2.imread(image_path)
        if img is None:
            return None, "无法读取图像文件"

        # 处理图片
        faces = face_app.get(img)

        if len(faces) == 0:
            return None, "未检测到人脸"
        elif len(faces) > 1:
            return None, "检测到多张人脸，请确保图像中只有一张人脸"
        else:
            return faces[0], "成功检测到人脸"
    except Exception as e:
        return None, f"处理图像时出错: {str(e)}"


class CustomImageDialog(QDialog):
    """自定义图片选择对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择图片")
        self.setGeometry(200, 200, 800, 600)
        self.selected_image_path = None
        self.image_buttons = []

        # 创建图片目录（如果不存在）
        self.picture_dir = os.path.join(os.path.expanduser("./"), "picture")
        os.makedirs(self.picture_dir, exist_ok=True)

        self.init_ui()
        self.load_images()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title_label = QLabel("请选择一张图片用于人脸注册")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(title_label)

        # 滚动区域用于显示图片
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.grid_layout = QGridLayout(scroll_widget)
        self.grid_layout.setAlignment(Qt.AlignTop)
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # 按钮区域
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("确定")
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setEnabled(False)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def load_images(self):
        # 支持的图片格式
        supported_formats = ('.png', '.jpg', '.jpeg', '.bmp')

        # 清除现有按钮
        for button in self.image_buttons:
            button.deleteLater()
        self.image_buttons.clear()

        # 获取图片文件
        image_files = []
        try:
            for file in os.listdir(self.picture_dir):
                if file.lower().endswith(supported_formats):
                    image_files.append(file)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"读取图片目录时出错: {str(e)}")
            return

        # 创建图片按钮
        row, col = 0, 0
        for i, filename in enumerate(image_files):
            image_path = os.path.join(self.picture_dir, filename)
            try:
                # 创建按钮
                button = QPushButton()
                button.setFixedSize(150, 150)
                button.setCheckable(True)
                button.clicked.connect(lambda checked, path=image_path, btn=button: self.select_image(path, btn))

                # 加载并缩放图片
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(140, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    button.setIcon(QIcon(pixmap))
                    button.setIconSize(QSize(140, 120))

                # 设置按钮文本（文件名）
                button.setText(filename[:15] + "..." if len(filename) > 15 else filename)
                button.setStyleSheet(
                    "QPushButton {"
                    "   text-align: bottom;"
                    "   padding-top: 5px;"
                    "   background-color: #f0f0f0;"
                    "   border: 1px solid #ccc;"
                    "   border-radius: 5px;"
                    "}"
                    "QPushButton:checked {"
                    "   background-color: #0078d4;"
                    "   color: white;"
                    "}"
                )

                self.grid_layout.addWidget(button, row, col)
                self.image_buttons.append(button)

                col += 1
                if col > 4:  # 每行最多5个按钮
                    col = 0
                    row += 1
            except Exception as e:
                print(f"加载图片 {filename} 时出错: {str(e)}")

    def select_image(self, image_path, clicked_button):
        # 取消其他按钮的选中状态
        for button in self.image_buttons:
            if button != clicked_button:
                button.setChecked(False)

        # 设置选中的图片路径
        self.selected_image_path = image_path
        self.ok_button.setEnabled(True)

    def get_selected_image_path(self):
        return self.selected_image_path


class PasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理员登录")
        self.setModal(True)
        self.setGeometry(300, 300, 300, 150)

        layout = QVBoxLayout(self)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("请输入管理员密码")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel("需要管理员权限才能访问此功能"))
        layout.addWidget(self.password_input)
        layout.addWidget(buttons)

    def get_password(self):
        return self.password_input.text()


class AdminLoginDialog(QDialog):
    def __init__(self, database_manager, parent=None):
        super().__init__(parent)
        self.database_manager = database_manager
        self.face_worker = None
        self.picam2 = None
        self.setWindowTitle("管理员登录")
        self.setModal(True)
        self.setGeometry(300, 300, 350, 250)

        layout = QVBoxLayout(self)

        # 登录方式选择
        self.login_method = QComboBox()
        self.login_method.addItem("密码登录")
        self.login_method.addItem("人脸识别登录")
        self.login_method.currentIndexChanged.connect(self.switch_login_method)

        layout.addWidget(QLabel("选择登录方式:"))
        layout.addWidget(self.login_method)

        # 创建堆叠部件用于切换不同登录界面
        self.stacked_widget = QStackedWidget()

        # 密码登录页面
        self.password_widget = QWidget()
        password_layout = QVBoxLayout(self.password_widget)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("请输入管理员密码")
        self.password_input.returnPressed.connect(self.try_login) # Add return pressed

        password_layout.addWidget(QLabel("管理员密码:"))
        password_layout.addWidget(self.password_input)
        password_layout.addStretch()

        # 人脸识别登录页面
        self.face_widget = QWidget()
        face_layout = QVBoxLayout(self.face_widget)
        self.face_status = QLabel("点击开始人脸识别")
        self.face_status.setAlignment(Qt.AlignCenter)
        self.face_recognize_btn = QPushButton("开始人脸识别")
        self.face_recognize_btn.clicked.connect(self.start_face_recognition)
        self.stop_face_btn = QPushButton("停止识别")
        self.stop_face_btn.clicked.connect(self.stop_face_recognition)
        self.stop_face_btn.setEnabled(False)

        face_layout.addWidget(self.face_status)
        face_layout.addWidget(self.face_recognize_btn)
        face_layout.addWidget(self.stop_face_btn)
        face_layout.addStretch()

        self.stacked_widget.addWidget(self.password_widget)
        self.stacked_widget.addWidget(self.face_widget)

        layout.addWidget(self.stacked_widget)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.try_login)
        buttons.rejected.connect(self.reject)

        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("登录")

        layout.addWidget(buttons)

        self.recognized_admin = None
        self.face_timer = QTimer()
        self.face_timer.timeout.connect(self.update_face_frame)

    def switch_login_method(self, index):
        self.stacked_widget.setCurrentIndex(index)
        if index == 1:  # 人脸识别
            self.ok_button.setEnabled(False)
        else:  # 密码
            self.ok_button.setEnabled(True)

    def try_login(self):
        if self.login_method.currentIndex() == 0:  # 密码登录
            password = self.password_input.text()
            password_hash = hashlib.md5(password.encode()).hexdigest()
            # 验证密码是否为默认密码
            if password_hash == DEFAULT_ADMIN_PASSWORD_HASH:
                self.accept()
            else:
                QMessageBox.warning(self, "认证失败", "密码错误")
        else:  # 人脸识别登录
            if self.recognized_admin:
                # 验证识别到的人是否为管理员
                if self.database_manager.is_admin(self.recognized_admin):
                    self.accept()
                else:
                    QMessageBox.warning(self, "认证失败", "识别到的用户不是管理员")
            else:
                QMessageBox.warning(self, "认证失败", "请先进行人脸识别")

    def start_face_recognition(self):
        try:
            # 获取预加载的人脸识别模型
            self.face_worker = get_face_analysis_model()
            if self.face_worker is None:
                raise Exception("人脸识别模型未正确加载")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            return

        # 启动 Picamera2
        try:
            if self.picam2 is not None:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except:
                    pass
                self.picam2 = None

            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"format": 'RGB888', "size": (640, 480)},
                raw={"format": 'SRGGB12', "size": (1920, 1080)}
            )
            config["transform"] = libcamera.Transform(hflip=0, vflip=1)
            self.picam2.configure(config)
            self.picam2.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法启动摄像头: {str(e)}")
            return

        self.face_recognize_btn.setEnabled(False)
        self.stop_face_btn.setEnabled(True)
        self.face_status.setText("识别中...")
        self.face_timer.start(30)  # 30ms interval

    def stop_face_recognition(self):
        self.face_timer.stop()
        if self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except:
                pass
            self.picam2 = None
        self.face_recognize_btn.setEnabled(True)
        self.stop_face_btn.setEnabled(False)
        self.face_status.setText("点击开始人脸识别")

    def update_face_frame(self):
        if self.picam2 and self.face_worker:
            # 获取新帧 (RGB)
            try:
                frame = self.picam2.capture_array()
                if frame is not None:
                    # frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    frame_bgr = frame
                    
                    # 进行人脸识别
                    faces = self.face_worker.get(frame_bgr)
                    if len(faces) > 0:
                        # 获取最佳匹配
                        best_match, best_similarity, _, _ = self.database_manager.find_best_match(faces[0].embedding)
                        if best_match and best_similarity > 0.6:  # 阈值可调整
                            self.recognized_admin = best_match
                            self.face_status.setText(f"识别成功: {best_match} (相似度: {best_similarity:.2f})")
                            self.ok_button.setEnabled(True)
                            self.stop_face_recognition()
                        else:
                            self.face_status.setText("未匹配到已注册用户")
                    else:
                        self.face_status.setText("未检测到人脸")
            except Exception as e:
                self.face_status.setText(f"识别错误: {str(e)}")

    def closeEvent(self, event):
        self.stop_face_recognition()
        event.accept()

    def reject(self):
        self.stop_face_recognition()
        super().reject()


class SyncFaceAnalysisWorker(QThread):
    frame_processed = Signal(object, list)  # frame, faces
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = None
        self.initialize_face_analysis()
        self.frame = None
        self.running = False

    def initialize_face_analysis(self):
        try:
            # 直接获取预加载的模型，避免重复加载
            self.app = get_face_analysis_model()
        except Exception as e:
            # 如果获取失败，则初始化一个新的模型
            try:
                import onnxruntime
                providers = onnxruntime.get_available_providers()
                if 'CUDAExecutionProvider' in providers:
                    ctx_id = 0  # 使用 GPU
                else:
                    ctx_id = -1  # 使用 CPU
            except ImportError:
                ctx_id = -1

            self.app = FaceAnalysis(name='buffalo_l')
            self.app.prepare(ctx_id=ctx_id, det_size=(640, 640))

    def process_frame(self, frame):
        """处理帧，返回人脸列表。输入应为BGR格式（如果直接从OpenCV读取）或RGB（如果从Picamera2读取并转换）"""
        # 注意：这里我们假设传入的是BGR格式，因为insightface通常期望BGR
        if self.app is not None:
            try:
                faces = self.app.get(frame)
                return faces
            except Exception as e:
                self.error_occurred.emit(str(e))
        return []

    def run(self):
        self.running = True

    def stop(self):
        self.running = False
        
    # 兼容性别名
    def _process_frame_sync(self, frame):
        return self.process_frame(frame)


class AsyncFaceAnalysisWorker(QObject):
    """异步人脸识别工作类"""
    finished = Signal(list)  # faces
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.app = None
        self.initialize_face_analysis()
        
        # 兼容性信号
        self.error_occurred = self.error

    def initialize_face_analysis(self):
        try:
            self.app = get_face_analysis_model()
        except Exception as e:
            print(f"Error initializing face analysis: {e}")

    async def process_frame_async(self, frame):
        """异步处理帧"""
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            try:
                faces = await loop.run_in_executor(executor, self._process_frame_sync, frame)
                return faces
            except Exception as e:
                raise e

    def _process_frame_sync(self, frame):
        """同步处理帧（在执行器中运行）"""
        if self.app is not None:
            try:
                faces = self.app.get(frame)
                return faces
            except Exception as e:
                raise e
        return []
        
    # 兼容 SyncFaceAnalysisWorker API
    def process_frame(self, frame):
        return self._process_frame_sync(frame)

    def stop(self):
        pass

    def wait(self):
        pass


class TTSThread(QThread):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.finished.connect(self.deleteLater)

    def run(self):
        try:
            # 初始化 TTS 引擎
            engine = pyttsx3.init()
            engine.say(self.text)
            engine.runAndWait()
        except Exception as e:
            print(f"TTS Error: {str(e)}")


class FaceRecognitionThread(QThread):
    recognition_result = Signal(str, float, str, str)  # name, similarity, groups, list_type
    error_occurred = Signal(str)

    def __init__(self, database_manager, threshold=0.6, parent=None):
        super().__init__(parent)
        self.database_manager = database_manager
        self.threshold = threshold
        self.embedding = None

    def set_embedding(self, embedding):
        self.embedding = embedding

    def run(self):
        if self.embedding is not None:
            try:
                best_match, best_similarity, groups, list_type = self.database_manager.find_best_match(self.embedding, self.threshold)
                self.recognition_result.emit(best_match if best_match else "未知", best_similarity, groups if groups else 'all', list_type if list_type else 'white')
            except Exception as e:
                self.error_occurred.emit(str(e))


class ManageFacesDialog(QDialog):
    def __init__(self, database_manager, parent=None):
        super().__init__(parent)
        self.database_manager = database_manager
        self.setWindowTitle("管理已注册人脸")
        self.setGeometry(200, 200, 400, 500)

        self.init_ui()
        self.populate_list()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 搜索区域
        search_group = QGroupBox("搜索人脸")
        search_layout = QHBoxLayout(search_group)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入姓名搜索")
        search_layout.addWidget(self.search_input)

        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.search_face)
        search_layout.addWidget(self.search_btn)

        # 人脸列表
        list_group = QGroupBox("已注册人脸列表")
        list_layout = QVBoxLayout(list_group)

        self.faces_list = QListWidget()
        self.faces_list.setSelectionMode(QAbstractItemView.SingleSelection)
        list_layout.addWidget(self.faces_list)

        # 按钮区域
        button_layout = QHBoxLayout()

        self.set_admin_btn = QPushButton("设为管理员")
        self.set_admin_btn.clicked.connect(self.set_as_admin)
        button_layout.addWidget(self.set_admin_btn)

        self.remove_admin_btn = QPushButton("取消管理员")
        self.remove_admin_btn.clicked.connect(self.remove_admin)
        self.remove_admin_btn.setEnabled(False)
        button_layout.addWidget(self.remove_admin_btn)

        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.clicked.connect(self.delete_selected)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)

        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self.populate_list)
        button_layout.addWidget(self.refresh_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        # 连接信号
        self.faces_list.itemSelectionChanged.connect(self.on_selection_changed)

        # 添加到主布局
        layout.addWidget(search_group)
        layout.addWidget(list_group)
        layout.addLayout(button_layout)

    def populate_list(self):
        self.faces_list.clear()
        names = self.database_manager.get_all_names()
        for name in names:
            if self.database_manager.is_admin(name):
                item_text = f"{name} (管理员)"
            else:
                item_text = name
            self.faces_list.addItem(item_text)

    def on_selection_changed(self):
        has_selection = len(self.faces_list.selectedItems()) > 0
        self.delete_btn.setEnabled(has_selection)

        if has_selection:
            selected_text = self.faces_list.selectedItems()[0].text()
            name = selected_text.replace(" (管理员)", "")
            is_admin = self.database_manager.is_admin(name)
            self.remove_admin_btn.setEnabled(is_admin)
            self.set_admin_btn.setEnabled(not is_admin)
        else:
            self.set_admin_btn.setEnabled(False)
            self.remove_admin_btn.setEnabled(False)

    def search_face(self):
        search_term = self.search_input.text().strip()
        if not search_term:
            self.populate_list()
            return

        self.faces_list.clear()
        names = self.database_manager.get_all_names()
        filtered_names = [name for name in names if search_term.lower() in name.lower()]
        for name in filtered_names:
            if self.database_manager.is_admin(name):
                item_text = f"{name} (管理员)"
            else:
                item_text = name
            self.faces_list.addItem(item_text)

    def set_as_admin(self):
        selected_items = self.faces_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请选择一个用户")
            return

        selected_text = selected_items[0].text()
        name = selected_text.replace(" (管理员)", "")

        if self.database_manager.set_as_admin(name):
            QMessageBox.information(self, "成功", f"'{name}' 已设为管理员")
            self.populate_list()
        else:
            QMessageBox.warning(self, "失败", f"设置 '{name}' 为管理员失败")

    def remove_admin(self):
        selected_items = self.faces_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请选择一个用户")
            return

        selected_text = selected_items[0].text()
        name = selected_text.replace(" (管理员)", "")

        if self.database_manager.remove_admin(name):
            QMessageBox.information(self, "成功", f"'{name}' 已取消管理员权限")
            self.populate_list()
        else:
            QMessageBox.warning(self, "失败", f"取消 '{name}' 管理员权限失败")

    def delete_selected(self):
        selected_items = self.faces_list.selectedItems()
        if not selected_items:
            return

        selected_text = selected_items[0].text()
        name = selected_text.replace(" (管理员)", "")

        reply = QMessageBox.question(self, "确认删除", f"确定要删除 '{name}' 的人脸数据吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # Check if this user has faces on this device
            user_faces = self.database_manager.database.get(name, [])
            if not isinstance(user_faces, list):
                user_faces = [user_faces]
                
            local_device_id = self.database_manager.device_id
            has_local = False
            for f in user_faces:
                if f.get('device_id', 'global') == local_device_id:
                    has_local = True
                    break
                    
            if has_local:
                if self.database_manager.delete_face(name, local_device_id):
                    QMessageBox.information(self, "成功", f"已删除 '{name}' 在本机的设备数据")
                    self.populate_list()
                else:
                    QMessageBox.warning(self, "失败", f"删除 '{name}' 的人脸数据失败")
            else:
                # Fallback to delete all or global if it's the only one
                if self.database_manager.delete_face(name):
                    QMessageBox.information(self, "成功", f"已删除 '{name}' 的人脸数据")
                    self.populate_list()
                else:
                    QMessageBox.warning(self, "失败", f"删除 '{name}' 的人脸数据失败")
                
    # 添加公开的刷新方法
    def refresh_data(self):
        self.populate_list()


class FaceComparisonDialog(QDialog):
    """人脸比对对话框"""

    def __init__(self, database_manager, parent=None):
        super().__init__(parent)
        self.database_manager = database_manager
        self.face_worker = None
        self.picam2 = None
        self.current_frame = None
        self.current_embedding = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

        self.setWindowTitle("人脸比对")
        self.setGeometry(200, 200, 1200, 700)
        self.init_ui()

        # 初始化人脸识别模型
        try:
            self.face_worker = get_face_analysis_model()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法加载人脸识别模型: {str(e)}")
            self.close()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 主内容区域
        content_layout = QHBoxLayout()

        # 左侧区域：摄像头和拍摄
        left_panel = QGroupBox("摄像头区域")
        left_layout = QVBoxLayout(left_panel)

        # 摄像头显示区域
        self.camera_label = QLabel("摄像头预览")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setMinimumSize(400, 400)
        self.camera_label.setStyleSheet("background-color: black; border: 2px solid #555;")
        left_layout.addWidget(self.camera_label)

        # 摄像头控制按钮
        camera_controls = QHBoxLayout()
        self.start_camera_btn = QPushButton("打开摄像头")
        self.start_camera_btn.clicked.connect(self.start_camera)
        camera_controls.addWidget(self.start_camera_btn)

        self.stop_camera_btn = QPushButton("关闭摄像头")
        self.stop_camera_btn.clicked.connect(self.stop_camera)
        self.stop_camera_btn.setEnabled(False)
        camera_controls.addWidget(self.stop_camera_btn)

        self.capture_btn = QPushButton("拍照比对")
        self.capture_btn.clicked.connect(self.capture_and_compare)
        self.capture_btn.setEnabled(False)
        camera_controls.addWidget(self.capture_btn)

        left_layout.addLayout(camera_controls)

        # 右侧区域：比对结果
        right_panel = QGroupBox("比对结果")
        right_layout = QVBoxLayout(right_panel)

        # 比对结果布局
        result_layout = QHBoxLayout()

        # 左边：拍摄图片
        captured_group = QGroupBox("拍摄图片")
        captured_layout = QVBoxLayout(captured_group)
        self.captured_label = QLabel("暂无拍摄图片")
        self.captured_label.setAlignment(Qt.AlignCenter)
        self.captured_label.setMinimumSize(300, 300)
        self.captured_label.setStyleSheet("background-color: #f0f0f0; border: 2px solid #ccc;")
        captured_layout.addWidget(self.captured_label)
        result_layout.addWidget(captured_group)

        # 右边：匹配图片
        matched_group = QGroupBox("匹配图片")
        matched_layout = QVBoxLayout(matched_group)
        self.matched_label = QLabel("暂无匹配图片")
        self.matched_label.setAlignment(Qt.AlignCenter)
        self.matched_label.setMinimumSize(300, 300)
        self.matched_label.setStyleSheet("background-color: #f0f0f0; border: 2px solid #ccc;")
        matched_layout.addWidget(self.matched_label)
        result_layout.addWidget(matched_group)

        right_layout.addLayout(result_layout)

        # 比对信息
        info_group = QGroupBox("比对信息")
        info_layout = QFormLayout(info_group)

        self.name_label = QLabel("无")
        info_layout.addRow("姓名:", self.name_label)

        self.similarity_label = QLabel("0.00")
        info_layout.addRow("相似度:", self.similarity_label)

        self.code_label = QLabel("无")
        info_layout.addRow("编码:", self.code_label)

        right_layout.addWidget(info_group)

        # 添加到主布局
        content_layout.addWidget(left_panel, 1)
        content_layout.addWidget(right_panel, 1)

        # 底部按钮
        bottom_layout = QHBoxLayout()

        self.check_images_btn = QPushButton("检查缺失图像")
        self.check_images_btn.clicked.connect(self.check_missing_images)
        bottom_layout.addWidget(self.check_images_btn)

        self.retake_images_btn = QPushButton("补拍缺失图像")
        self.retake_images_btn.clicked.connect(self.retake_missing_images)
        bottom_layout.addWidget(self.retake_images_btn)

        bottom_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(close_btn)

        # 添加到主布局
        layout.addLayout(content_layout)
        layout.addLayout(bottom_layout)

    def start_camera(self):
        """打开摄像头"""
        try:
            if self.picam2 is not None:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except:
                    pass
                self.picam2 = None

            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"format": 'RGB888', "size": (640, 480)},
                raw={"format": 'SRGGB12', "size": (1920, 1080)}
            )
            config["transform"] = libcamera.Transform(hflip=0, vflip=1)
            self.picam2.configure(config)
            self.picam2.start()

            self.timer.start(30)  # 30ms interval
            self.start_camera_btn.setEnabled(False)
            self.stop_camera_btn.setEnabled(True)
            self.capture_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开摄像头失败: {str(e)}")

    def stop_camera(self):
        """关闭摄像头"""
        self.timer.stop()
        if self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except:
                pass
            self.picam2 = None

        self.start_camera_btn.setEnabled(True)
        self.stop_camera_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        self.camera_label.clear()
        self.camera_label.setText("摄像头预览")

    def update_frame(self):
        """更新摄像头画面"""
        if self.picam2:
            frame = self.picam2.capture_array()
            if frame is not None:
                # Picamera2 RGB -> BGR for processing
                # frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                frame_bgr = frame
                self.current_frame = frame_bgr.copy()

                # 处理帧以检测人脸
                if self.face_worker:
                    faces = self.face_worker.get(frame_bgr)

                    # 绘制人脸框
                    for face in faces:
                        bbox = face.bbox.astype(int)
                        cv2.rectangle(frame_bgr, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)

                # 显示帧 (Convert BGR back to RGB for display)
                self.display_frame_on_label(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB), self.camera_label)

    def capture_and_compare(self):
        """拍摄并进行人脸比对"""
        if self.current_frame is None:
            QMessageBox.warning(self, "警告", "没有可用的图像")
            return

        # 处理帧以获取人脸 (Using stored BGR frame)
        if self.face_worker:
            faces = self.face_worker.get(self.current_frame)

            if len(faces) == 0:
                QMessageBox.warning(self, "警告", "未检测到人脸")
                return
            elif len(faces) > 1:
                QMessageBox.warning(self, "警告", "检测到多张人脸，请确保图像中只有一张人脸")
                return

            # 获取人脸特征和位置
            embedding = faces[0].embedding
            bbox = faces[0].bbox.astype(int)
            face_roi_bgr = self.current_frame[bbox[1]:bbox[3], bbox[0]:bbox[2]]

            # 显示拍摄的人脸 (Convert to RGB for display)
            self.display_frame_on_label(cv2.cvtColor(face_roi_bgr, cv2.COLOR_BGR2RGB), self.captured_label)

            # 进行人脸比对
            best_match, best_similarity, _, _ = self.database_manager.find_best_match(embedding)

            if best_match and best_similarity > 0.6:
                # 更新比对信息
                self.name_label.setText(best_match)
                self.similarity_label.setText(f"{best_similarity:.2f}")

                # 尝试加载匹配的人脸图像
                matched_image = self.database_manager.load_face_image(best_match)
                if matched_image is not None:
                    # Matched image is BGR, convert to RGB for display
                    self.display_frame_on_label(cv2.cvtColor(matched_image, cv2.COLOR_BGR2RGB), self.matched_label)
                else:
                    self.matched_label.setText("人脸图像缺失")
            else:
                self.name_label.setText("未知")
                self.similarity_label.setText("0.00")
                self.matched_label.setText("未匹配到人脸")

    def display_frame_on_label(self, frame_rgb, label):
        """在标签上显示帧 (Input is RGB)"""
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)

        # 缩放图片以适应标签
        scaled_pixmap = pixmap.scaled(
            label.width(),
            label.height(),
            Qt.KeepAspectRatio
        )
        label.setPixmap(scaled_pixmap)

    def check_missing_images(self):
        """检查哪些人脸缺少图像"""
        names = self.database_manager.get_all_names()
        missing_images = []

        for name in names:
            if not self.database_manager.check_face_image_exists(name):
                missing_images.append(name)

        if missing_images:
            message = f"以下人脸缺少图像:\n\n" + "\n".join(missing_images)
            QMessageBox.information(self, "缺失图像", message)
        else:
            QMessageBox.information(self, "检查结果", "所有人脸图像都存在")

    def retake_missing_images(self):
        """补拍缺失的人脸图像"""
        names = self.database_manager.get_all_names()
        missing_images = []

        for name in names:
            if not self.database_manager.check_face_image_exists(name):
                missing_images.append(name)

        if not missing_images:
            QMessageBox.information(self, "检查结果", "所有人脸图像都存在，无需补拍")
            return

        # 显示补拍对话框
        # 注意：这里需要确保关闭当前对话框的摄像头，或者让RetakeImagesDialog处理
        # 最好是先停止当前摄像头
        self.stop_camera()
        
        retake_dialog = RetakeImagesDialog(self.database_manager, missing_images, self)
        retake_dialog.exec()

    def closeEvent(self, event):
        """关闭事件处理"""
        self.stop_camera()
        event.accept()


class RetakeImagesDialog(QDialog):
    """补拍缺失人脸图像对话框"""

    def __init__(self, database_manager, missing_names, parent=None):
        super().__init__(parent)
        self.database_manager = database_manager
        self.missing_names = missing_names
        self.current_index = 0
        self.face_worker = None
        self.picam2 = None
        self.current_frame = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

        self.setWindowTitle("补拍人脸图像")
        self.setGeometry(200, 200, 800, 600)
        self.init_ui()

        # 初始化人脸识别模型
        try:
            self.face_worker = get_face_analysis_model()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法加载人脸识别模型: {str(e)}")
            self.close()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 提示信息
        info_label = QLabel(f"共需补拍 {len(self.missing_names)} 个人脸图像")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(info_label)

        # 当前补拍的人名
        self.current_name_label = QLabel(f"当前: {self.missing_names[self.current_index]}")
        self.current_name_label.setAlignment(Qt.AlignCenter)
        self.current_name_label.setStyleSheet("font-size: 14px; font-weight: bold; margin: 10px;")
        layout.addWidget(self.current_name_label)

        # 摄像头显示区域
        self.camera_label = QLabel("摄像头预览")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setMinimumSize(400, 400)
        self.camera_label.setStyleSheet("background-color: black; border: 2px solid #555;")
        layout.addWidget(self.camera_label)

        # 控制按钮
        controls_layout = QHBoxLayout()

        self.start_camera_btn = QPushButton("打开摄像头")
        self.start_camera_btn.clicked.connect(self.start_camera)
        controls_layout.addWidget(self.start_camera_btn)

        self.stop_camera_btn = QPushButton("关闭摄像头")
        self.stop_camera_btn.clicked.connect(self.stop_camera)
        self.stop_camera_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_camera_btn)

        self.capture_btn = QPushButton("拍照保存")
        self.capture_btn.clicked.connect(self.capture_and_save)
        self.capture_btn.setEnabled(False)
        controls_layout.addWidget(self.capture_btn)

        self.skip_btn = QPushButton("跳过")
        self.skip_btn.clicked.connect(self.skip_current)
        controls_layout.addWidget(self.skip_btn)

        layout.addLayout(controls_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(self.missing_names))
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

    def start_camera(self):
        """打开摄像头"""
        try:
            if self.picam2 is not None:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except:
                    pass
                self.picam2 = None

            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"format": 'RGB888', "size": (640, 480)},
                raw={"format": 'SRGGB12', "size": (1920, 1080)}
            )
            config["transform"] = libcamera.Transform(hflip=0, vflip=1)
            self.picam2.configure(config)
            self.picam2.start()

            self.timer.start(30)  # 30ms interval
            self.start_camera_btn.setEnabled(False)
            self.stop_camera_btn.setEnabled(True)
            self.capture_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开摄像头失败: {str(e)}")

    def stop_camera(self):
        """关闭摄像头"""
        self.timer.stop()
        if self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except:
                pass
            self.picam2 = None

        self.start_camera_btn.setEnabled(True)
        self.stop_camera_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        self.camera_label.clear()
        self.camera_label.setText("摄像头预览")

    def update_frame(self):
        """更新摄像头画面"""
        if self.picam2:
            frame = self.picam2.capture_array()
            if frame is not None:
                # Picamera2 RGB -> BGR
                # frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                frame_bgr = frame
                self.current_frame = frame_bgr.copy()

                # 处理帧以检测人脸
                if self.face_worker:
                    faces = self.face_worker.get(frame_bgr)

                    # 绘制人脸框
                    for face in faces:
                        bbox = face.bbox.astype(int)
                        cv2.rectangle(frame_bgr, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)

                # 显示帧 (BGR -> RGB)
                self.display_frame_on_label(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB), self.camera_label)

    def capture_and_save(self):
        """拍摄并保存人脸图像"""
        if self.current_frame is None:
            QMessageBox.warning(self, "警告", "没有可用的图像")
            return

        # 处理帧以获取人脸 (BGR)
        if self.face_worker:
            faces = self.face_worker.get(self.current_frame)

            if len(faces) == 0:
                QMessageBox.warning(self, "警告", "未检测到人脸")
                return
            elif len(faces) > 1:
                QMessageBox.warning(self, "警告", "检测到多张人脸，请确保图像中只有一张人脸")
                return

            # 获取人脸位置
            bbox = faces[0].bbox.astype(int)
            face_roi_bgr = self.current_frame[bbox[1]:bbox[3], bbox[0]:bbox[2]]

            # 保存人脸图像
            name = self.missing_names[self.current_index]
            self.database_manager.save_face_image(name, face_roi_bgr)

            # 更新进度
            self.progress_bar.setValue(self.current_index + 1)

            # 移动到下一个
            self.current_index += 1

            # 检查是否完成
            if self.current_index >= len(self.missing_names):
                QMessageBox.information(self, "完成", "所有缺失的人脸图像已补拍完成")
                self.accept()
            else:
                self.current_name_label.setText(f"当前: {self.missing_names[self.current_index]}")

    def skip_current(self):
        """跳过当前人脸"""
        self.current_index += 1

        # 检查是否完成
        if self.current_index >= len(self.missing_names):
            QMessageBox.information(self, "完成", "补拍过程已完成")
            self.accept()
        else:
            self.current_name_label.setText(f"当前: {self.missing_names[self.current_index]}")

    def display_frame_on_label(self, frame_rgb, label):
        """在标签上显示帧 (RGB)"""
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)

        # 缩放图片以适应标签
        scaled_pixmap = pixmap.scaled(
            label.width(),
            label.height(),
            Qt.KeepAspectRatio
        )
        label.setPixmap(scaled_pixmap)

    def closeEvent(self, event):
        """关闭事件处理"""
        self.stop_camera()
        event.accept()


class SettingsDialog(QDialog):
    def __init__(self, config_manager, database_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.database_manager = database_manager
        self.setWindowTitle("设置")
        self.resize(700, 500)
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # Left Menu (ListWidget)
        self.list_widget = QListWidget()
        self.list_widget.addItem("选项")
        self.list_widget.addItem("网络设置")
        self.list_widget.addItem("系统信息")
        self.list_widget.setFixedWidth(150)
        self.list_widget.setCurrentRow(0)
        self.list_widget.currentRowChanged.connect(self.change_page)
        main_layout.addWidget(self.list_widget)

        # Right Content (StackedWidget)
        self.stacked_widget = QStackedWidget()

        # Page 1: Options
        page1 = QWidget()
        layout1 = QVBoxLayout(page1)

        # Section 1: Pattern Recognition
        label_pattern = QLabel("模式识别")
        label_pattern.setStyleSheet("color: #888888; font-weight: bold; font-size: 14px; margin-top: 10px;")
        layout1.addWidget(label_pattern)

        # Radio Buttons
        radio_layout = QHBoxLayout()
        self.radio_test = QRadioButton("测试")
        self.radio_attendance = QRadioButton("考勤")
        self.radio_access = QRadioButton("门禁")

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_test)
        self.mode_group.addButton(self.radio_attendance)
        self.mode_group.addButton(self.radio_access)

        radio_layout.addWidget(self.radio_test)
        radio_layout.addWidget(self.radio_attendance)
        radio_layout.addWidget(self.radio_access)
        radio_layout.addStretch()
        layout1.addLayout(radio_layout)

        # Initialize selection
        current_mode = self.config_manager.get_mode()
        if current_mode == 'Test':
            self.radio_test.setChecked(True)
        elif current_mode == 'Attendance':
            self.radio_attendance.setChecked(True)
        elif current_mode == 'Access Control':
            self.radio_access.setChecked(True)
        else:
            self.radio_test.setChecked(True)

        # Separator
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        line1.setStyleSheet("background-color: #cccccc;")
        layout1.addWidget(line1)
        
        # Section 2: Startup Mode
        label_startup = QLabel("启动方式 (重启生效)")
        label_startup.setStyleSheet("color: #888888; font-weight: bold; font-size: 14px; margin-top: 10px;")
        layout1.addWidget(label_startup)

        startup_layout = QHBoxLayout()
        self.radio_sync = QRadioButton("同步 (Sync)")
        self.radio_async = QRadioButton("异步 (Async)")
        
        self.startup_group = QButtonGroup(self)
        self.startup_group.addButton(self.radio_sync)
        self.startup_group.addButton(self.radio_async)
        
        startup_layout.addWidget(self.radio_sync)
        startup_layout.addWidget(self.radio_async)
        startup_layout.addStretch()
        layout1.addLayout(startup_layout)

        # Init selection
        start_mode = self.config_manager.get_start_mode()
        if start_mode == 'Async':
            self.radio_async.setChecked(True)
        else:
            self.radio_sync.setChecked(True)

        # Separator
        line_startup = QFrame()
        line_startup.setFrameShape(QFrame.HLine)
        line_startup.setFrameShadow(QFrame.Sunken)
        line_startup.setStyleSheet("background-color: #cccccc;")
        layout1.addWidget(line_startup)

        layout1.addStretch()
        self.stacked_widget.addWidget(page1)

        # Page 4: Network Settings
        page4 = QWidget()
        layout4 = QVBoxLayout(page4)
        
        label_net = QLabel("管理后台连接")
        label_net.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        layout4.addWidget(label_net)
        
        form_layout = QFormLayout()
        self.edit_host = QLineEdit()
        self.edit_port = QLineEdit()
        self.edit_port.setPlaceholderText("5000")
        
        # Load current config
        try:
            web_config = self.config_manager.get_web_admin_config()
            self.edit_host.setText(web_config['host'])
            self.edit_port.setText(str(web_config['port']))
        except AttributeError:
            pass
            
        form_layout.addRow("服务器 IP:", self.edit_host)
        form_layout.addRow("端口:", self.edit_port)
        layout4.addLayout(form_layout)
        
        sync_btn = QPushButton("测试连接并同步配置")
        sync_btn.clicked.connect(self.sync_configuration)
        sync_btn.setFixedSize(150, 30)
        layout4.addWidget(sync_btn)
        
        sync_faces_btn = QPushButton("从服务器同步人脸库")
        sync_faces_btn.clicked.connect(self.sync_faces)
        sync_faces_btn.setFixedSize(150, 30)
        layout4.addWidget(sync_faces_btn)
        
        layout4.addStretch()
        self.stacked_widget.addWidget(page4)

        # System Info Page
        sys_info_page = QWidget()
        sys_info_layout = QVBoxLayout(sys_info_page)
        
        label_sys = QLabel("系统信息")
        label_sys.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        sys_info_layout.addWidget(label_sys)
        
        sys_form_layout = QFormLayout()
        
        device_info = self.database_manager.get_device_info()
        dev_id_text = device_info['device_id'] if device_info else "未知"
        mac_text = device_info['machine_code'] if device_info else "未知"
        reg_time_text = str(device_info['registered_at']) if device_info else "未知"
        
        self.edit_dev_id = QLineEdit(dev_id_text)
        self.edit_dev_id.setReadOnly(True)
        self.edit_mac = QLineEdit(mac_text)
        self.edit_mac.setReadOnly(True)
        self.edit_reg_time = QLineEdit(reg_time_text)
        self.edit_reg_time.setReadOnly(True)
        
        sys_form_layout.addRow("设备 ID:", self.edit_dev_id)
        sys_form_layout.addRow("机器码:", self.edit_mac)
        sys_form_layout.addRow("注册时间:", self.edit_reg_time)
        
        sys_info_layout.addLayout(sys_form_layout)
        sys_info_layout.addStretch()
        self.stacked_widget.addWidget(sys_info_page)

        # Right side layout wrapper
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.addWidget(self.stacked_widget)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setFixedSize(80, 30)
        save_btn.setStyleSheet("background-color: #0078d4; color: white; border: none; border-radius: 4px;")

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setFixedSize(80, 30)
        cancel_btn.setStyleSheet("background-color: #f0f0f0; color: black; border: 1px solid #ccc; border-radius: 4px;")

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)

        right_layout.addLayout(btn_layout)

        main_layout.addWidget(right_container)

    def change_page(self, index):
        self.stacked_widget.setCurrentIndex(index)

    def save_settings(self):
        if self.radio_test.isChecked():
            mode = 'Test'
        elif self.radio_attendance.isChecked():
            mode = 'Attendance'
        elif self.radio_access.isChecked():
            # else:
            mode = 'Access Control'

        self.config_manager.set_mode(mode)
        
        if self.radio_async.isChecked():
            start_mode = 'Async'
        else:
            start_mode = 'Sync'
        
        # Check if startup mode changed
        old_start_mode = self.config_manager.get_start_mode()
        self.config_manager.set_start_mode(start_mode)
        
        # Save Web Admin config
        host = self.edit_host.text()
        port = self.edit_port.text()
        if host and port:
             try:
                self.config_manager.set_web_admin_config(host, port)
             except Exception:
                pass

        msg = "设置已保存"
        if old_start_mode != start_mode:
            msg += "\n启动模式已更改，请重启程序以生效。"
            
        QMessageBox.information(self, "提示", msg)
        self.accept()

    def sync_configuration(self):
        host = self.edit_host.text()
        port = self.edit_port.text()
        if not host or not port:
            QMessageBox.warning(self, "警告", "请输入IP和端口")
            return
            
        try:
            device_id = ""
            parent_window = self.parent()
            if parent_window and hasattr(parent_window, 'database_manager'):
                device_id = parent_window.database_manager.device_id
                
            client_mode = self.config_manager.get_mode()
            client_start_mode = self.config_manager.get_start_mode()
            client_updated_at = self.config_manager.get_config_updated_at()
            
            url = f"http://{host}:{port}/api/sync_config"
            params = {
                'device_id': device_id,
                'client_mode': client_mode,
                'client_start_mode': client_start_mode,
                'client_updated_at': client_updated_at
            }
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    # Update local config
                    self.config_manager.set_mode(data['mode'])
                    self.config_manager.set_start_mode(data['start_mode'])
                    mysql = data['mysql']
                    self.config_manager.set_mysql_config(
                        mysql['host'], mysql['user'], mysql['password'], mysql['database'], mysql['port']
                    )
                    # Also save web admin config
                    self.config_manager.set_web_admin_config(host, port)
                    
                    QMessageBox.information(self, "成功", "配置已同步！请重启程序生效。")
                    self.accept() # Close dialog
                else:
                    QMessageBox.warning(self, "失败", f"同步失败: {data.get('error')}")
            else:
                QMessageBox.warning(self, "失败", f"HTTP错误: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接失败: {str(e)}")

    def sync_faces(self):
        host = self.edit_host.text()
        port = self.edit_port.text()
        if not host or not port:
            QMessageBox.warning(self, "警告", "请输入IP和端口")
            return
            
        try:
            self.setCursor(Qt.WaitCursor)
            parent_window = self.parent()
            if not parent_window or not hasattr(parent_window, 'database_manager'):
                 self.setCursor(Qt.ArrowCursor)
                 QMessageBox.critical(self, "错误", "无法访问数据库管理器")
                 return
                 
            db_manager = parent_window.database_manager
            QApplication.processEvents()
            
            success, msg = db_manager.sync_faces_from_remote(host, port)
            
            self.setCursor(Qt.ArrowCursor)
            
            if success:
                QMessageBox.information(self, "成功", msg)
            else:
                QMessageBox.warning(self, "失败", msg)
                
        except Exception as e:
            self.setCursor(Qt.ArrowCursor)
            QMessageBox.critical(self, "错误", f"同步出错: {str(e)}")



class ArcFaceUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ArcFace 人脸识别系统")
        # 设置全屏、置顶和无边框窗口
        self.setWindowState(Qt.WindowFullScreen)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        # 初始化组件
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # project_root = os.path.dirname(base_dir) # current dir is arcface, which is project root for config
        self.config_manager = ConfigManager(os.path.join(base_dir, "config.ini"))
        
        # 根据配置选择启动模式
        start_mode = self.config_manager.get_start_mode()
        self.is_async = (start_mode == 'Async')
        
        db_path = os.path.join(base_dir, "sideUI", "dd", "face_database.pkl")
        sqlite_path = os.path.join(base_dir, "sideUI", "dd", "records.db")

        # 确保数据库目录存在
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
        except Exception as e:
            print(f"创建数据库目录失败: {e}")

        if self.is_async:
            self.database_manager = AsyncDatabaseManager(database_path=db_path, sqlite_path=sqlite_path)
            self.face_worker = AsyncFaceAnalysisWorker()
        else:
            self.database_manager = SyncDatabaseManager(database_path=db_path, sqlite_path=sqlite_path)
            self.face_worker = SyncFaceAnalysisWorker()
            
        # Configure Database Logging
        db_handler = DatabaseLogHandler(self.database_manager)
        db_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(db_handler)
        
        # Start background sync service
        try:
            self.database_manager.start_sync_service()
            
            # Sync device metadata on startup
            metadata_path = os.path.join(base_dir, "metadata.yaml")
            self.database_manager.sync_device_info(metadata_path)
            
        except Exception as e:
            print(f"Failed to start sync service or update metadata: {e}")
            
        self.recognition_thread = None
        # self.engine = pyttsx3.init()  # 移除主线程初始化，改为在线程中使用
        
        # 添加管理对话框引用
        self.manage_dialog = None

        # 初始化活体检测器
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, "cfgs", "mobilenetv2.yaml")
            model_path = os.path.join(current_dir, "models", "_14_best.pth.tar")
            self.anti_spoofing_detector = FaceAntiSpoofing(config_path, model_path, 'moilenetv2')
        except Exception as e:
            print(f"活体检测模型加载失败: {e}")
            self.anti_spoofing_detector = None

        # 视频相关
        self.picam2 = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.current_frame = None

        # 添加识别状态控制变量
        self.recognition_paused = False  # 识别是否暂停
        self.pause_timer = QTimer()  # 暂停定时器
        self.pause_timer.timeout.connect(self.resume_recognition)
        self.recognition_result_displayed = False  # 是否已显示识别结果

        # 添加结果处理函数
        self.result_handler = self.default_result_handler

        # 设置全局样式表
        self.setStyleSheet("""
                QPushButton {
                    background-color: #3a3a3a;
                    color: white;
                    border: 1px solid #555;
                    border-radius: 5px;
                    padding: 8px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                }
                QPushButton:pressed {
                    background-color: #2a2a2a;
                    border-color: #444;
                }
                QPushButton:disabled {
                    background-color: #2d2d2d;
                    border-color: #444;
                    opacity: 0.6;
                }
            """)

        # 创建UI
        self.init_ui()

        # 连接信号
        if hasattr(self.face_worker, 'error_occurred'):
             self.face_worker.error_occurred.connect(self.handle_error)

    def init_ui(self):
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部标题栏
        title_bar = QWidget()
        title_bar.setStyleSheet("background-color: #2d2d2d;")
        title_bar.setFixedHeight(50)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 0, 10, 0)

        title_label = QLabel("ArcFace 竖屏版")
        title_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
        title_layout.addWidget(title_label)
        
        mode_label = QLabel(f"Mode: {'Async' if self.is_async else 'Sync'}")
        mode_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        title_layout.addWidget(mode_label)
        title_layout.addStretch()

        exit_button = QPushButton("×")
        exit_button.setFixedSize(30, 30)
        exit_button.setStyleSheet(
            "QPushButton { background-color: #ff4d4d; color: white; border-radius: 15px; font-size: 18px; font-weight: bold; }"
            "QPushButton:hover { background-color: #ff3333; }"
        )
        exit_button.clicked.connect(self.close_application)
        title_layout.addWidget(exit_button)

        main_layout.addWidget(title_bar)

        # 堆叠部件 (分页)
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget, 1)

        # ====== 页面 1: 人脸识别 ======
        page_recognition = QWidget()
        page_rec_layout = QVBoxLayout(page_recognition)
        page_rec_layout.setContentsMargins(10, 10, 10, 10)
        page_rec_layout.setSpacing(10)

        self.video_label = QLabel("视频显示区域")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; border-radius: 10px; color: white;")
        self.video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.video_label.setMinimumSize(1, 1)
        page_rec_layout.addWidget(self.video_label, 5)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        page_rec_layout.addWidget(self.progress_bar)

        self.result_label = QLabel("暂无识别结果")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setStyleSheet("font-size: 20px; font-weight: bold; background-color: #333333; color: white; border-radius: 10px; padding: 10px;")
        self.result_label.setMinimumHeight(120)
        page_rec_layout.addWidget(self.result_label, 1)

        rec_controls = QHBoxLayout()
        self.start_camera_btn = QPushButton("开始识别")
        self.start_camera_btn.setFixedHeight(50)
        self.start_camera_btn.clicked.connect(self.start_camera_recognition)
        self.stop_camera_btn = QPushButton("停止识别")
        self.stop_camera_btn.setFixedHeight(50)
        self.stop_camera_btn.clicked.connect(self.stop_camera_recognition)
        self.stop_camera_btn.setEnabled(False)
        rec_controls.addWidget(self.start_camera_btn)
        rec_controls.addWidget(self.stop_camera_btn)
        page_rec_layout.addLayout(rec_controls)

        self.stacked_widget.addWidget(page_recognition)

        # ====== 页面 2: 人脸注册 ======
        page_register = QWidget()
        page_reg_layout = QVBoxLayout(page_register)
        page_reg_layout.setContentsMargins(10, 10, 10, 10)
        page_reg_layout.setSpacing(10)

        self.reg_video_label = QLabel("摄像头预览 (注册)")
        self.reg_video_label.setAlignment(Qt.AlignCenter)
        self.reg_video_label.setStyleSheet("background-color: black; border-radius: 10px; color: white;")
        self.reg_video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.reg_video_label.setMinimumSize(1, 1)
        page_reg_layout.addWidget(self.reg_video_label, 3)

        register_group = QGroupBox("人脸注册")
        register_group.setStyleSheet("QGroupBox { font-size: 16px; font-weight: bold; margin-top: 15px; }")
        register_layout = QVBoxLayout(register_group)
        register_layout.setSpacing(10)

        form_layout = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("输入姓名")
        self.name_input.setFixedHeight(40)
        form_layout.addRow(QLabel("姓名:"), self.name_input)
        register_layout.addLayout(form_layout)

        img_layout = QHBoxLayout()
        self.image_path_label = QLabel("未选择图片")
        self.image_path_label.setWordWrap(True)
        img_layout.addWidget(self.image_path_label, 1)

        self.select_image_btn = QPushButton("选择图片")
        self.select_image_btn.setFixedHeight(40)
        self.select_image_btn.clicked.connect(self.select_image)
        img_layout.addWidget(self.select_image_btn)
        register_layout.addLayout(img_layout)

        btn_layout1 = QHBoxLayout()
        self.register_image_btn = QPushButton("图片注册")
        self.register_image_btn.setFixedHeight(45)
        self.register_image_btn.clicked.connect(self.register_from_image)
        self.register_image_btn.setEnabled(False)
        btn_layout1.addWidget(self.register_image_btn)

        self.register_camera_btn = QPushButton("摄像头注册")
        self.register_camera_btn.setFixedHeight(45)
        self.register_camera_btn.clicked.connect(self.register_from_camera)
        btn_layout1.addWidget(self.register_camera_btn)
        register_layout.addLayout(btn_layout1)

        btn_layout2 = QHBoxLayout()
        self.capture_btn = QPushButton("拍照")
        self.capture_btn.setFixedHeight(45)
        self.capture_btn.clicked.connect(self.capture_image)
        self.capture_btn.setEnabled(False)
        btn_layout2.addWidget(self.capture_btn)

        self.cancel_register_btn = QPushButton("取消录入")
        self.cancel_register_btn.setFixedHeight(45)
        self.cancel_register_btn.clicked.connect(self.cancel_registration)
        self.cancel_register_btn.setEnabled(False)
        btn_layout2.addWidget(self.cancel_register_btn)
        register_layout.addLayout(btn_layout2)

        page_reg_layout.addWidget(register_group, 2)
        self.stacked_widget.addWidget(page_register)

        # ====== 页面 3: 管理与设置 ======
        page_manage = QWidget()
        page_man_layout = QVBoxLayout(page_manage)
        page_man_layout.setContentsMargins(20, 20, 20, 20)

        manage_group = QGroupBox("管理与设置")
        manage_group.setStyleSheet("QGroupBox { font-size: 16px; font-weight: bold; margin-top: 15px; }")
        manage_layout = QVBoxLayout(manage_group)
        manage_layout.setSpacing(20)

        self.face_comparison_btn = QPushButton("人脸比对")
        self.face_comparison_btn.setFixedHeight(60)
        self.face_comparison_btn.clicked.connect(self.open_face_comparison_dialog)
        manage_layout.addWidget(self.face_comparison_btn)

        self.manage_faces_btn = QPushButton("管理已注册人脸")
        self.manage_faces_btn.setFixedHeight(60)
        self.manage_faces_btn.clicked.connect(self.open_manage_faces_dialog)
        manage_layout.addWidget(self.manage_faces_btn)

        self.settings_btn = QPushButton("系统设置")
        self.settings_btn.setFixedHeight(60)
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        manage_layout.addWidget(self.settings_btn)

        page_man_layout.addWidget(manage_group)
        page_man_layout.addStretch()
        self.stacked_widget.addWidget(page_manage)

        # ====== 底部导航栏 ======
        nav_bar = QWidget()
        nav_bar.setStyleSheet("background-color: #1e1e1e;")
        nav_bar.setFixedHeight(70)
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self.nav_btns = []
        nav_items = [("人脸识别", 0), ("人脸注册", 1), ("管理与设置", 2)]

        for text, index in nav_items:
            btn = QPushButton(text)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            btn.setCheckable(True)
            if index == 0:
                btn.setChecked(True)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #aaaaaa;
                    border: none;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton:checked {
                    color: #0078d4;
                    background-color: #2d2d2d;
                    border-top: 3px solid #0078d4;
                }
            """)
            btn.clicked.connect(lambda checked, idx=index: self.switch_page(idx))
            nav_layout.addWidget(btn)
            self.nav_btns.append(btn)

        main_layout.addWidget(nav_bar)

        # 状态栏
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("background-color: #2d2d2d; color: white;")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def switch_page(self, index):
        if self.stacked_widget.currentIndex() != index:
            # Stop camera when leaving page to avoid confusion
            if hasattr(self, 'cap') and self.cap and self.cap.isOpened():
                if hasattr(self, 'registering_name'):
                    self.cancel_registration()
                else:
                    self.stop_camera_recognition()
            elif hasattr(self, 'picam2') and self.picam2:
                if hasattr(self, 'registering_name'):
                    self.cancel_registration()
                else:
                    self.stop_camera_recognition()
                    
        self.stacked_widget.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == index)

    def close_application(self):
        """关闭应用程序，需要管理员验证"""
        # 暂停主摄像头，如果正在运行
        was_running = False
        if self.picam2:
            self.stop_camera_recognition()
            was_running = True

        # 显示管理员登录对话框
        login_dialog = AdminLoginDialog(self.database_manager, self)
        if login_dialog.exec() == QDialog.Accepted:
            # 管理员验证通过，关闭应用程序
            # 清理资源
            self.timer.stop()
            if self.picam2:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except:
                    pass
                self.picam2 = None
            QApplication.quit()
        else:
            # 管理员验证失败，不关闭应用程序
            QMessageBox.warning(self, "退出失败", "需要管理员权限才能退出系统")
            # 如果之前在运行，可以考虑恢复
            # if was_running:
            #     self.start_camera_recognition()

    def select_image(self):
        # 使用自定义图片选择对话框
        dialog = CustomImageDialog(self)
        if dialog.exec() == QDialog.Accepted:
            selected_path = dialog.get_selected_image_path()
            if selected_path:
                self.image_path_label.setText(selected_path)
                self.register_image_btn.setEnabled(True)

    def register_from_image(self):
        # 人脸注册需要管理员权限
        # 暂停摄像头如果开启
        if self.picam2:
            self.stop_camera_recognition()
            
        self.require_admin_auth(self._perform_image_registration)

    def _perform_image_registration(self):
        name = self.name_input.text().strip()
        image_path = self.image_path_label.text()

        if not name:
            QMessageBox.warning(self, "警告", "请输入姓名")
            return

        if image_path == "未选择图片":
            QMessageBox.warning(self, "警告", "请选择图片")
            return

        # 检查姓名是否已存在
        if self.database_manager.name_exists(name):
            reply = QMessageBox.question(self, "确认", f"姓名 '{name}' 已存在，是否覆盖？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return

        # 处理图片注册
        self.status_bar.showMessage("正在处理图片...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

        try:
            # 读取图片
            img = cv2.imread(image_path)
            if img is None:
                raise Exception("无法读取图像文件")

            # 获取人脸特征
            # 注意：图片文件通常是BGR，FaceAnalysis处理BGR
            faces = self.face_worker.process_frame(img)
            if len(faces) == 0:
                QMessageBox.warning(self, "警告", "未检测到人脸，请检查图像质量")
            elif len(faces) > 1:
                QMessageBox.warning(self, "警告", "检测到多张人脸，请确保图像中只有一张人脸")
            else:
                embedding = faces[0].embedding
                # 提取人脸区域
                bbox = faces[0].bbox.astype(int)
                face_roi = img[bbox[1]:bbox[3], bbox[0]:bbox[2]]

                # 同时保存人脸特征和人脸图像
                # 注意：Sync 和 Async 的 add_face 方法已通过别名统一 API
                self.database_manager.add_face(name, embedding, face_roi)
                
                QMessageBox.information(self, "成功", f"人脸 '{name}' 已保存")
                self.status_bar.showMessage("人脸注册成功")
                
                # 刷新管理对话框（如果打开）
                if self.manage_dialog is not None:
                    self.manage_dialog.refresh_data()

                # 显示图片 (Convert BGR to RGB for display)
                self.display_image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        except Exception as e:
            QMessageBox.critical(self, "错误", f"注册失败: {str(e)}")
            self.status_bar.showMessage("人脸注册失败")
        finally:
            self.progress_bar.setVisible(False)

    def register_from_camera(self):
        # 人脸注册需要管理员权限
        # 暂停摄像头如果开启
        if self.picam2:
            self.stop_camera_recognition()
            
        self.require_admin_auth(self._perform_camera_registration)

    def _perform_camera_registration(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "警告", "请输入姓名")
            return

        # 检查姓名是否已存在
        if self.database_manager.name_exists(name):
            reply = QMessageBox.question(self, "确认", f"姓名 '{name}' 已存在，是否覆盖？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return

        # 打开摄像头进行注册
        try:
            if self.picam2 is not None:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except:
                    pass
                self.picam2 = None

            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"format": 'RGB888', "size": (640, 480)},
                raw={"format": 'SRGGB12', "size": (1920, 1080)}
            )
            config["transform"] = libcamera.Transform(hflip=0, vflip=1)
            self.picam2.configure(config)
            self.picam2.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法启动摄像头: {str(e)}")
            return

        self.registering_name = name
        self.timer.start(30)  # 30ms interval
        self.status_bar.showMessage("请将脸部对准摄像头，按'S'键或点击拍照按钮进行拍照注册")

        # 禁用注册按钮防止重复点击，启用拍照按钮
        self.register_camera_btn.setEnabled(False)
        self.start_camera_btn.setEnabled(False)  # 禁用开始检测按钮
        self.capture_btn.setEnabled(True)
        self.cancel_register_btn.setEnabled(True)  # 启用取消录入按钮

    def start_camera_recognition(self):
        try:
            if self.picam2 is not None:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except:
                    pass
                self.picam2 = None

            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"format": 'RGB888', "size": (640, 480)},
                raw={"format": 'SRGGB12', "size": (1920, 1080)}
            )
            config["transform"] = libcamera.Transform(hflip=0, vflip=1)
            self.picam2.configure(config)
            self.picam2.start()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法启动摄像头: {str(e)}")
            return

        # 重置识别状态
        self.recognition_paused = False
        self.recognition_result_displayed = False
        self.pause_timer.stop()
        self.video_label.setStyleSheet("background-color: black;")  # 清除边缘光影

        # 禁用注册相关按钮
        self.select_image_btn.setEnabled(False)
        self.register_camera_btn.setEnabled(False)
        self.register_image_btn.setEnabled(False)
        self.name_input.setEnabled(False)

        self.timer.start(30)  # 30ms interval
        self.start_camera_btn.setEnabled(False)
        self.stop_camera_btn.setEnabled(True)
        self.status_bar.showMessage("人脸识别运行中，按 'q' 键退出")
        # 清除之前的结果
        self.result_label.setText("暂无识别结果")

    def stop_camera_recognition(self):
        self.timer.stop()
        self.pause_timer.stop()  # 停止暂停定时器
        self.recognition_paused = False  # 重置暂停状态
        self.recognition_result_displayed = False  # 重置结果显示状态
        if self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except:
                pass
            self.picam2 = None

        # 启用注册相关按钮
        self.select_image_btn.setEnabled(True)
        self.register_camera_btn.setEnabled(True)
        self.name_input.setEnabled(True)
        # 恢复注册图片按钮状态（根据是否有选择图片）
        image_path = self.image_path_label.text()
        self.register_image_btn.setEnabled(image_path != "未选择图片")

        self.start_camera_btn.setEnabled(True)
        self.stop_camera_btn.setEnabled(False)
        
        self.video_label.clear()
        self.video_label.setText("视频显示区域")
        self.video_label.setStyleSheet("background-color: black; border-radius: 10px; color: white;")
        
        self.reg_video_label.clear()
        self.reg_video_label.setText("摄像头预览 (注册)")
        self.reg_video_label.setStyleSheet("background-color: black; border-radius: 10px; color: white;")
        
        self.status_bar.showMessage("已停止识别")
        # 清除识别结果
        self.result_label.setText("暂无识别结果")

    def update_frame(self):
        if self.picam2:
            try:
                frame = self.picam2.capture_array()
                if frame is not None:
                    # Picamera2 RGB -> BGR for processing and consistency
                    # frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    frame_bgr = frame
                    self.current_frame = frame_bgr.copy()

                    # 处理帧
                    faces = self.face_worker.process_frame(frame_bgr)

                    # 如果在识别模式下，只处理距离屏幕最近的人脸
                    if self.start_camera_btn.isEnabled() == False and not hasattr(self,
                                                                                  'registering_name') and not self.recognition_paused:  # 识别模式
                        if len(faces) > 0:
                            # 找出距离屏幕最近的人脸（面积最大的人脸）
                            closest_face = None
                            max_area = 0
                            for face in faces:
                                bbox = face.bbox.astype(int)
                                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                                if area > max_area:
                                    max_area = area
                                    closest_face = face

                            # 只处理距离屏幕最近的人脸
                            if closest_face is not None:
                                bbox = closest_face.bbox.astype(int)
                                embedding = closest_face.embedding

                                # 绘制边界框
                                cv2.rectangle(frame_bgr, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)

                                # 如果活体检测器可用，进行活体检测
                                if self.anti_spoofing_detector:
                                    try:
                                        # 提取人脸区域
                                        face_roi = frame_bgr[bbox[1]:bbox[3], bbox[0]:bbox[2]]

                                        if face_roi.size > 0:  # 确保人脸区域不为空
                                            # 进行活体检测
                                            label, probability = self.anti_spoofing_detector.predict_frame(face_roi)

                                            # 添加阈值判断，高于75%阈值算作真人
                                            threshold = 0.75
                                            if probability[1] >= threshold:
                                                liveness_label = 'True'
                                                liveness_color = (0, 255, 0)  # 绿色
                                                # 进行人脸识别
                                                self.perform_recognition(embedding, bbox, frame_bgr)
                                            else:
                                                liveness_label = 'False'
                                                liveness_color = (0, 0, 255)  # 红色

                                            # 在图像上显示活体检测结果
                                            cv2.putText(frame_bgr, f"Liveness: {liveness_label}",
                                                        (bbox[0], bbox[1] - 10),
                                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, liveness_color, 2)
                                    except Exception as e:
                                        print(f"活体检测出错: {e}")
                                else:
                                    # 进行人脸识别
                                    self.perform_recognition(embedding, bbox, frame_bgr)
                    else:
                        # 非识别模式或暂停状态下，绘制所有人脸框
                        for i, face in enumerate(faces):
                            bbox = face.bbox.astype(int)
                            # 绘制边界框
                            cv2.rectangle(frame_bgr, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)

                    # 显示帧 (Convert BGR back to RGB for display)
                    self.display_image(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))

                    # 检查是否在注册模式下并按下了'S'键
                    if hasattr(self, 'registering_name'):
                        # 检查是否按下了'S'键
                        key = cv2.waitKey(1) & 0xFF
                        if key == ord('s') or key == ord('S'):  # S键
                            if len(faces) > 0:
                                self.capture_for_registration(faces[0].embedding)
                            else:
                                self.status_bar.showMessage("未检测到人脸，请重试")

                    # 如果未检测到人脸，清除识别结果
                    elif len(faces) == 0 and self.start_camera_btn.isEnabled() == False and not self.recognition_paused:
                        self.result_label.setText("暂无识别结果")
            except Exception as e:
                self.status_bar.showMessage(f"获取帧时出错: {str(e)}")

    def perform_recognition(self, embedding, bbox, frame):
        if self.recognition_thread is None or not self.recognition_thread.isRunning():
            self.recognition_thread = FaceRecognitionThread(self.database_manager)
            self.recognition_thread.recognition_result.connect(self.update_recognition_result)
            self.recognition_thread.error_occurred.connect(self.handle_error)
            self.recognition_thread.set_embedding(embedding)
            self.recognition_thread.start()

    def update_recognition_result(self, name, similarity, groups='all', list_type='white'):
        # 检查是否已显示识别结果，避免重复处理
        if self.recognition_result_displayed:
            return

        # 标记已显示识别结果
        self.recognition_result_displayed = True

        # 识别模式
        mode = self.config_manager.get_mode()
        
        # --- 黑白名单与分组过滤逻辑 ---
        
        # 1. 权限过滤：如果是黑名单，直接拒绝（优先级最高）
        if list_type == 'black':
            self.video_label.setStyleSheet("background-color: black; border-radius: 10px;")
            self.result_label.setText(f"警告: 黑名单用户\n姓名: {name}")
            TTSThread(f"警告，黑名单用户{name}", self).start()
            # 记录拒绝日志
            if hasattr(self.database_manager, 'add_access_record'):
                 self.database_manager.add_access_record(name, "In", "Denied-Blacklist", f"Similarity: {similarity:.2f}")
            
            # 暂停识别
            self.recognition_paused = True
            self.pause_timer.start(3000)
            return

        # 2. 分组过滤
        required_group = None
        if mode == 'Attendance':
            required_group = 'attendance'
        elif mode == 'Access Control':
            required_group = 'access'
            
        is_allowed = True
        if required_group and groups != 'all':
            user_groups = groups.split(',')
            if required_group not in user_groups:
                is_allowed = False
        
        if not is_allowed:
             self.video_label.setStyleSheet("background-color: black; border-radius: 10px;") # 橙色警告
             self.result_label.setText(f"无权限: {name}\n非当前业务组用户")
             TTSThread("无权限", self).start()
             
             self.recognition_paused = True
             self.pause_timer.start(3000)
             return

        # 调用结果处理函数
        self.result_handler()

        # 根据识别结果显示红绿色标志
        if name != "未知":
            # 识别成功，显示绿色标志
            self.video_label.setStyleSheet("background-color: black; border-radius: 10px;")
            self.result_label.setText(f"姓名: {name}\n相似度: {similarity:.2f}")
            if mode == 'Attendance':
                TTSThread(f"{name}打卡成功！", self).start()
                if hasattr(self.database_manager, 'add_attendance_record'):
                    self.database_manager.add_attendance_record(name, "Normal", f"Similarity: {similarity:.2f}")
            elif mode == 'Access Control':
                TTSThread(f"验证成功", self).start()
                if hasattr(self.database_manager, 'add_access_record'):
                    self.database_manager.add_access_record(name, "In", "Allowed", f"Similarity: {similarity:.2f}")

        else:
            # 识别失败，显示红色标志
            self.video_label.setStyleSheet("background-color: black; border-radius: 10px;")
            self.result_label.setText(f"姓名: {name}\n相似度: {similarity:.2f}")
            TTSThread("验证失败", self).start()
            if mode == 'Access Control':
                if hasattr(self.database_manager, 'add_access_record'):
                    self.database_manager.add_access_record("Unknown", "In", "Denied", f"Similarity: {similarity:.2f}")

        # 暂停识别两秒
        self.recognition_paused = True
        self.pause_timer.start(3000)  # 3秒后恢复识别

    def capture_image(self):
        """拍照按钮的处理函数"""
        if hasattr(self, 'registering_name') and self.picam2:
            try:
                frame = self.picam2.capture_array()
                if frame is not None:
                    # Convert to BGR for consistency
                    # frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    frame_bgr = frame
                    faces = self.face_worker.process_frame(frame_bgr)
                    if len(faces) > 0:
                        self.capture_for_registration(faces[0].embedding)
                    else:
                        self.status_bar.showMessage("未检测到人脸，请重试")
                else:
                    self.status_bar.showMessage("无法获取摄像头画面")
            except Exception as e:
                self.status_bar.showMessage(f"拍照出错: {e}")

    def capture_for_registration(self, embedding):
        """捕获当前帧进行注册"""
        if hasattr(self, 'registering_name'):
            name = self.registering_name

            # 获取当前帧
            try:
                frame = self.picam2.capture_array()
                if frame is not None:
                    frame_bgr = frame
                    # 处理帧以获取人脸位置
                    faces = self.face_worker.process_frame(frame_bgr)
                    if len(faces) > 0:
                        # 提取人脸区域
                        bbox = faces[0].bbox.astype(int)
                        face_roi = frame_bgr[bbox[1]:bbox[3], bbox[0]:bbox[2]]
                        # 同时保存人脸特征和人脸图像
                        self.database_manager.add_face(name, embedding, face_roi)
                    else:
                        # 如果无法检测到人脸，只保存特征
                        self.database_manager.add_face(name, embedding)
                else:
                    # 如果无法获取帧，只保存特征
                    self.database_manager.add_face(name, embedding)
            except Exception as e:
                self.status_bar.showMessage(f"注册出错: {e}")
                
            # 刷新管理对话框（如果打开）
            if self.manage_dialog is not None:
                self.manage_dialog.refresh_data()

            # 停止摄像头
            self.stop_camera_recognition()

            # 清理注册状态
            delattr(self, 'registering_name')

            # 更新UI
            self.status_bar.showMessage(f"人脸 '{name}' 注册成功")
            QMessageBox.information(self, "成功", f"人脸 '{name}' 已保存")

            # 启用相关按钮
            self.register_camera_btn.setEnabled(True)
            self.start_camera_btn.setEnabled(True)
            self.capture_btn.setEnabled(False)
            self.cancel_register_btn.setEnabled(False)  # 禁用取消录入按钮

    def display_image(self, frame_rgb):
        """Display RGB image on label"""
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)

        # 缩放图片以适应标签
        current_page = self.stacked_widget.currentIndex()
        target_label = self.video_label if current_page == 0 else self.reg_video_label
        
        scaled_pixmap = pixmap.scaled(
            target_label.width(),
            target_label.height(),
            Qt.KeepAspectRatio
        )

        # 绘制时间戳 (如果不是测试模式)
        mode = self.config_manager.get_mode()
        if mode in ['Attendance', 'Access Control']:
            painter = QPainter(scaled_pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            font = QFont("SimHei", 24, QFont.Bold)
            painter.setFont(font)
            current_time = QDateTime.currentDateTime().toString("yyyy年M月d日 HH:mm:ss")
            painter.setPen(QColor(0, 0, 0))
            painter.drawText(22, 42, current_time)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(20, 40, current_time)
            painter.end()

        target_label.setPixmap(scaled_pixmap)

    def handle_error(self, error_msg):
        QMessageBox.critical(self, "错误", f"发生错误: {error_msg}")
        self.status_bar.showMessage("发生错误")
        self.progress_bar.setVisible(False)

    def default_result_handler(self):
        """默认的结果处理函数，打印111"""
        print(111)

    def resume_recognition(self):
        """恢复识别，清除识别结果和红绿色标志"""
        self.recognition_paused = False
        self.recognition_result_displayed = False
        self.result_label.setText("暂无识别结果")
        self.video_label.setStyleSheet("background-color: black; border-radius: 10px; color: white;")  # 清除边缘光影

    def require_admin_auth(self, callback):
        # 显示新的管理员登录对话框
        login_dialog = AdminLoginDialog(self.database_manager, self)
        if login_dialog.exec() == QDialog.Accepted:
            callback()

    def open_manage_faces_dialog(self):
        # 显示新的管理员登录对话框
        login_dialog = AdminLoginDialog(self.database_manager, self)
        if login_dialog.exec() == QDialog.Accepted:
            # 如果已存在对话框，激活它而不是创建新的
            if self.manage_dialog is not None:
                self.manage_dialog.raise_()
                self.manage_dialog.activateWindow()
            else:
                dialog = ManageFacesDialog(self.database_manager, self)
                self.manage_dialog = dialog

                # 连接对话框关闭事件
                def on_dialog_finished():
                    self.manage_dialog = None

                dialog.finished.connect(on_dialog_finished)
                dialog.show()

    def open_settings_dialog(self):
        # 系统设置需要管理员权限
        login_dialog = AdminLoginDialog(self.database_manager, self)
        if login_dialog.exec() == QDialog.Accepted:
            dialog = SettingsDialog(self.config_manager, self.database_manager, self)
            dialog.exec()

    def open_face_comparison_dialog(self):
        """打开人脸比对对话框"""
        # 暂停摄像头如果开启
        if self.picam2:
            self.stop_camera_recognition()
            
        dialog = FaceComparisonDialog(self.database_manager, self)
        dialog.exec()

    def cancel_registration(self):
        """取消人脸录入"""
        self.stop_camera_recognition()

        # 清理注册状态
        if hasattr(self, 'registering_name'):
            delattr(self, 'registering_name')

        # 更新UI
        self.status_bar.showMessage("已取消人脸录入")

        # 启用相关按钮
        self.register_camera_btn.setEnabled(True)
        self.start_camera_btn.setEnabled(True)
        self.capture_btn.setEnabled(False)
        self.cancel_register_btn.setEnabled(False)  # 禁用取消录入按钮

    def force_quit(self):
        """强制退出程序"""
        # 直接强制退出，不显示任何提示框以避免在程序严重错误时无法退出
        try:
            self.timer.stop()
            if self.picam2:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except:
                    pass
                self.picam2 = None
        except:
            pass

        # 强制退出应用
        try:
            QApplication.instance().quit()
        except:
            sys.exit(0)

    def keyPressEvent(self, event):
        """处理键盘按键事件"""
        # 添加Esc键作为强制退出程序的快捷键
        if event.key() == Qt.Key_Escape:
            self.force_quit()
        # 添加Ctrl+Q作为强制退出程序的快捷键
        elif event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Q:
            self.force_quit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        # 清理资源
        try:
            # Trigger final sync before exit
            if hasattr(self, 'database_manager'):
                print("Performing final data sync before exit...")
                self.database_manager.sync_data_now()
                self.database_manager.stop_sync_service()
        except Exception as e:
            print(f"Error during shutdown sync: {e}")

        self.timer.stop()
        if self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except:
                pass
            self.picam2 = None
        
        # 清理注册状态
        if hasattr(self, 'registering_name'):
            delattr(self, 'registering_name')
        
        if self.face_worker:
            self.face_worker.stop()
            self.face_worker.wait()
            
        event.accept()


class ModelLoadingThread(QThread):
    """模型加载线程"""
    loading_finished = Signal(bool, str)  # success, message

    def run(self):
        success, message = preload_face_analysis_model()
        self.loading_finished.emit(success, message)


# 全局变量保存主窗口实例，防止被垃圾回收
main_window = None


def main():
    app = QApplication(sys.argv)

    # 设置应用程序图标
    icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)
        # Windows特定：确保任务栏图标也更新
        import ctypes
        myappid = 'mycompany.myproduct.subproduct.version'  # 任意字符串
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass  # 在非Windows平台上忽略

    # 设置全屏显示
    # app.setOverrideCursor(Qt.BlankCursor)  # 隐藏鼠标指针

    # 显示加载动画
    loading_animation = LoadingAnimation()
    loading_animation.show()

    # 也为加载动画设置图标
    if os.path.exists(icon_path):
        loading_animation.setWindowIcon(QIcon(icon_path))
    loading_animation.show()

    # 将窗口居中显示
    screen = app.primaryScreen().geometry()
    loading_animation.move(
        (screen.width() - loading_animation.width()) // 2,
        (screen.height() - loading_animation.height()) // 2
    )

    # 启动模型加载线程
    loading_thread = ModelLoadingThread()

    def on_loading_finished(success, message):
        global main_window
        loading_animation.close()
        if not success:
            QMessageBox.critical(None, "错误", message)
            app.quit()
        else:
            main_window = ArcFaceUI()
            main_window.show()

            # 为 MainWindow 设置图标
            if os.path.exists(icon_path):
                main_window.setWindowIcon(QIcon(icon_path))
            main_window.show()

    loading_thread.loading_finished.connect(on_loading_finished)
    loading_thread.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
