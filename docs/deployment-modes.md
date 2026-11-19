# 部署模式说明

CaosBioGuard 使用三个正交维度描述部署形态，避免把“有没有网、在哪个网络、服务是否拆开”混在一个开关里。

## 1. 三个维度

| 维度 | 取值 | 含义 |
|---|---|---|
| `operation_mode` | `offline` / `online` | 离线本地识别，或在线访问中心服务 |
| `network_scope` | `lan` / `public` | 局域网内访问，或通过公网域名访问 |
| `topology` | `integrated` / `separated` | 边缘终端集成 Web/存储，或边缘与中心服务分离 |

配置入口：

```ini
[Deployment]
operation_mode=offline
network_scope=lan
topology=integrated
public_base_url=
```

没有 `[Deployment]` 段时，系统会从旧字段 `General.networkmode`、`WebAdmin.protocol`、`Cloud.enabled` 推导，保证旧配置可继续启动。

## 2. 推荐部署组合

### 2.1 离线局域网集成：单机门禁/考勤机

```ini
[General]
networkmode=offline

[Deployment]
operation_mode=offline
network_scope=lan
topology=integrated

[Cloud]
enabled=false
```

- 权威数据：边缘机本地 SQLite、本地人脸/多模态文件。
- 识别链路：摄像头/采集器 → 本地算法 → 本地模板库 → 继电器开门。
- 网络要求：断网可用；管理后台仅在局域网内访问。
- 同步策略：事件写入 outbox，恢复网络后再批量同步。
- 适用：单门、单车间、社区单点位、临时工地。

### 2.2 离线局域网分离：边缘缓存 + 中心权威

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

- 中心服务正常时负责权威库、管理和审计；边缘断网时使用本地缓存继续识别。
- 离线期间的考勤、拒绝、开门、报警事件进入 outbox。
- 网络恢复后按 HMAC 签名、幂等键和重试策略补传。
- 适用：多门禁点、园区/工厂内网、中心机房统一管理。

### 2.3 在线局域网集成

```ini
[Deployment]
operation_mode=online
network_scope=lan
topology=integrated
```

- 边缘机同时提供本地 Web 管理和识别服务。
- 局域网内电脑、PWA 或内网手机可访问。
- 不依赖公网域名和云端数据库。
- 适合小规模、单点位或 PoC 验证。

### 2.4 在线局域网分离

```ini
[Deployment]
operation_mode=online
network_scope=lan
topology=separated
```

- 中心服务部署在局域网服务器，多个边缘终端通过内网同步。
- 中心侧使用 MySQL、对象存储或兼容 S3 服务。
- 适合多设备、多部门、多门禁点的生产内网。

### 2.5 在线公网分离：手机端/小程序/多站点统一管理

```ini
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

- 公网 TLS 必须由 Nginx、Caddy、Traefik 或云负载均衡终止。
- Flask/Waitress 不直接暴露公网，也不把 `0.0.0.0` 当作公网地址。
- 小程序、PWA、Web 管理端通过 HTTPS 访问。
- 边缘终端仍保留本地缓存，公网中断时可按配置降级离线识别。

## 3. 不推荐或禁止的组合

| 组合 | 结论 | 原因 |
|---|---|---|
| `offline + public + any` | 禁止 | 公网服务需要在线监听；离线只能作为公网中断后的降级状态 |
| `public + http` | 禁止 | 管理 token、人员信息和移动端流量不能明文传输 |
| `separated + Cloud.enabled=false` | 禁止 | 分离模式没有中心权威存储，语义冲突 |
| `integrated + Cloud.enabled=true` | 禁止 | 集成模式以本地为权威，同时启用云端会造成双权威 |
| `public + separated + HTTP sync` | 禁止 | 同步载荷含考勤和设备事件，必须 HTTPS + HMAC |

## 4. 配置校验

运行：

```bash
python deployment.py
```

输出包含：

- `storage`：当前权威存储语义；
- `capabilities`：本地识别、离线缓存、HMAC 同步、TLS、公网 PWA 等能力；
- `warnings`：可启动但需要关注的风险；
- `errors`：阻断生产部署的配置错误。

退出码为 `0` 表示无错误；存在错误时退出码为 `1`，可接入 CI/CD 或部署脚本。

## 5. 降级与恢复原则

1. 在线分离模式下，边缘终端必须保留本地模板和最近事件缓存。
2. 网络中断时，根据 `Kiosk.liveness_mode` 与部署安全策略选择本地识别或只读告警。
3. 离线期间所有事件写入本地 outbox，不覆盖中心权威库。
4. 网络恢复后先做人员/模板版本对账，再补传事件。
5. 公网模式必须启用 HTTPS、强 token、CORS 白名单、HMAC 密钥和最小权限账号。
