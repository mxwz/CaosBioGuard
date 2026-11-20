# 环境安装与配置说明

本文面向管理员和部署人员，说明 CaosBioGuard 的虚拟环境、依赖、密钥、端口和运行配置。普通用户通常只需要访问管理员提供的 Web/PWA/小程序地址，不需要自行安装 Python 环境。

## 1. 最小与推荐配置

### 最小配置

- 操作系统：Windows 10/11 x64、Ubuntu 20.04+ x64、可用的 Linux ARM64 边缘设备
- CPU：2 核
- 内存：2 GB
- 磁盘：10 GB 可用空间
- 摄像头：普通 USB 摄像头或兼容 UVC 的摄像头
- 网络：局域网；离线模式可无外网

说明：2C2G 可运行仿真硬件、轻量模态和基础 Web 服务；InsightFace 人脸模型、多模态同时运行或 Docker 部署时会比较紧张。

### 推荐配置

- CPU：4 核及以上
- 内存：8 GB
- 磁盘：20 GB 以上 SSD
- 摄像头：1080P、自动曝光稳定、支持近红外或双目更佳
- 网络：千兆局域网；公网部署需域名和 HTTPS

## 2. Python 与虚拟环境

当前推荐 Python 3.13。不要复用从其他机器迁移来的 `.venv`，应重新创建。

### Windows PowerShell

```powershell
cd C:\Users\18229\Documents\work\py\CaosBioGuard
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements/requirements.txt
```

如果 PowerShell 阻止激活脚本，可执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Linux/macOS

```bash
cd /path/to/CaosBioGuard
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements/requirements.txt
```

## 3. 密钥与敏感配置

禁止把真实密码、Token、HMAC Secret、云存储密钥写入代码或模板文件。优先使用环境变量，也可使用本机未入库的 `config.ini`。

### 主要环境变量

| 变量 | 用途 |
|---|---|
| `CAOS_FLASK_SECRET_KEY` | Flask 会话签名密钥 |
| `CAOS_SYNC_TOKEN` | 云边同步 Bearer Token |
| `CAOS_AGENT_TOKEN` | Agent 接口 Bearer Token |
| `CAOS_HMAC_SECRET` | 同步请求 HMAC 签名密钥 |
| `CAOS_ENCRYPTION_KEY` | 生物模板和原始采集样本加密密钥 |

生成 Fernet 密钥：

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

生产环境缺少 Flask 密钥或模板加密密钥时，系统应拒绝启动或拒绝写入，不允许静默降级为明文。

## 4. 端口配置

Web 管理端默认使用非常用端口：

- 默认端口：`6100`
- 默认地址：`http://127.0.0.1:6100`

可在 `[WebAdmin]` 中修改：

```ini
[WebAdmin]
host = 0.0.0.0
port = 6100
protocol = http
```

局域网访问时可监听 `0.0.0.0`，但应配合防火墙、登录限速和强 Token。公网访问建议使用 HTTPS 反向代理，并在云安全组或防火墙中限制来源。

## 5. 常用运行方式

### 边缘 Kiosk

```powershell
python -m sideUI.kiosk.app
```

### Web 管理端

```powershell
python -m web_admin.app
```

### 运行测试

```powershell
python -m pytest -q
python -m compileall -q .
python -m pip check
```

### 部署模式校验

```powershell
python deployment.py --validate
```

### Docker Compose

```powershell
Copy-Item .env.example .env
# 编辑 .env，填入强密码、Token 和 Fernet key
docker compose config
docker compose up -d
```

Docker 模式下 MySQL 不向宿主机发布 3306，Web 默认只绑定 `127.0.0.1:6100`。需要局域网访问时，将 `.env` 中的 `WEB_BIND_ADDRESS` 改为 `0.0.0.0`，并确认防火墙策略。

## 6. HTTPS 与反向代理

局域网测试可以使用 HTTP；公网模式应启用 HTTPS。HTTPS 可作为可选项接入，不与应用强绑定。

常见方式：

- Cloudflare 证书或腾讯云免费证书
- Nginx / Caddy / Traefik 反向代理
- 后端继续监听 `127.0.0.1:6100`
- 公网 443 端口转发到内部 `6100`

公网部署还应配置：

- 安全组仅放行必要端口
- 可选管理后台 IP 白名单
- 强密码和登录失败锁定
- HMAC/Bearer 机器接口鉴权
- 日志审计和定期备份

## 8. 配置检查清单

上线前至少确认：

- 已重新创建当前机器可用的 `.venv`
- `pip check` 无冲突
- 全量测试通过
- 真实密钥未写入代码
- 模板和原始采集样本已加密
- Web 端口不是默认弱配置或已做访问控制
- 公网模式已启用 HTTPS
- 离线、在线、局域网、公网、集成、分离模式均已按实际场景验证
- 备份、回退、注销封存和管理员锁定流程可正常使用
