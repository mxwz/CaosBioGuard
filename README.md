<div align="center" markdown="1">

<img src="logo.png" alt="Caos BioGuard Logo" width="128" />

# 🔮 Caos BioGuard
**智能分布式人脸门禁与考勤管理系统 | Distributed Face Recognition System**

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PySide6](https://img.shields.io/badge/PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://www.qt.io/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge)](LICENSE)

> 基于 `InsightFace` 和 `PyTorch` 的高性能人脸识别系统。完美融合了 **云端集中管理** 与 **边缘实时计算**，支持跨平台（PC/树莓派）部署，为您打造极具未来感的无感通行与考勤体验。

[**English Version**](README_en.md) | [**进入服务端文档**](web_admin/README.md) | [**进入边缘端文档**](sideUI/README.md)

</div>

---

## 🧭 系统导航 (Documentation Portal)

本系统采用彻底的**云边解耦**架构，为了提供最清晰的指引，我们将文档拆分为了两个专属的独立模块。请根据您的需求进入对应的文档查看详细说明与部署指南：

### ☁️ [Web 服务端 (Web Admin Server) ➔](web_admin/README.md)
系统的“大脑”。提供全局可视化大屏、人员特征统管、考勤与门禁日志分析、设备参数远程下发配置等功能。
- 架构：`Flask` + `MySQL` + `Jinja2`
- 适用场景：云服务器、本地数据中心

### 👁️ [边缘识别端 (Edge AI Device) ➔](sideUI/README.md)
系统的“感官”。部署在闸机或物理入口，提供毫秒级离线人脸识别、活体防伪拦截、实时语音播报与异步断网缓存功能。
- 架构：`PySide6` + `InsightFace` + `PyTorch` + `SQLite`
- 适用场景：Windows PC、带摄像头的 x86 主机、树莓派 (Raspberry Pi)

---

## 🔗 云边端协同架构

系统在数据同步与存储上做了大量深度优化，即使在弱网环境下也能稳定运行。

- **🗄️ 混合存储模型**：边缘端采用 `SQLite` + 本地图片哈希存储，保证毫秒级鉴权响应；服务端依托 `MySQL` 进行海量数据持久化。
- **📡 双向数据同步 (Bi-directional Sync)**：
  - **上行**：边缘端产生的考勤记录、门禁日志、活体检测报警通过后台线程平滑上传至服务器。
  - **下行**：服务端下发的配置更改、新注册人脸、设备管理员权限、软删除指令实时下发至对应的边缘设备。
- **🛡️ 数据隔离与安全**：引入 `device_id` 机制，不同的边缘设备只拉取属于自己的人脸特征与配置，实现终端数据的物理隔离。全局软删除机制防止误删数据丢失。

---

## 📊 竞品分析与功能优势

与其他常见的门禁考勤方案相比，本系统在架构设计与功能扩展性上具有显著优势：

| 功能维度 | 🔮 Caos BioGuard (本系统) | 传统 IC/NFC 门禁系统 | 纯云端人脸识别 API |
| :--- | :--- | :--- | :--- |
| **识别方式** | 人脸 | 卡片/NFC | 图片/视频流 |
| **边缘计算** | √ | × | × |
| **活体检测** | √ | × | × |
| **离线可用性** | √ | √ | × |
| **云端集中管控** | √ | × | √ |
| **硬件成本** | 低 | 中 | 高 |
| **二次开发** | 高 | 低 | 中 |

---

## 🗺️ 未来规划 (Roadmap)

我们致力于将系统打造为**软硬件结合的多生物特征综合感知与管理平台**。未来将不仅局限于考勤与门禁，更将向广阔的 AIoT 场景延伸：

- **🧬 多生物特征融合 (Multi-Biometrics)**：引入指纹、掌静脉、虹膜、声纹等识别模态，支持多因子组合认证（如人脸+掌静脉），满足极高安全场景需求。
- **🤖 大模型与多模态交互 (LLM Integration)**：接入本地或云端大语言模型，赋予边缘终端智能语音问答、访客接待、无障碍语音引导等前沿能力。
- **🌐 全场景 IoT 联动 (IoT Ecosystem)**：扩展 MQTT 等物联网协议，联动智能家居、楼宇自控、环境监测、安防监控等海量外围设备。

---

## 🛠️ 环境依赖注意事项 (Environment & Dependencies)

本项目依赖 `PyTorch` 进行模型推理：
- **GPU 版本（推荐）**：请务必前往 [PyTorch 官网 (https://pytorch.org/)](https://pytorch.org/) 自行安装对应的 GPU 版本，以确保最佳性能。
- **CPU 版本**：如果您使用纯 CPU 环境，请务必自行安装 `onnx` 的 CPU 版本以及 `PyTorch` 的 CPU 版本，否则可能会遇到运行报错。

> 💡 **边缘端数据库配置提示**：
> 边缘端（SideUI）在连接服务端的 MySQL 数据库时，**请勿使用**服务端的 `127.0.0.1` 或 `localhost`（这会指向边缘设备自己）。您必须使用服务端在**局域网（LAN IP）**或**公网（Public IP）**上的真实 IP 地址，确保边缘端能够正确跨网络连接到服务端数据库。

---

## 🔖 版本号管理 (Version Management)

整个项目的版本号统一由根目录 **[version.py](version.py)** 维护，避免版本号散落多处。其它模块（如 `managers.py`、`metadata.yaml`）一律引用它，发版时**只需修改 `version.py` 末尾的 `CURRENT_VERSION` 一处**即可。

版本号遵循语义化版本 `v{major}.{minor}.{patch}`，并区分两种版本形态：

| 形态 | 示例 | 说明 |
| :--- | :--- | :--- |
| **正式版 (Release)** | `v0.1.3` | 功能完善且无严重漏洞的版本 |
| **预览版 (Beta)** | `v0.1.3-beta` | 后续可能推出的内测版 |

```python
# version.py 末尾
CURRENT_VERSION = VersionInfo(0, 1, 3)                         # 正式版 v0.1.3
CURRENT_VERSION = VersionInfo(0, 1, 3, ReleaseType.BETA)       # 预览版 v0.1.3-beta
CURRENT_VERSION = VersionInfo(0, 1, 3, ReleaseType.DEV)        # 开发版 v0.1.3-dev
```

---

## 🔐 配置文件与隐私字段说明 (Configuration & Privacy)

项目的**密钥、数据库密码、访问令牌**等隐私信息统一存放在以下本地配置文件中。**这些文件严禁上传到公开仓库**（请加入 `.gitignore`）。若仓库未包含这些文件（例如首次部署 / 从源码重建），你需要按下方字段自行创建，否则服务无法正常初始化。

### 1. 根目录 `config.ini`

| 键 | 说明 | 是否隐私 |
| :--- | :--- | :--- |
| `[General] mode` | 业务模式（Attendance / Access） | 否 |
| `[General] startmode` | 启动模式（Sync 等） | 否 |
| `[General] syncinterval` | 数据同步间隔（秒） | 否 |
| `[General] networkmode` | 网络模式（Online / Offline） | 否 |
| `[Cloud] enabled` | 云边分离模式开关（true / false） | 否 |
| `[Cloud] host / user / database` | 云端数据库连接信息 | 否 |
| `[Cloud] password` | 云端数据库密码 | **隐私** |
| `[MySQL] host / user / database / port` | MySQL 连接信息 | 否 |
| `[MySQL] password` | MySQL 密码 | **隐私** |
| `[S3] endpoint` | R2/S3 端点（**不含** bucket 路径） | 否 |
| `[S3] access_key / secret_key` | R2/S3 API 访问令牌 | **隐私** |
| `[S3] bucket` | 存储桶名称 | 否 |
| `[S3] region` | 区域（Cloudflare R2 固定填 `auto`） | 否 |
| `[Security] encryptionkey` | 人脸特征加密密钥（Fernet） | **隐私** |
| `[WebAdmin] host / port` | 后台监听地址 / 端口 | 否 |
| `[WebAdmin] protocol` | 访问协议（http / https，默认 http） | 否 |
| `[WebAdmin] token / salt` | 后台登录令牌（哈希）与盐 | **隐私** |
| `[WebAdmin] sessiontimeout` | 登录会话空闲超时（分钟，默认 10） | 否 |
| `[Templates]` / `[Enums]` | 业务模板与枚举字典 | 否 |

### 2. `web_admin/.env`

由 `web_admin/app.py` 通过 `load_dotenv` 读取，用于设置 Flask 运行环境：

| 键 | 说明 | 默认值 | 是否隐私 |
| :--- | :--- | :--- | :--- |
| `FLASK_PORT` | 后台监听端口 | `5000` | 否 |
| `FLASK_ENV` | 运行环境（development / production） | `development` | 否 |

> 💡 上述 `access_key`、`secret_key`、`password`、`token`、`salt`、`encryptionkey` 均为敏感信息，提交代码或打包分发前请务必移除 / 脱敏。

### 3. 快速配置模板（复制即用）

将下面内容保存为根目录 `config.ini`（`<...>` 处替换为你的真实值；留空的密钥项会在首次运行时自动生成）：

```ini
[General]
mode = Attendance
startmode = Sync
syncinterval = 30

[Cloud]
enabled = False
host = localhost
user = root
password =
database = arcface_cloud

[S3]
endpoint = https://<account_id>.r2.cloudflarestorage.com
access_key = <your_r2_access_key_id>
secret_key = <your_r2_secret_access_key>
bucket = face-images
region = auto

[MySQL]
host = 127.0.0.1
user = root
password = <your_mysql_password>
database = face_recognition
port = 3306

[Security]
# 留空则首次运行时自动生成 Fernet 加密密钥
encryptionkey =

[WebAdmin]
host = 0.0.0.0
port = 6100
# 访问协议：http 或 https（域名部署建议 https）
protocol = http
# 留空则首次启动时自动生成登录令牌并打印到控制台
token =
salt =
# 登录会话空闲超时（分钟），默认 10
sessiontimeout = 10

[Templates]
company = name:text:姓名:false, gender:enum:性别:false, id_card:text:身份证号:false, phone:text:联系电话:false, email:text:电子邮箱:false, employee_id:text:工号:false, department:text:部门:false, position:text:职位:false, hire_date:date:入职日期:false, status:enum:员工状态:false, access_level:enum:门禁权限级别:false, validity_period:datetime:有效期:false, note:text:备注:false
community = name:text:姓名:false, gender:enum:性别:false, id_card:text:身份证号:false, phone:text:联系电话:false, email:text:电子邮箱:false, building_no:text:楼栋号:false, unit_no:text:单元号:false, room_no:text:房号:false, property_type:enum:房产性质:false, owner_name:text:业主姓名:false, resident_type:enum:人员类型:false, access_areas:multiselect:通行区域:false, validity_period:datetime:有效期:false, note:text:备注:false

[Enums]
gender = 男,女,其他
status = 在职,离职,休假,调岗,实习,待入职,停薪留职,退休
access_level = 1-普通员工,2-管理层,3-受限区域,4-临时员工,5-承包商,6-访客,7-实习生,8-其他
property_type = 自有,租赁,国有,集体所有,联营企业,股份制企业,港澳台投资,涉外房产,其他
resident_type = 业主,家属,租客,访客,物业,施工,其他
access_areas = 大门,单元门,地下室
```

将下面内容保存为 `web_admin/.env`：

```ini
FLASK_PORT=6100
FLASK_ENV=development
```

### 4. 域名 / HTTPS 部署

云端 Web 后台监听 `0.0.0.0`，可通过 IP 或域名访问。域名部署的完整链路：

1. **域名解析**：将域名 DNS 解析到服务器公网 IP。
2. **反向代理**：用 Nginx / Caddy 把 `80/443` 转发到 Flask 的 `6100` 端口，并配置 HTTPS 证书。
3. **边缘端配置**：在 SideUI 设置页中：
   - 协议：选择 `https`（或按反向代理实际协议选择 `http`）
   - 服务器地址：填域名（如 `cloud.example.com`）或 IP
   - 端口：填反向代理对外端口（如 `443` 或自定义）

> 💡 边缘端既支持 IP 也支持域名，本质都是同一个「地址」字符串；关键在于「协议」要与反向代理一致（https 需已配置证书），端口要与对外端口一致。

---

## 🤝 贡献与支持

加入交流群获取最新动态或技术支持：
- **QQ 交流群**：[1097302953](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=ge-5kwGOs3JswxbRp7UErPvQATEuR44f&authKey=u7dTn3rxfzC5J27Ev2pE8rzK3Y2NB%2F0VzzCAd9GXHpgdQr%2FIuOyBg0CBL1ry14h4&noverify=0&group_code=1097302953)

欢迎开发者提交 Issue 或 Pull Request 来共同完善这个项目！
1. **Fork** 本项目
2. 创建您的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交您的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 **Pull Request**

> 📝 **贡献者协议 (CLA) 与收益共享说明**：
> 鉴于本项目采用双重授权模式，当您提交 Pull Request 时，即表示您同意将您贡献代码的商业许可权（Commercial Licensing Rights）授予本项目发起人（Caos），以便我们能够向企业提供闭源商业授权。
> 💰 **开源激励承诺**：为感谢社区的付出，若本项目未来产生商业授权收益，我们将提取部分合理比例的净收益，建立**开源贡献者激励基金**，并根据核心贡献者（Core Contributors）的代码提交质量与工作量进行回馈划分。您依然保留对您贡献代码的原始署名权。

---

## 📄 协议与授权 (License)

本项目采用 **[Apache License 2.0](LICENSE)** 协议开源。您可以自由地使用、修改和分发本项目代码，但需遵守协议中的相关规定。

> ⚠️ **注意**：本项目边缘端 UI 依赖了 `PySide6`，该库基于 LGPLv3 协议。在进行商业分发时，请确保您遵守了 LGPLv3 的相关动态链接与开源义务。
>
> 🔐 **发布签名 (Release Signing)**：本项目的发布版本（Release）使用 GPG 签名以确保真实性与完整性，签名与验证流程请参见 **[RELEASE_GUIDE.md](RELEASE_GUIDE.md)**。
>
> 验证签名前请先导入本项目公钥：`gpg --import pubkey.asc`（公钥文件见 **[pubkey.asc](pubkey.asc)**）。

### ⚠️ 严格免责与使用条款 (Strict Disclaimer & Terms of Use)

请务必阅读完整的 **[DISCLAIMER.md](DISCLAIMER.md)** 文件。以下为核心摘要：

1. **项目用途**：本项目为**研究自用**性质的工程验证项目，并非开箱即用的商业产品。
2. **免责声明**：因使用本软件造成的任何直接或间接损失（包括但不限于数据泄露、业务中断等），作者**不承担任何责任**。本软件按“原样（AS IS）”提供。
3. **禁止事项**：**禁止**将本软件用于任何非法活动（如非法监控）；**禁止**移除项目中的版权和商标声明。
4. **生物数据隐私**：实际部署时，**必须**自行确保完全符合当地个人信息保护法律法规（如 PIPL、GDPR）。

---

<div align="center">
  <b>&copy; 2026 Caos. All Rights Reserved.</b><br>
  <i>Empowering Future Access Control with AI.</i>
</div>