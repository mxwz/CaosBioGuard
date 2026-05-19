<div align="center" markdown="1">
  <img src="https://img.icons8.com/fluency/150/000000/facial-recognition-scan.png" alt="Edge Icon"/>
  <h1>👁️ Caos BioGuard - Edge AI Device</h1>
  <p><strong>极致毫秒级响应的边缘 AI 感官 | The Ultra-Fast Edge AI Sensory</strong></p>
  
  <p>
    <img src="https://img.shields.io/badge/AI_Engine-InsightFace-FF6F00?style=for-the-badge" />
    <img src="https://img.shields.io/badge/Deep_Learning-PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white" />
    <img src="https://img.shields.io/badge/GUI-PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white" />
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-green?style=for-the-badge" /></a>
  </p>
  
  [**English Version**](README_en.md) | [**返回主页**](../README.md)
</div>

---

## 🌟 核心使命

作为系统的“感官终端”，**Edge Device** 部署在闸机、门禁或考勤机等物理入口。它依托强大的边缘计算能力，即使在弱网或断网环境下，也能实现**毫秒级的人脸比对**与**活体防伪拦截**。

---

## 🔮 炫酷功能亮点

<table>
  <tr>
    <td><b>⚡ 极速 AI 推理核心</b><br>底层深度集成 <code>InsightFace</code> (`buffalo_l` 模型)，支持 CPU 与 CUDA 硬件加速自动切换，眨眼间完成人脸特征提取与高维度向量比对。</td>
    <td><b>🛡️ 工业级活体防伪 (FAS)</b><br>内置基于 <code>PyTorch</code> 的轻量级活体检测神经网络，有效抵御高清照片、屏幕视频及 3D 面具等各类欺诈攻击。</td>
  </tr>
  <tr>
    <td><b>🍓 树莓派硬件级深度适配</b><br>除标准 PC 端 (`sideUI_unified.py`) 外，提供专为树莓派优化的 `sideUI_unified_pi.py`，原生调用 <code>libcamera</code> 与 <code>picamera2</code> 彻底释放 CSI 摄像头性能。</td>
    <td><b>🔄 异步并发多线程引擎</b><br>基于 <code>PySide6</code> 打造，UI 渲染线程与 AI 推理线程绝对隔离，支持异步高并发架构，确保识别画面如丝般顺滑。</td>
  </tr>
  <tr>
    <td><b>🔊 沉浸式交互体验</b><br>现代化深色系 UI 界面，人脸追踪框实时跟随。集成 <code>pyttsx3</code> 实现毫秒级本地语音播报反馈（“签到成功”、“识别失败”）。</td>
    <td><b>🗄️ 断网无忧的离线引擎</b><br>采用本地 `SQLite` 数据库与特征向量哈希缓存。云端断开？没关系，本地依然顺畅识别，网络恢复后后台静默同步记录。</td>
  </tr>
</table>

---

## ⚠️ 重要运行须知 (避坑指南)

> **首次运行防卡顿警告**：
> 在启动边缘端 UI 之前，**必须确保 Web 服务端的 MySQL 数据库已正确配置并在运行中**！如果边缘端无法连接到云端拉取配置和进行数据同步，其后台同步线程的反复重试会导致识别界面出现**明显的卡顿（一卡一卡的现象）**。

### 如何启动？

*   **普通 PC / Windows / x86 Linux** (使用 USB 摄像头)：
    ```bash
    python sideUI/sideUI_unified.py
    ```
*   **树莓派专版** (使用 CSI 摄像头，需在根目录运行)：
    ```bash
    python sideUI_unified_pi.py
    ```

---

## 📄 协议与授权 (Edge License)

本边缘端核心代码（包含 UI 与本地推理逻辑）采用 **[GNU GPLv3](LICENSE)** 协议开源。
由于使用了 `PySide6` (LGPLv3)，为了确保开源生态的纯洁性：
*   **个人/学习使用**：完全免费。
*   **商业分发限制**：如果您将本程序打包成独立软件（如 `.exe`）或烧录至硬件设备中对外销售，您**必须**开源您修改后的完整系统代码。如需规避开源义务进行闭源商业售卖，请联系原作者获取商业授权许可。