<div align="center" markdown="1">
  <img src="https://img.icons8.com/fluency/150/000000/facial-recognition-scan.png" alt="Edge Icon"/>
  <h1>👁️ Caos BioGuard - Edge AI Device</h1>
  <p><strong>The Ultra-Fast Edge AI Sensory</strong></p>
  
  <p>
    <img src="https://img.shields.io/badge/AI_Engine-InsightFace-FF6F00?style=for-the-badge" />
    <img src="https://img.shields.io/badge/Deep_Learning-PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white" />
    <img src="https://img.shields.io/badge/GUI-PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white" />
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-green?style=for-the-badge" /></a>
  </p>
  
  [**中文版本**](README.md) | [**Back to Main**](../README_en.md)
</div>

---

## 🌟 Core Mission

As the "Sensory Terminal" of the system, the **Edge Device** is deployed at physical entrances like turnstiles or attendance machines. Relying on powerful edge computing capabilities, it achieves **millisecond-level facial comparison** and **anti-spoofing interception** even in weak or disconnected network environments.

---

## 🔮 Feature Highlights

<table>
  <tr>
    <td><b>⚡ Ultra-Fast AI Inference</b><br>Deeply integrates <code>InsightFace</code> (`buffalo_l` model), supporting automatic CPU/CUDA hardware acceleration switching, completing feature extraction and vector comparison in the blink of an eye.</td>
    <td><b>🛡️ Industrial-Grade Anti-Spoofing (FAS)</b><br>Built-in lightweight liveness detection neural network based on <code>PyTorch</code>, effectively resisting various fraud attacks like HD photos, screen videos, and 3D masks.</td>
  </tr>
  <tr>
    <td><b>🍓 Raspberry Pi Hardware Deep Adaptation</b><br>In addition to the standard PC version (`sideUI_unified.py`), a dedicated `sideUI_unified_pi.py` is provided, natively calling <code>libcamera</code> and <code>picamera2</code> to unleash CSI camera performance.</td>
    <td><b>🔄 Asynchronous Concurrent Engine</b><br>Built on <code>PySide6</code>, ensuring absolute isolation between the UI rendering thread and the AI inference thread. Supports asynchronous high-concurrency architecture for silky-smooth visuals.</td>
  </tr>
  <tr>
    <td><b>🔊 Immersive Interactive Experience</b><br>Modern dark-themed UI with real-time face tracking boxes. Integrates <code>pyttsx3</code> for millisecond-level local voice broadcast feedback ("Sign-in successful", "Recognition failed").</td>
    <td><b>🗄️ Offline-Proof Engine</b><br>Adopts local `SQLite` database and feature vector hash caching. Cloud disconnected? No problem. Local recognition remains smooth, and records are silently synced in the background once the network recovers.</td>
  </tr>
</table>

---

## ⚠️ Important Runtime Notice (Avoid Stuttering)

> **Anti-Stutter Warning for First Run**:
> Before starting the Edge UI, **you MUST ensure that the Web Server's MySQL database is correctly configured and running**! If the edge device fails to connect to the cloud to pull configurations and sync data, the repeated retries of its background sync thread will cause **noticeable stuttering (lagging UI and camera feed)**.

### How to Start?

*   **Standard PC / Windows / x86 Linux** (Using USB Webcams):
    ```bash
    python sideUI/sideUI_unified.py
    ```
*   **Raspberry Pi Edition** (Using CSI Camera, run from the root directory):
    ```bash
    python sideUI_unified_pi.py
    ```

---

## 📄 License & Authorization

The core edge code (including UI and local inference logic) is open-sourced under the **[GNU GPLv3](LICENSE)** license.
Due to the use of `PySide6` (LGPLv3), to ensure the purity of the open-source ecosystem:
*   **Personal/Educational Use**: Completely free.
*   **Commercial Distribution Restrictions**: If you package this program into standalone software (e.g., `.exe`) or flash it into hardware devices for external sales, you **MUST** open-source your complete modified system code. To bypass open-source obligations for closed-source commercial sales, please contact the original author for a commercial license.