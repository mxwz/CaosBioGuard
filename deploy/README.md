# Docker / Compose 部署

## 1. 准备配置

```bash
cp deploy/config.docker.ini.example config.ini
# 修改 [WebAdmin] token、[Security] encryptionkey、[Kiosk] admin_pin
```

- `[Cloud] enabled=false`：Web 用本地 SQLite + 目录，最简启动。
- 改为 `true` 并填 `[MySQL]`/`[S3]`：Web 用 MySQL + R2；compose 已带 MySQL。
- `[MySQL] host=mysql` 是容器内服务名，不要写 127.0.0.1。

## 2. 启动 Web + MySQL

```bash
docker compose up -d --build web
# 访问 http://localhost:5000
# 手机 PWA: http://localhost:5000/m/
```

## 3. 启用边缘端（需要 X11 与摄像头）

```bash
export DISPLAY=:0
docker compose --profile edge up -d --build edge
```

Linux 主机先允许容器访问 X11：

```bash
xhost +local:docker
```

边缘端需要 `/dev/video0` 与 `~/.insightface` 模型；Windows/macOS 的 Docker Desktop 不支持直接透传摄像头，GUI 边缘端建议原生 PyInstaller 包。

## 4. 常用命令

```bash
docker compose logs -f web
docker compose exec web python -c "import flask; print(flask.__version__)"
docker compose down          # 保留 mysql_data / dd 数据
docker compose down -v       # 连数据库一起删除（谨慎）
```

## 5. 生产建议

- 前面加 Nginx/Caddy 做 TLS；小程序要求 HTTPS 域名。
- `config.ini` 只读挂载，密钥用 Docker secret 或环境变量注入。
- MySQL 备份：`docker compose exec mysql mysqldump -u root -p caos_bioguard > backup.sql`
- 边缘端与 Web 分机部署时，把 `[WebAdmin] host` 指向 Web、`[Sync] endpoint` 指向同步接口。
