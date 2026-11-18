# 多生物特征 API（/api/biometrics）

鉴权：管理员 session，或请求头 `Authorization: Bearer <[WebAdmin] token>`（也接受 `X-Auth-Token`）。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 引擎可用数、模板统计、版本 |
| GET | `/modalities` | 9 模态规格、阈值、依赖可用性 |
| GET | `/subjects` | 已注册主体及其模态 |
| GET | `/stats` | 各模态模板数量与平均质量 |
| DELETE | `/subjects/<subject>` | 删除该主体全部模板 |
| POST | `/quality` | 仅做质量评估，不写库 |
| POST | `/enroll` | 注册模板 |
| POST | `/verify` | 1:N 验证 |

人脸模态在 `/api/biometrics/enroll|verify` 返回 `409`，请继续使用 `/faces`、`/api/face_compare`，避免同一人脸双写。

## 样本格式

`POST /enroll` 与 `/verify` 支持两种请求：

### multipart/form-data

| 字段 | 适用模态 |
|---|---|
| `subject` | 注册必填 |
| `modality` | `voiceprint/fingerprint/iris/palmprint/vein/gait/retina/signature` |
| `file` | 图片（除声纹/步态/签名外）、WAV、步态视频 |
| `strokes` | 签名轨迹 JSON 字符串，如 `[[[x,y,t],...]]` |
| `device_id` | 可选，默认 `WEB` |

### application/json

```json
{
  "subject": "张三",
  "modality": "iris",
  "image_base64": "data:image/png;base64,...",
  "device_id": "edge-001"
}
```

声纹用 `audio_base64`（WAV）；步态用 `frames_base64` 列表或 `file` 视频；
签名用 `strokes` 数组，可选 `image_base64` 签名图。

## 响应

```json
{"status": "ok", "data": {"ok": true, "quality": 0.86, "samples": 1, "template_bytes": 4211}}
```

`/verify`：

```json
{"status":"ok","data":{"passed":true,"match":{"subject":"张三","score":0.91,"threshold":0.6,"quality":0.88,"margin":0.12,"details":{}}}}
```

## 手机端

移动端聚合 API 在 `/api/mobile`：`login`、`overview`、`records`、`devices`、`profile`、`enroll-request`、`enroll-requests`。员工用 `X-Mobile-Subject` 查看本人数据；管理员用同一 Bearer token。
