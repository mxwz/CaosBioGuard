# 打包说明

## Windows（Kiosk）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-edge.txt -r requirements-build.txt
.\packaging\build_windows.ps1 -Clean
```

产物：`dist\CaosBioGuardKiosk\CaosBioGuardKiosk.exe`

首次运行会在 exe 同级生成 `config.ini`、`dd/`。把以下内容放到同目录：

- `config.ini`（相机、阈值、活体模式、`[WebAdmin]`、`[Sync]`）
- InsightFace 模型目录（默认 `~/.insightface` 或 `config.ini` 指定路径）
- 可选 `dd/face_database.pkl`（旧人脸库）

## Linux / 树莓派

```bash
python3 -m pip install -r requirements-edge.txt -r requirements-build.txt
bash packaging/build_linux.sh
```

树莓派建议使用 64 位系统 + `onnxruntime` CPU；Kiosk 全屏依赖 Qt xcb：

```bash
sudo apt install -y libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0
```

## 注意

- 打包机与目标机 **架构/系统必须一致**（Windows 上不能打 Linux 包）。
- `insightface` 首次运行会下载模型；离线部署请提前把 `~/.insightface/models` 复制到目标机。
- 不要在 spec 中打包 `config.ini`（含 token/密钥）。
