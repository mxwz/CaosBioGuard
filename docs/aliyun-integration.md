# 阿里云人脸四条产品线接入说明

## 1. 范围

当前批次同时预留以下四条路线，但它们属于不同产品和计费链路，不能合并成一个 SDK：

| 路线 | 模块/接口 | 运行位置 | 当前能力 |
|---|---|---|---|
| VIAPI Facebody | `alibabacloud_facebody20191230`，`CompareFace` | 服务端 | 云端 1:1 人脸比对 |
| IMM | `alibabacloud_imm20200930`，`CompareImageFaces` | 服务端 + OSS | 基于 OSS URI 的人脸相似度对比 |
| CloudAuth | `alibabacloud_cloudauth20190307` | 服务端 | 金融级实人、活体、认证工单流程 |
| Android AAR | 阿里云实人认证 Android SDK | 手机原生层 | 端侧采集、MetaInfo、活体和认证 |

无密钥阶段默认通过 `mock=true` 跑通“可用性 → 质量 → 引用模板 → 同图/异图比分 → 活体”的最小链路，不访问阿里云。

## 2. 可选依赖

真实调用前再安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/requirements-cloud-vendors.txt
```

默认安装和基础测试不依赖这些包。

## 3. 配置方式

### Facebody

```ini
[VendorSDK.face]
enabled=true
vendor=aliyun
route=facebody
mock=false
region_id=cn-shanghai
access_key_id=${ALIBABA_CLOUD_ACCESS_KEY_ID}
access_key_secret=${ALIBABA_CLOUD_ACCESS_KEY_SECRET}
```

`CompareFace` 支持图片 URL，也可通过本地文件路径转 base64 调用。

### IMM

```ini
[VendorSDK.face]
enabled=true
vendor=aliyun
route=imm
mock=false
region_id=cn-beijing
project_name=your-project
```

IMM 2020-09-30 的 `CompareImageFaces` 需要两张同地域 OSS URI，例如：

```text
oss://your-bucket/face-a.jpg
oss://your-bucket/face-b.jpg
```

本地图片需要先上传 OSS，不能直接把本地路径传给 IMM。

### CloudAuth

```ini
[VendorSDK.face]
enabled=true
vendor=aliyun
route=cloudauth
mock=false
region_id=cn-shanghai
scene_id=your-scene-id
product_code=ID_MIN
model=NO_LIVENESS
cert_type=IDENTITY_CARD
cert_name=姓名
cert_no=身份证号
```

完整 H5/原生认证还需要 `InitFaceVerify`、`DescribeFaceVerify`、回调、Return URL 和认证场景配置。

### Android AAR

```ini
[VendorSDK.face]
enabled=true
vendor=aliyun
route=android_aar
mock=false
native_bridge_ready=true
aar_dir=mobile/capacitor/android/app/libs
```

Python 不能直接加载 AAR。真实链路必须在 Capacitor Android 工程中新增原生插件，完成：

1. 用户同意隐私政策后延迟 `ZIMFacade.install(context)`；
2. 调用 `getMetaInfos` 获取设备环境信息；
3. 服务端 `InitFaceVerify` 换取 `CertifyId` 和 `CertifyUrl`；
4. 手机端调用认证；
5. 服务端通过回调或 `DescribeFaceVerify` 获取结果。

## 4. 无密钥最小化验证

### Python 单元测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_aliyun_adapter.py
```

### Web API mock

登录管理员后调用：

```http
GET /api/biometrics/cloud-vendors/catalog
POST /api/biometrics/cloud-vendors/aliyun/mock
```

POST 可传：

```json
{"route": "facebody"}
```

`route` 可选 `facebody`、`imm`、`cloudauth`、`android_aar`。接口返回质量、两个引用模板、同图比分、异图比分和 mock 活体结果。

## 5. 密钥与合规边界

1. 密钥只能放服务端环境变量或外置安全配置，不能写入 Git、前端 JS 或 APK。
2. 建议使用最小权限 RAM 子账号，按路线分别授权，不使用主账号 AK。
3. 公网服务必须使用 HTTPS、强 Token 和回调签名校验。
4. 金融级实人认证涉及身份证、人脸、活体和风控资料，上线前需完成个人信息保护影响评估、单独同意、留存期限和注销策略复核。
5. 当前 mock 结果只证明工程链路可运行，不代表真实 FAR、FRF、活体通过率或风控效果。

## 6. 官方参考

- Facebody CompareFace：https://next.api.aliyun.com/document/facebody/2019-12-30/CompareFace
- Facebody Python SDK：https://next.api.aliyun.com/api-tools/sdk/facebody?version=2019-12-30&language=python-tea
- IMM 人脸相似度对比：https://help.aliyun.com/zh/imm/user-guide/face-similarity-comparison
- CloudAuth Python 示例：https://help.aliyun.com/zh/id-verification/financial-grade-id-verification/call-examples-of-sdk-for-python-2
- Android SDK 接入：https://help.aliyun.com/zh/id-verification/financial-grade-id-verification/integrate-sdk-for-android-into-an-android-application-2
