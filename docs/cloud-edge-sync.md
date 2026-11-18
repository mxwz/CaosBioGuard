# 云边同步协议（v1）

## 1. 现状与耦合问题

旧实现中边缘端通过 `managers.py` 直接连接 MySQL / 调用云端 HTTP，问题：

1. **强耦合**：边缘端进程持有 MySQL 连接池与云端地址，云端不可达时业务写入直接失败或阻塞。
2. **无幂等**：网络超时后重试可能产生重复考勤/门禁事件。
3. **无签名**：同步接口只靠网络边界，事件可被伪造或篡改。
4. **无退避**：失败后立即重试，云端抖动时形成重试风暴。
5. **不可观测**：失败事件没有持久化死信，排障只能翻日志。

## 2. 新模型：Outbox → 批量推送 → 云端去重

```
边缘端业务写入
   │  (本地 SQLite 事务)
   ├── 业务表（records / events / biometrics）
   └── sync_outbox(event_type, payload, idempotency_key, next_at)
             │
             ▼
       SyncClient.flush()
             │  POST /api/sync/events（HMAC 签名）
             ▼
云端按 idempotency_key 去重 → 返回 accepted / duplicates
             │
             ▼
       mark_acked() / mark_retry(指数退避 + 抖动)
```

代码：`biometrics/sync.py`（`SyncOutbox` / `SyncClient` / `SyncConfig`）。

## 3. 请求契约

`POST {endpoint}`，`Content-Type: application/json; charset=utf-8`。

请求头：

| Header | 说明 |
|---|---|
| `X-Caos-Device` | 边缘设备 ID |
| `X-Caos-Timestamp` | Unix 秒；服务端允许 ±300s 偏移 |
| `X-Caos-Signature` | `HMAC_SHA256(secret, f"{timestamp}.{body}")` 的小写 hex |

请求体必须是 **canonical JSON**（`sort_keys=True`、无空格分隔符、UTF-8、不转义中文）：

```json
{
  "device_id": "edge-001",
  "sent_at": 1763500000.0,
  "events": [
    {
      "idempotency_key": "attendance:9f2c...",
      "type": "attendance",
      "payload": {"user_name": "张三", "status": "正常", "timestamp": "2026-11-18 09:01:00"},
      "created_at": 1763500000.0
    }
  ]
}
```

响应：

```json
{"accepted": ["attendance:9f2c..."], "duplicates": []}
```

- `accepted`：本次新写入的事件 key；
- `duplicates`：云端已存在、按幂等键忽略的事件 key；
- 未出现在任一列表中的 key 视为失败，进入退避重试。

## 4. 重试与死信

- 指数退避：`min(base_delay * 2^(attempts-1), 3600)` 秒，叠加 0~30% 抖动。
- `attempts >= max_attempts` 标记 `dead`，保留在 outbox 供人工重放。
- 建议边缘端每 30~60 秒调用一次 `flush()`；云端恢复后自动追平。

## 5. 云端实现要点

1. 先验签，再解析 JSON；时间戳超窗直接 401。
2. `idempotency_key` 建唯一索引；插入冲突即视为 duplicate。
3. 单事务写入本批 accepted，避免部分成功。
4. 返回前不要做重业务；异步落库可用但需保证 key 已持久化。
5. 建议按 `device_id` 做限流与审计。

## 6. 迁移步骤

1. 边缘端配置 `[Sync] endpoint/secret/device_id`，启动时 `SyncOutbox('./dd/sync_outbox.db')`。
2. 业务写入后调用 `outbox.enqueue('attendance', payload)`，替换原直接 HTTP。
3. 后台线程定时 `SyncClient.flush()`；管理页展示 `stats()` 与 `dead_letters()`。
4. 云端上线 `/api/sync/events` 后再切流量；旧 MySQL 直连保留只读回退。
5. 观察 `acked / retry / dead` 三个指标，稳定后移除直连。

## 7. 安全建议

- `secret` 每设备独立，存放在系统密钥库/环境变量，不写入仓库。
- 全链路 HTTPS；内网也建议签名，防横向移动。
- HMAC 只保证完整性与来源，不替代 TLS。
- 事件 payload 不含原始生物特征模板；模板同步走独立加密通道（Fernet + 设备公钥）。
