-- 仅创建库与字符集；业务表由 web_admin/managers.py 自动迁移。
CREATE DATABASE IF NOT EXISTS caos_bioguard
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
