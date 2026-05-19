<div align="center" markdown="1">
  <img src="https://img.icons8.com/fluency/150/000000/server.png" alt="Server Icon"/>
  <h1>☁️ Caos BioGuard - Web Admin Server</h1>
  <p><strong>智能集中管控中心 | The Intelligent Central Control Center</strong></p>
  
  <p>
    <img src="https://img.shields.io/badge/Framework-Flask-black?style=for-the-badge&logo=flask" />
    <img src="https://img.shields.io/badge/Database-MySQL-4479A1?style=for-the-badge&logo=mysql&logoColor=white" />
    <img src="https://img.shields.io/badge/Frontend-Jinja2%20%7C%20Bootstrap-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white" />
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-AGPLv3-blue?style=for-the-badge" /></a>
  </p>
  
  [**English Version**](README_en.md) | [**返回主页**](../README.md)
</div>

---

## 🌟 核心使命

作为整个分布式人脸门禁考勤系统的“大脑”，**Web Admin** 负责统筹处理来自所有边缘设备的数据请求，提供强大的可视化管理大屏，并确立全局数据的绝对一致性与安全性。

---

## 🔮 炫酷功能亮点

<table>
  <tr>
    <td><b>📊 动态可视化大屏</b><br>基于现代化图表库，实时呈现今日考勤率、设备在线状态与人员通行趋势，打造科技感十足的监控中心。</td>
    <td><b>👥 全局人脸库管理</b><br>支持多条件极速检索、人员分组编排。更支持通过 Web 页面直接唤起摄像头录入高精度人脸底图。</td>
  </tr>
  <tr>
    <td><b>💻 边缘设备统管</b><br>在云端一键下发指令，远程控制边缘终端的业务模式（考勤/门禁）与启动参数，实现“一处修改，全网生效”。</td>
    <td><b>📝 多维数据穿透与导出</b><br>考勤流水、门禁记录、异常活体攻击报警记录全景追溯，支持自定义时间维度的 Excel 报表导出。</td>
  </tr>
  <tr>
    <td><b>⚙️ 灵活自定义元数据</b><br>系统内置企业考勤/社区门禁双模板。管理员可自由配置人员附加信息字段（如下拉框、多选框字典）。</td>
    <td><b>🔒 混合身份认证</b><br>支持传统高强度密码体系与基于 Base64 图像流的前端人脸活体识别双重登录模式，保障系统入口安全。</td>
  </tr>
</table>

---

## 🛠️ 后端架构与技术栈

本服务端采用经典的 **MVC** 分层架构设计，确保代码的高内聚与低耦合：

*   **路由层 (Routers)**：基于 `Flask` 蓝图 (Blueprints)，严格隔离 API 接口与页面渲染路由。
*   **服务层 (Services)**：`managers.py` 统筹核心业务逻辑，处理复杂的双向数据同步冲突。
*   **持久层 (Database)**：依托 `MySQL` 进行海量数据持久化，通过参数化查询彻底杜绝 SQL 注入。
*   **安全层 (Security)**：全局 `@app.before_request` 权限拦截，严格校验 Session 会话与 Device ID 权限边界。

---

## 🚀 部署指南

### 1. 数据库准备
请确保您的服务器已安装 MySQL 5.7 或以上版本。
```sql
CREATE DATABASE face_recognition DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2. 环境配置
在项目根目录（即 `../config.ini`）中配置 `[MySQL]` 节点信息：
```ini
[MySQL]
host = 127.0.0.1
port = 3306
user = root
password = your_password
database = face_recognition
```

### 3. 启动服务
```bash
# 回到项目根目录执行
cd ..
python web_admin/app.py
```
> 🎉 **提示**：首次成功连接数据库后，系统会自动创建所需的所有数据表，并在控制台打印初始的超级管理员账号与密码！

---

## 📄 协议与授权 (Server License)

本服务端代码采用 **[GNU AGPLv3](LICENSE)** 协议开源。
**核心约束**：如果您将本 Web 服务端用于商业用途，或将其部署在网络上作为 SaaS 服务对外提供，您**必须**将您的整个商业系统（包含修改后的本服务端代码及与之交互的其他服务端代码）同样以 AGPLv3 协议开源。如需闭源商业化使用，请联系原作者获取商业授权。