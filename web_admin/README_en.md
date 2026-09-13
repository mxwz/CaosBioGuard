<div align="center" markdown="1">
  <img src="https://img.icons8.com/fluency/150/000000/server.png" alt="Server Icon"/>
  <h1>☁️ Caos BioGuard - Web Admin Server</h1>
  <p><strong>The Intelligent Central Control Center</strong></p>
  
  <p align="center">
    <img src="https://img.shields.io/badge/Framework-Flask-black?style=for-the-badge&logo=flask" />
    <img src="https://img.shields.io/badge/Database-MySQL-4479A1?style=for-the-badge&logo=mysql&logoColor=white" />
    <img src="https://img.shields.io/badge/Frontend-Jinja2%20%7C%20Bootstrap-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white" />
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue?style=for-the-badge" /></a>
  </p>
  
  [**中文版本**](README.md) | [**Back to Main**](../README_en.md)
</div>

---

## 🌟 Core Mission

As the "Brain" of the entire distributed face recognition access control and attendance system, the **Web Admin** is responsible for orchestrating data requests from all edge devices, providing a powerful visual management dashboard, and ensuring absolute consistency and security of global data.

---

## 🔮 Feature Highlights

<table>
  <tr>
    <td><b>📊 Dynamic Visual Dashboard</b><br>Real-time presentation of daily attendance rates, device online status, and personnel access trends using modern chart libraries.</td>
    <td><b>👥 Global Face Database Management</b><br>Supports multi-condition rapid retrieval and personnel grouping. Enables direct invocation of webcams via the Web page to register high-precision face images.</td>
  </tr>
  <tr>
    <td><b>💻 Edge Device Orchestration</b><br>Remotely control the business mode (Attendance/Access) and startup parameters of edge terminals from the cloud. "Modify once, effective network-wide."</td>
    <td><b>📝 Multi-dimensional Data Export</b><br>Panoramic traceability of attendance streams, access records, and abnormal anti-spoofing alarm logs, supporting customized Excel report exports.</td>
  </tr>
  <tr>
    <td><b>⚙️ Flexible Metadata Customization</b><br>Built-in dual templates for enterprise attendance and community access. Administrators can freely configure personnel additional information fields (e.g., dropdowns, multi-select dictionaries).</td>
    <td><b>🔒 Hybrid Identity Authentication</b><br>Supports traditional high-strength password systems and frontend face recognition login based on Base64 image streams to guarantee system entry security.</td>
  </tr>
</table>

---

## 🛠️ Architecture & Tech Stack

This server adopts a classic **MVC** layered architecture to ensure high cohesion and low coupling:

*   **Routers**: Based on `Flask` Blueprints, strictly isolating API interfaces from page rendering routes.
*   **Services**: `managers.py` coordinates core business logic and handles complex bi-directional data synchronization conflicts.
*   **Database**: Relies on `MySQL` for massive data persistence, thoroughly preventing SQL injection through parameterized queries.
*   **Security**: Global `@app.before_request` permission interception, strictly verifying Session and Device ID boundaries.

---

## 🚀 Deployment Guide

### 1. Database Preparation
Ensure your server has MySQL 5.7 or above installed.
```sql
CREATE DATABASE caos_BioGuard DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2. Environment Configuration
Configure the `[MySQL]` node in the `config.ini` located in the project root:
```ini
[MySQL]
host = 127.0.0.1
port = 3306
user = root
password = your_password
database = caos_BioGuard
```

### 3. Start the Service
```bash
# Execute from the project root directory
cd ..
python web_admin/app.py
```
> 🎉 **Tip**: Upon successful initial database connection, the system will automatically create all required tables and print the initial super admin credentials in the console!

---

## 🧩 Plugin Package Format & Validation (Registry Center)

The registry center manages three kinds of registries (notify channels / face store backends / agent tools) using a **plug-and-play package** model. Every plugin (application) is a Python package containing `__init__.py`. Simply drop it into the corresponding directory to be auto-discovered — there is no "add plugin" button to click in the admin panel.

### Custom Plugin Directories

| Registry | Custom plugin directory |
| --- | --- |
| Notify channels | `custom_plugins/notify/` |
| Face store backends | `custom_plugins/face_store/` |
| Agent tools | `custom_plugins/agent_tools/` |

### Required Format

Each plugin package must define a module-level `INFO = PluginInfo(...)` in its `__init__.py`. The registry center reads and validates the application through it. **Required attributes**:

| Attribute | Description |
| --- | --- |
| `name` | English identifier (a valid Python identifier, e.g. `health_check`) |
| `display_name` | Chinese display name (e.g. `服务健康检查`) |
| `description` | Description of what the application does |
| `origin` | `'system'` (built-in) / `'custom'` (custom) |
| `entry` | The implementation body (class / instance / factory) |

The optional `tags` attribute is a list of tags used for tag-based filtering in the registry center.

### Example

```python
from registry.base import PluginInfo


class HealthCheckChannel:
    name = 'health_check'
    display_name = '服务健康检查'


INFO = PluginInfo(
    name='health_check',
    display_name='服务健康检查',
    description='定时探测服务健康状态并告警',
    origin='custom',
    entry=HealthCheckChannel(),
    tags=['通知', '健康检查'],
)
```

### Validation Rules

*   A single `.py` file is not a valid plugin form; it must be a package subpackage containing `__init__.py`, otherwise it is **highlighted in red** as well.
*   Missing any required attribute, an invalid `name`, an invalid `origin`, or an empty `entry` is treated as a **format error**.
*   Malformed plugins are not shown in the application list; instead they are **highlighted in red** in the "problem applications" section with the concrete error reason.
*   Valid plugins appear immediately in their registry, with fuzzy search, tag filtering, and type filtering support.

---

## 📄 License & Authorization

The server code is open-sourced under the **[Apache License 2.0](LICENSE)** license. You are free to use, modify, and distribute this project, provided you comply with the terms of the license.