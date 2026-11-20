# 拔插式 SDK 插件协议

本文说明 CaosBioGuard 的厂商 SDK 插件、标准模板包、签名校验和注册中心。插件目录默认不进入仓库，示例插件位于 `plugins/available/`，运行时安装目录为 `plugins/installed/`。

## 1. 两类可导入对象

### 1.1 标准模板包

标准模板包使用 `template.toml`，用于导入系统已经定义的 `BioTemplate`。数组可通过外部 `.npy` 或 base64 提供。

导入流程：

1. 安全 ZIP 解压；
2. 校验 `template.toml` 和数组；
3. 构造 `BioTemplate`；
4. 写入加密模板库；
5. 如包含原始样本，同步写入加密样本版本库。

标准模板导入不等于自动兼容厂商私有模板。私有 `.bin`、`.dat` 或厂商特征必须通过对应适配器解释。

### 1.2 原生 SDK 插件

原生 SDK 插件使用 `plugin.toml`，并提供适配器入口。适配器必须继承 `VendorAdapter`，实现可用性检查、特征提取，并按能力实现比较、活体或用户管理。

Python 不直接调用 C++ 类成员函数。C/C++ SDK 必须先提供稳定 C ABI，再由 Python 通过 `ctypes` 加载。

## 2. Manifest 字段

`plugin.toml` 的核心字段包括：

- `schema_version`：当前为 `1.0`；
- `plugin_id`、`name`、`version`、`vendor`；
- `modalities`：至少一个模态；
- `platforms`：如 `windows-x64`、`linux-x64`、`linux-arm64`；
- `adapter_class`：插件内模块和类名；
- `capabilities`：检测、提取、比较、活体、用户管理等；
- `permissions`：相机、麦克风、串口、模型目录等；
- `native_libraries`：插件内原生库相对路径；
- `license_path`、`model_path`；
- `min_app_version`、`enabled_by_default`。

平台、能力和权限均使用白名单。未知字段组合、空模态、错误协议版本或非法适配器路径会被拒绝。

## 3. 完整性与安全

插件包递归计算除 `signature.sig` 外所有文件的 SHA256，生成规范化哈希，再使用 Ed25519 公钥验证签名。

默认策略：

- 未签名插件拒绝安装；
- 仅开发测试可通过 `CAOS_ALLOW_UNSIGNED_PLUGINS=true` 或 `allow_unsigned=True` 放行；
- 原生库、License、模型路径禁止绝对路径、`..` 和符号链接；
- ZIP 解压强制检查 zip slip 和路径越界；
- 插件复制到受控目录后才允许注册；
- 启用时实际加载适配器并执行 `check_available()`，失败则保持禁用。

## 4. 注册中心

`PluginManager` 使用 SQLite 保存注册表和审计表，支持：

- 安装与替换；
- 列表和详情查询；
- 启用、停用；
- 健康检查；
- 适配器动态加载；
- 审计记录。

Web 管理 API 提供插件列表、安装、启用、停用、健康检查和标准模板导入路由。

## 5. 百度人脸示例

示例插件位于：

```text
plugins/available/baidu_face/
├── plugin.toml
└── adapter.py
```

Windows C ABI 包装层位于：

```text
vendor_wrappers/baidu_face/
├── caos_bdface.h
├── caos_bdface.cpp
├── CMakeLists.txt
└── build.ps1
```

当前包装层已可构建出 `caos_bdface.dll`，Python 侧由 `BaiduFaceSDKAdapter` 加载。由于当前设备尚未完成百度 License 激活，真机离线识别、活体和精度仍需授权后验收。

## 6. 上线边界

真实厂商 SDK 上线前至少完成：

1. 设备指纹和 License 激活；
2. 原生库运行时依赖检查；
3. 管理员确认和审计；
4. 单独同意与个人信息保护影响评估；
5. 真机 FAR、FRR、EER 和 PAD 攻击测试；
6. 模型与 SDK 同源模板比对验证；
7. 插件禁用、回退和卸载流程演练。
