# 百度人脸离线 SDK 接入评估

本文基于百度人脸离线识别 SDK 文档和本地 `baidu_face_SDK/` 压缩包，评估其接入现有 HybridEngine 的方式、授权条件、风险和后续实施步骤。

## 1. SDK 能力

百度官方文档说明，人脸离线识别 SDK 包含人脸采集、活体检测、人脸对比/识别、人脸库管理等能力，全部在本地离线运行。官方文档地址：

https://ai.baidu.com/ai-doc/FACE/Yk37c1opz

文档中列出的能力包括：

- 人脸检测与跟踪
- 人脸质量控制
- 人脸采集
- RGB 可见光静默活体
- NIR 近红外活体
- Depth/3D 结构光活体
- 1:1 人脸对比
- 1:N 人脸搜索
- 本地人脸库管理
- 人脸属性、遮挡、模糊、姿态、口罩等检测

## 2. 本地 SDK 包情况

本地目录包含 Android、Windows、Linux ARM、RV1109、RV1106、RV1126、RK3588 等多个版本。

典型 Windows C++ SDK 头文件 `baidu_face_api.h` 提供 `BaiduFaceApi` 类，关键方法包括：

- `sdk_init`
- `get_device_id`
- `is_auth`
- `detect`
- `track`
- `face_feature`
- `liveness_feature`
- `rgb_liveness`
- `nir_liveness`
- `rgb_depth_liveness`
- `match`
- `compare_feature`
- `identify`
- `user_add`
- `user_update`
- `user_delete`

## 3. 关键工程结论

Python 不能直接通过 `ctypes` 调用 C++ 类成员函数。C++ 类存在名称修饰、对象构造、this 指针和 ABI 差异，直接调用容易崩溃，也不稳定。

因此需要以下任一桥接方式：

### 方案 A：C ABI 包装 DLL/so，推荐

编写一个很薄的 C 接口，对 `BaiduFaceApi` 进行包装，例如：

- `caos_bdface_init`
- `caos_bdface_device_id`
- `caos_bdface_detect`
- `caos_bdface_extract`
- `caos_bdface_liveness`
- `caos_bdface_compare`
- `caos_bdface_identify`
- `caos_bdface_shutdown`

Python 侧通过 `ctypes.CDLL` 加载，再实现 `BaiduFaceSDKAdapter(VendorAdapter)`。

优点：

- 稳定、性能好；
- 可同时适配 Windows DLL 和 Linux so；
- 与现有 `HybridEngine` 最匹配；
- 内存和线程可以在桥接层显式管理。

### 方案 B：C#/Java 本地 HTTP 或 gRPC 服务

使用官方 C# 或 Java Demo 启动本地服务，对 Python 暴露 localhost HTTP/gRPC。

优点：

- 复用官方示例；
- 不需要先写 C ABI。

缺点：

- 多一个运行进程；
- 部署和运维更复杂；
- 性能和端口管理成本更高。

### 方案 C：Android/ARM 设备端原生服务

Android、RK3588、RV1126 等版本可在设备原生侧运行 SDK，再通过本地 HTTP、gRPC、WebSocket 或命名管道与 Python 边缘服务通信。

该方案适合最终硬件一体机，不适合当前 Windows 开发阶段。

## 4. 授权与激活

百度离线 SDK 按设备授权，每台设备需要独立序列号和 License。激活时绑定设备硬件指纹。

需要管理：

- 序列号
- 硬件指纹
- License 文件
- SDK 版本
- 模型路径
- 授权有效期
- 设备系统时间

正式授权永久有效，但硬件变更可能导致授权失效；测试授权通常有有效期限制。

## 5. 与现有双后端架构的关系

现有架构包含：

- `VendorAdapter`
- `GenericSDKAdapter`
- `HybridEngine`
- `BioTemplateStore`
- `CaptureRepository`

百度 SDK 应作为人脸模态的一个厂商后端接入：

- `model`：继续使用当前 InsightFace 模型；
- `sdk`：使用百度离线 SDK；
- `fusion`：模型和 SDK 分别出分，再按策略融合；
- `auto`：SDK 可用时优先 SDK，不可用时按配置决定是否回退模型。

注意：不同来源的模板必须同源比较。SDK 模板不能直接与 InsightFace 模板当作同一向量比较，应通过各自后端比较，融合层只融合分数。

## 6. 后续实施步骤

1. 解压 Windows C++ SDK，确认 DLL、模型、License 目录和运行时依赖。
2. 编写 C ABI 包装层，先实现初始化、授权检查、设备指纹和人脸检测。
3. 再实现特征提取、RGB 活体、1:1 比较和 1:N 搜索。
4. Python 侧实现 `BaiduFaceSDKAdapter`。
5. 接入 `VendorAdapterRegistry` 和配置段。
6. 增加单元测试、桥接层 mock 测试和异常路径测试。
7. 在真实设备上激活 License，验证离线运行。
8. 与当前 InsightFace 做 A/B 对比和 fusion 策略验证。
9. 再扩展 Linux ARM、RK3588 或 Android 一体机版本。

## 7. 当前边界

在没有解压并构建 C ABI 桥接层、没有激活 License 的情况下，不能声称百度离线 SDK 已完成真机接入。当前可确认的是：SDK 包已具备，官方能力和接入路径明确，后续可按适配器方式纳入现有双后端架构。
