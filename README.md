<div align="center" markdown="1">

# 🔮 Caos BioGuard
**智能分布式人脸门禁与考勤管理系统 | Distributed Face Recognition System**

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Flask](https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PySide6](https://img.shields.io/badge/PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://www.qt.io/)
[![License](https://img.shields.io/badge/license-AGPLv3-blue?style=for-the-badge)](LICENSE)

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
| **识别方式** | 动态人脸（未来支持多生物特征融合） | 实体卡片/NFC（易丢失、易代打） | 静态图片/视频流上传 |
| **边缘计算** | 支持（本地毫秒级特征比对） | 不支持（仅做简单验证） | 不支持（极度依赖网络） |
| **活体检测** | 内置离线防伪，防御照片/视频攻击 | 无 | 需消耗云端 API 额度 |
| **离线可用性** | **完全可用**（本地鉴权，异步上传） | 仅支持已注册卡片 | 不可用 |
| **云端集中管控** | 支持（多设备、多终端全局统一管理） | 较弱（多为局域网单机管理） | 支持 |
| **硬件成本与适配** | 极低（支持树莓派/普通PC+USB摄像头） | 中等（需专用读卡器/闸机硬件） | 极低（但云端长期调用费用高） |
| **二次开发扩展** | 极高（全栈 Python 现代开源架构） | 极低（传统封闭系统） | 中等（受限于 API 接口） |

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

## 📄 协议与双重授权 (License & Dual Licensing)

本项目采用 **双重授权模式 (Dual Licensing)**，以平衡开源社区的技术交流与商业化需求：

1. **开源社区与个人学习 (AGPL-3.0 / GPL-3.0)**
   本项目整体服务端在 [GNU AGPLv3](LICENSE) 协议下开源，边缘端 UI 独立使用 [GNU GPLv3](sideUI/LICENSE) 协议。您可以免费下载、学习、修改并在遵守协议的前提下使用本项目。
   > ⚠️ **注意**：AGPLv3/GPLv3 均具有强烈的“开源传染性”。如果您将本项目用于商业产品，或将其部署在网络上对外提供服务，**您必须将您的商业系统源代码同样以对应协议开源**。

2. **闭源商业化授权 (Commercial License)**
   如果您希望将本项目（或其衍生品）用于商业盈利、打包进闭源的商业硬件/SaaS 系统中，且**不愿意开源您自己的商业代码**，您**必须**联系原作者获取商业授权许可。

### ⚠️ 严格免责与合规声明 (Strict Disclaimer)

1. **生物数据隐私与法律红线**：人脸等生物特征数据属于高度敏感的个人隐私。本项目仅提供技术验证的工程化实现，**绝不鼓励、不参与**侵犯他人隐私的行为。用户实际部署时，**必须自行确保完全符合当地个人信息保护法律法规**。
2. **预训练模型版权限制**：本系统底层调用的 `InsightFace` 模型权重通常**仅限学术研究与非商业用途**。若涉及模型商用问题，请自行查阅官方协议，本项目不提供商业背书。
3. **免责条款**：因用户擅自将本项目用于商业用途、非法用途，或因 Bug 导致的直接或间接经济损失与法律纠纷，**全部由使用者自行承担，原作者概不负责**。

---

<div align="center">
  <b>&copy; 2026 Caos. All Rights Reserved.</b><br>
  <i>Empowering Future Access Control with AI.</i>
</div>