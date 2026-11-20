# 百度人脸离线 SDK 接入说明

本文记录百度人脸离线识别 SDK 在 CaosBioGuard 中的 Windows 桥接方案、当前实现状态和授权验收边界。官方文档地址：

https://ai.baidu.com/ai-doc/FACE/Yk37c1opz

## 1. SDK 能力

百度 Windows C++ SDK 提供人脸检测、跟踪、特征提取、RGB/NIR/深度活体、1:1 比较、1:N 搜索、本地人脸库和用户组管理等能力，核心类为 `BaiduFaceApi`。

本地 Windows C++ SDK 已解压到（外部资料统一存放于 `TEMP/`，不入库）：

```text
TEMP/baidu_face_SDK/extracted/Windows_Cpp_8.4/FaceOfflineSdk
```

关键目录：

- 头文件：`FaceOfflineSdk/include/baidu_face_api.h`、`struct_info.h`；
- face_scene 头文件：`face_scene/include`；
- OpenCV 头文件：`third_party/opencv-win/include`；
- x64 导入库：`FaceOfflineSdk/lib/x64/BaiduFaceApi.lib`；
- x64 运行 DLL：`x64/`；
- 模型目录：`models/`；
- License 目录：`license/`。

## 2. C ABI 桥接

Python `ctypes` 不适合直接调用 C++ 类成员函数，因此项目在 `vendor_wrappers/baidu_face` 提供稳定 C ABI：

- `caos_bdface_create` / `caos_bdface_destroy`；
- `caos_bdface_init` / `caos_bdface_is_authorized`；
- `caos_bdface_detect`；
- `caos_bdface_extract`；
- `caos_bdface_compare`；
- `caos_bdface_rgb_liveness`。

包装层将 Python 传入的 uint8 图像转换为 OpenCV `cv::Mat`，再调用 `BaiduFaceApi`。所有入口均捕获 C++ 异常，避免异常跨越 ABI 边界导致进程崩溃。

当前 Windows 构建已通过：

```powershell
.\vendor_wrappers\baidu_face\build.ps1
```

产物为：

```text
vendor_wrappers/build/baidu_face/Release/caos_bdface.dll
```

## 3. Python 适配器

`biometrics/adapters/baidu_face.py` 提供 `BaiduFaceSDKAdapter`：

- 使用 `ctypes.CDLL` 加载 C ABI；
- 通过 `os.add_dll_directory` 加载百度运行时 DLL；
- 初始化模型目录并检查授权；
- 将百度 `Feature` 转换为标准 `BioTemplate`；
- 支持 SDK 同源特征比较；
- 支持 RGB 静默活体结果；
- 已接入 `VendorAdapterRegistry`，当厂商为 `baidu` 时自动选择该适配器。

示例插件入口位于 `plugins/available/baidu_face/`，可通过插件注册中心安装并加载。

## 4. 当前授权状态

当前设备尚未完成正式 License 激活。官方 Demo 与适配器检查均返回授权相关错误，因此不能声称已完成真机离线识别验收。

后续激活时需要核对：

- 设备硬件指纹；
- License Key 和 license.ini；
- 授权有效期；
- 模型目录；
- 系统时间；
- x64 运行时 DLL 依赖；
- 硬件变更后的授权状态。

## 5. 与双后端架构的关系

百度 SDK 作为人脸模态的厂商后端接入：

- `model`：使用现有本地模型；
- `sdk`：使用百度离线 SDK；
- `fusion`：模型和 SDK 分别出分后融合；
- `auto`：SDK 可用时优先 SDK，不可用时按配置回退。

不同来源的特征向量不能直接跨后端比较。SDK 模板必须通过百度 SDK 比较，融合层只融合各自返回的分数。

## 6. 剩余验收

授权完成后需要执行：

1. 真机离线初始化和 License 有效性检查；
2. 现场人脸检测、特征提取、1:1 和 1:N 测试；
3. RGB 活体与照片、屏幕、面具等 PAD 攻击测试；
4. FAR、FRR、EER 和阈值标定；
5. 与本地模型的 A/B 对比和 fusion 策略验证；
6. 插件停用、回退、卸载和审计验证；
7. 单独同意、PIA 和管理员确认流程复核。
