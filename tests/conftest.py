"""pytest 测试自举配置。

保证测试套件在任何机器（新开发机、CI、Docker、离线环境）都能直接运行，
不依赖宿主机预设的环境变量或本地 config.ini。

注意：这里设置的仅为测试进程内的临时密钥与平台参数，不会写入任何文件，
也不影响真实部署；生产环境仍必须通过环境变量或本地 config.ini 提供真实密钥。
"""

import os

# 无显示环境（服务器 / 容器 / CI）下使用 Qt 离屏平台；本地有桌面环境时不覆盖。
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

# 模板加密密钥：环境未提供时生成进程内临时 Fernet 密钥，
# 避免干净机器上因“模板加密未启用，禁止明文写入”而失败。
if not os.environ.get('CAOS_ENCRYPTION_KEY'):
    from cryptography.fernet import Fernet

    os.environ['CAOS_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
