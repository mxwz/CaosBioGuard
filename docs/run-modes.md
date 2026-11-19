# 运行流程与模式切换说明

## 1. 首次环境准备

在项目根目录执行。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-edge.txt
```

Web 后台额外依赖：

```powershell
pip install -r requirements-web.txt
```

验证：

```powershell
python -m pytest -q
python deployment.py
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-edge.txt
python -m pytest -q
python deployment.py
```

## 2. 源码运行入口

### 2.1 边缘 Kiosk

```powershell
python -m sideUI.kiosk.app
```

职责：摄像头采集、人脸/多模态识别、活体检测、本地模板库、事件记录、硬件继电器控制。

### 2.2 Web 后台

开发模式：

```powershell
$env:FLASK_ENV='development'
$env:FLASK_PORT='6100'
python -m web_admin.app
```

生产模式：

```powershell
$env:FLASK_ENV='production'
$env:FLASK_PORT='6100'
python -m web_admin.app
```

生产模式使用 Waitress；公网部署仍需 Nginx/Caddy/Traefik 终止 HTTPS。

### 2.3 PWA 手机端

1. 启动 Web 后台。
2. 浏览器打开 `http://<边缘机IP>:6100/mobile/`。
3. 浏览器菜单选择“添加到主屏幕”。

### 2.4 微信小程序

1. 用微信开发者工具打开 `mobile/miniprogram/`。
2. 在 `mobile/miniprogram/utils/api.js` 中配置 API 地址。
3. 真机上线需要 AppID、HTTPS 域名和合法服务器域名。

## 3. 不同部署模式运行流程

### 模式 A：离线 + 局域网 + 服务边缘集成

配置：

```ini
[General]
networkmode=offline

[Deployment]
operation_mode=offline
network_scope=lan
topology=integrated

[Cloud]
enabled=false

[Hardware]
enabled=true
mode=simulator
```

运行：

```powershell
python -m sideUI.kiosk.app
```

流程：本地采集 → 本地质量门控 → 本地模型/SDK 模板匹配 → 本地事件库 → 继电器开门。断网可用，事件进入 outbox。

### 模式 B：离线 + 局域网 + 服务边缘分离

```ini
[General]
networkmode=offline

[Deployment]
operation_mode=offline
network_scope=lan
topology=separated

[Cloud]
enabled=true

[Sync]
endpoint=https://center.example.com/api/sync/events
secret=long-hmac-secret
```

运行：

```powershell
python -m sideUI.kiosk.app
```

流程：边缘端使用本地缓存继续识别；离线期间事件写入 outbox；网络恢复后按 HMAC、幂等键和重试策略补传中心服务。

### 模式 C：在线 + 局域网 + 集成

```ini
[General]
networkmode=online

[Deployment]
operation_mode=online
network_scope=lan
topology=integrated

[Cloud]
enabled=false
```

运行：

```powershell
python -m sideUI.kiosk.app
$env:FLASK_ENV='production'; python -m web_admin.app
```

适合同机 Web 管理、局域网 PWA、小规模单点位。

### 模式 D：在线 + 局域网 + 分离

```ini
[General]
networkmode=online

[Deployment]
operation_mode=online
network_scope=lan
topology=separated

[Cloud]
enabled=true

[Sync]
endpoint=http://center.lan:6100/api/sync/events
secret=long-hmac-secret
```

运行：

1. 中心服务器启动 Web 后台和数据库。
2. 各边缘终端启动 Kiosk。
3. 边缘终端通过内网同步模板和事件。

### 模式 E：在线 + 公网 + 分离

```ini
[General]
networkmode=online

[Deployment]
operation_mode=online
network_scope=public
topology=separated
public_base_url=https://guard.example.com

[WebAdmin]
protocol=https
cors_origins=https://app.example.com

[Cloud]
enabled=true

[Sync]
endpoint=https://guard.example.com/api/sync/events
secret=long-hmac-secret
```

运行：

1. 中心服务监听内网端口，例如 `127.0.0.1:6100`。
2. 反向代理配置 HTTPS 证书并转发到 Web 服务。
3. 边缘 Kiosk 启动并保留本地缓存。
4. PWA/小程序通过 HTTPS 访问。

## 4. Docker 运行

```bash
docker compose --env-file deploy/docker.env -f deploy/docker-compose.yml up -d
```

配置文件从 `deploy/config.docker.ini.example` 复制，按上述模式修改后挂载。Docker 适合中心 Web 服务；真实电锁和摄像头通常仍在边缘终端侧接入。

## 5. Windows 打包

### 5.1 构建 exe

```powershell
pip install -r requirements-edge.txt -r requirements-build.txt
.\packaging\build_windows.ps1 -Clean
```

产物：

```text
dist/CaosBioGuardKiosk/CaosBioGuardKiosk.exe
```

这是 PyInstaller 单目录包，不是单文件 exe。单目录启动更快，也更适合模型、Qt 和硬件依赖。

### 5.2 Inno Setup 安装包

先安装 Inno Setup，然后执行：

```powershell
ISCC packaging/windows_installer.iss
```

产物：

```text
dist/installer/CaosBioGuardKioskSetup.exe
```

仓库已提供 `packaging/windows_installer.iss`。如果当前机器未安装 Inno Setup，只能生成 PyInstaller 目录，不能生成安装程序。

## 6. Android APK 说明

当前项目的边缘端是 PySide6，PyInstaller 不能直接生成 APK。手机端当前形态是 PWA 和微信小程序。

若需要原生 APK，推荐低成本路线：

1. 基于现有 `mobile/` Web/PWA；
2. 使用 Capacitor 包装；
3. 安装 Android Studio、JDK 和 Android SDK；
4. 执行 `npx cap add android`、`npx cap sync`、`./gradlew assembleDebug`。

当前环境未安装 JDK/Android SDK，因此尚未生成 APK。另一条路线是 Qt for Android 或 Flutter/React Native 重写，成本明显更高。

## 7. 启动后检查

```powershell
python deployment.py
python -m pytest -q
pip check
```

检查项：

- 模型是否可加载；
- 摄像头和采集器是否在线；
- 公网模式是否 HTTPS；
- SDK 不可用时是否允许模型回退；
- 同步端点和 HMAC secret 是否一致；
- 硬件是否处于 simulator/serial 正确模式。
