# 打包说明

## Windows（Kiosk）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-edge.txt -r requirements-build.txt
.\packaging\build_windows.ps1 -Clean
```

产物：`dist\CaosBioGuardKiosk\CaosBioGuardKiosk.exe`

如果打包机存在 `~/.insightface/models/buffalo_l`，spec 会自动把模型内置到
`_internal/insightface/models/buffalo_l`，目标机可离线运行；当前 Windows 含模型单目录约 800MB。
若未内置模型，运行时会回退到目标机 `~/.insightface` 或尝试下载。

部署时仍需单独提供 `config.ini`（相机、阈值、活体模式、`[WebAdmin]`、`[Sync]`），
不要把含密钥的配置打进安装包；可选挂载旧 `dd/face_database.pkl`。

## Windows 安装包（Inno Setup）

先完成 PyInstaller 构建：

```powershell
.\packaging\build_windows.ps1 -Clean
```

安装 Inno Setup 后执行：

```powershell
ISCC packaging/windows_installer.iss
```

产物：`dist/installer/CaosBioGuardKioskSetup.exe`

## Linux / 树莓派

```bash
python3 -m pip install -r requirements-edge.txt -r requirements-build.txt
bash packaging/build_linux.sh
```

树莓派建议使用 64 位系统 + `onnxruntime` CPU；Kiosk 全屏依赖 Qt xcb：

```bash
sudo apt install -y libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0
```

## Android APK

PySide6 与 PyInstaller 不能直接生成 APK。当前手机端是 PWA 和微信小程序；若要 APK，推荐用 Capacitor 包装现有 `mobile/`，并安装 JDK、Android Studio 和 Android SDK。详细流程见 `docs/run-modes.md`。

## 注意

- 打包机与目标机 **架构/系统必须一致**（Windows 上不能打 Linux 包）。
- 离线部署优先使用 spec 自动内置的 `buffalo_l`；未内置时，请提前把 `~/.insightface/models` 复制到目标机。
- 不要在 spec 中打包 `config.ini`（含 token/密钥）。
