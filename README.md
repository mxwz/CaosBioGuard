<div align="center">

<img src="logo.png" alt="Caos BioGuard Logo" width="128" />

# Caos BioGuard

**多生物识别考勤与门禁系统 | Multi-Biometric Attendance & Access Control**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PySide6](https://img.shields.io/badge/PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://www.qt.io/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge)](LICENSE)

</div>

## 1. 系统简介

CaosBioGuard 是一套覆盖边缘终端、Web 管理端、PWA/手机端和微信小程序的考勤与门禁系统。系统支持离线本地识别、在线统一管理、云边同步、硬件门锁控制和容器化部署，适用于工厂、园区、社区、实验室和办公场景。

当前内置 9 类生物识别模态：

| 类别 | 模态 |
|---|---|
| 视觉/人脸 | 人脸、虹膜、视网膜、步态、掌纹、签名 |
| 语音 | 声纹 |
| 外部采集器 | 指纹、静脉 |

完整模态为：人脸、声纹、指纹、虹膜、掌纹、静脉、步态、视网膜、签名。人脸链路基于 InsightFace 与 ONNX Runtime；其他模态已完成离线软件接口、模板存储和合成数据链路验证，真实精度需接入对应硬件和厂商 SDK 后评估。

## 2. 架构总览

```text
┌─────────────────────────────┐
│ 边缘 Kiosk：PySide6 + ONNX  │
│ 本地识别 / 活体 / 硬件控制   │
└──────────────┬──────────────┘
               │ SQLite outbox / HMAC / 幂等同步
┌──────────────▼──────────────┐
│ Web 服务：Flask + Waitress   │
│ 人员 / 模板 / 考勤 / 设备 API │
└───────┬──────────────┬──────┘
        │              │
┌───────▼──────┐ ┌─────▼──────────────────────┐
│ PWA/手机端    │ │ 微信小程序：管理员/用户双角色 │
└──────────────┘ └────────────────────────────┘
```

核心目录：

| 路径 | 说明 |
|---|---|
| `biometrics/` | 9 模态识别、融合、活体、模板存储、同步 outbox |
| `sideUI/kiosk/` | PySide6 高科技 Kiosk、Tab 页面、线程池和数据层 |
| `web_admin/` | Flask Web 后台、多模态 API、移动端 API |
| `mobile/` | PWA 与微信小程序 |
| `hardware/` | 门锁、继电器、门磁、出门按钮、报警器硬件抽象 |
| `deployment.py` | 离线/在线、局域网/公网、集成/分离模式校验 |
| `packaging/` | PyInstaller 打包配置 |
| `deploy/` | Dockerfile、Compose、配置模板和部署说明 |

## 3. 部署模式

系统使用三个正交维度描述部署：

- `operation_mode`：`offline` / `online`
- `network_scope`：`lan` / `public`
- `topology`：`integrated` / `separated`

```ini
[Deployment]
operation_mode=offline
network_scope=lan
topology=integrated
public_base_url=
```

典型模式：

| 场景 | 推荐配置 |
|---|---|
| 单机无网门禁 | 离线 + 局域网 + 集成 |
| 多边缘终端、中心统一审计 | 在线/可离线降级 + 局域网 + 分离 |
| 手机端或小程序公网访问 | 在线 + 公网 + 分离，HTTPS 反向代理 |
| 演示或开发 | 仿真硬件 + 离线集成 |

配置校验：

```bash
python deployment.py
```

详见 [部署模式说明](docs/deployment-modes.md)。

## 4. 硬件联动

`hardware/` 提供：

- 仿真继电器：无硬件时联调；
- 串口继电器：按配置发送十六进制开门/关门命令；
- Wiegand26 编码：外部读卡器适配；
- 门磁、出门按钮、报警器和外部读卡器健康状态；
- Kiosk 识别通过后自动调用解锁。

示例：

```ini
[Hardware]
enabled=true
mode=simulator
serial_port=COM3
baudrate=9600
open_command=A0 01 01 A2
close_command=A0 01 00 A1
unlock_duration=3
```

详见 [硬件端设计说明](docs/hardware-design.md)。

## 5. 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-edge.txt
python -m pytest -q
python -m sideUI.kiosk.app
```

Web 服务：

```powershell
pip install -r requirements-web.txt
python -m web_admin.app
```

默认配置适合本地开发。生产环境必须替换默认 token、HMAC secret、管理员 PIN，并在公网模式下启用 HTTPS。

## 6. 打包与 Docker

边缘端可执行文件：

```powershell
pyinstaller packaging/edge_kiosk.spec --clean --noconfirm
```

容器部署：

```bash
docker compose --env-file deploy/docker.env -f deploy/docker-compose.yml up -d
```

相关文件：

- `packaging/edge_kiosk.spec`
- `deploy/Dockerfile`
- `deploy/docker-compose.yml`
- `deploy/deployment.md`

## 7. 文档导航

- [应用说明](docs/application-guide.md)
- [部署模式说明](docs/deployment-modes.md)
- [硬件端设计说明](docs/hardware-design.md)
- [云边同步协议](docs/cloud-edge-sync.md)
- [多生物识别 API](docs/biometrics-api.md)
- [Web 服务端文档](web_admin/README.md)
- [边缘端历史文档](sideUI/README.md)

## 8. 当前能力边界

- 非人脸模态的合成数据验证只证明软件链路可运行，不代表真实硬件精度。
- 指纹、虹膜、掌纹、静脉、视网膜等需要真实采集设备和厂商 SDK。
- 启发式活体不能替代专用 PAD 模型、双目或 3D 防伪设备。
- 仿真继电器不会产生真实开门动作，生产前必须完成真机验收。
- 小程序真机上线需要 AppID、HTTPS 域名和合法服务器域名配置。
- 强电接线、消防联动和现场安装应由具备资质的人员实施。
