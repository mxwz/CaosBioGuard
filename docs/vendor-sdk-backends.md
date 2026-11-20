# 模型识别与厂商 SDK 双后端说明

## 1. 为什么不是二选一

生物识别系统通常同时存在两类后端：

| 后端 | 输入 | 输出 | 优势 | 主要成本 |
|---|---|---|---|---|
| 本地模型/算法 | 原始图像、音频、视频、轨迹 | 标准 `BioTemplate` | 跨厂商、可离线、数据格式统一、便于融合 | 真实精度依赖模型、训练数据和现场调参 |
| 厂商 SDK | 传感器原始数据或厂商模板 | 厂商模板、分数、活体结果 | 与采集硬件深度适配，通常包含设备驱动、质量控制、防伪和授权 | 平台绑定、协议私有、许可证和部署依赖 |

因此，指纹、虹膜、掌纹、静脉、视网膜等模态**既应该支持模型识别，也应该支持厂商 SDK**。仓库中的本地引擎负责统一的离线算法链路；厂商 SDK 通过适配层接入，不把私有协议散落到 UI、业务服务和存储层。

## 2. 软件结构

```text
BiometricService
        │
        ▼
HybridEngine
 ├── Model Engine：本地模型/算法，输出标准 BioTemplate
 └── VendorAdapter：封装厂商 Python SDK 或外部命令
        │
        ▼
BioTemplateStore：model / sdk 模板分开存储，可共存
```

相关模块：

| 模块 | 职责 |
|---|---|
| `biometrics/adapters/base.py` | 厂商适配器抽象 |
| `biometrics/adapters/generic.py` | 通用 Python/命令行 SDK 适配器和模板归一化 |
| `biometrics/adapters/registry.py` | 按模态注册 SDK，读取策略配置 |
| `biometrics/adapters/hybrid.py` | 模型与 SDK 混合引擎 |
| `biometrics/store.py` | 按 `backend` 字段共存模板 |

## 3. 后端策略

配置入口：

```ini
[BiometricBackends]
default_policy=auto
allow_fallback=true
```

| 策略 | 行为 |
|---|---|
| `auto` | 厂商 SDK 可用时优先使用 SDK；不可用时自动回退本地模型 |
| `model` | 强制使用本地模型，不调用厂商 SDK |
| `sdk` | 强制使用厂商 SDK；若 `allow_fallback=false`，SDK 不可用即失败 |
| `fusion` | 同时运行模型和 SDK，按权重融合分数，高安全场景使用 |

也可以在单个模态上覆盖策略：

```ini
[VendorSDK.fingerprint]
enabled=true
policy=fusion
```

单次请求还可以通过 `BioSample.meta['backend']='model'` 临时指定后端。

## 4. 厂商 SDK 配置

### 4.1 Python SDK 模式

```ini
[VendorSDK.fingerprint]
enabled=true
vendor=example
mode=python
python_class=vendor_adapters.FingerprintAdapter
template_format=iso19794-2
sdk_version=1.0
```

`python_class` 指向的包装类建议实现以下方法：

- `caos_available()`：检查驱动、授权和设备连接；
- `caos_extract(sample)`：返回 `BioTemplate`、字节、base64、向量或字典；
- `caos_compare(probe, gallery)`：返回 0~1 分数；
- `caos_liveness(sample)`：返回 `LivenessReport`；
- `caos_quality(sample)`：返回 `QualityReport`。

包装层的意义是把厂商私有数据结构转换成系统统一类型，业务层不直接导入厂商 SDK。

### 4.2 外部命令模式

适合 C/C++、Java 或只能独立运行的 SDK：

```ini
[VendorSDK.fingerprint]
enabled=true
mode=command
command=C:/sdk/caos_sdk_wrapper.exe
args=--device finger-01
timeout=8
```

程序通过 JSON 输入输出，系统以 `subprocess.run(..., shell=False)` 调用，不使用 shell。命令包装器需要明确处理设备路径、超时、错误码和模板编码。

## 5. 模板共存

模板库使用 `backend` 字段区分：

- `model`：本地模型模板；
- `sdk`：厂商模板；
- 未来可扩展其他后端。

同一人员、同一模态可以同时保存两份模板：

```text
subject=张三, modality=fingerprint, backend=model
subject=张三, modality=fingerprint, backend=sdk
```

默认 1:N 检索在两份模板都存在时优先选择 SDK 模板；指定 `backend=model` 时只检索模型模板。融合验证会分别读取两份模板并合并结果。

## 6. 接入真实设备的验收要求

即使同时接入模型和 SDK，也不能只靠合成样本判断可上线：

1. 确认设备驱动、波特率/USB/网络、授权文件和运行平台；
2. 确认 SDK 输出的是原始图像、标准模板还是私有模板；
3. 采集真实人员样本，评估 FAR、FRR、EER、阈值和稳定性；
4. 分别验证模型、SDK、自动回退和融合策略；
5. 验证断网、设备掉线、授权过期、模板版本升级和断电恢复；
6. 对指纹、虹膜、静脉等模态验证现场光照、干湿手指、佩戴眼镜、距离和角度影响。

## 7. 云端厂商路线

腾讯云 IAI、华为云 FRS、阿里云 VIAPI/IMM/CloudAuth 主要是云端 API，应优先在服务端实现 Python 适配器，密钥保留在服务端，不放进手机端。阿里云 Android AAR 属于端侧 SDK，需要单独实现 Capacitor 原生插件。

阿里云四条路线的配置、mock 和验收边界见 `docs/aliyun-integration.md`。

## 8. 当前边界

当前代码已完成双后端接口、通用适配器、混合引擎、模板共存、阿里云四条路线占位和自动化测试。具体厂商 SDK 的真机效果仍取决于实际设备、驱动、授权和现场数据；没有接入对应 SDK 前，不能宣称某个具体型号已经完成验收。
