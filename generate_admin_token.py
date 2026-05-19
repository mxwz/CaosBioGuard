import hashlib
import secrets
import sys

def hash_password(password, salt):
    """
    MD5(password + salt)
    与 web_admin/app.py 中的逻辑保持一致
    """
    return hashlib.md5((password + salt).encode()).hexdigest()

def main():
    print("=== ArcFace Web Admin Token 生成工具 ===")
    
    # 支持命令行参数或交互式输入
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        try:
            # Python 3
            password = input("请输入新的管理员密码 (明文): ").strip()
        except KeyboardInterrupt:
            print("\n已取消")
            return

    if not password:
        print("错误: 密码不能为空")
        return

    # 生成随机盐 (4字节 -> 8 hex字符，与 app.py 默认一致)
    salt = secrets.token_hex(4)
    
    # 计算哈希
    token = hash_password(password, salt)
    
    print("\n生成成功！")
    print("请将以下内容更新到您的 config.ini 文件中 [WebAdmin] 部分：")
    print("-" * 50)
    print(f"token = {token}")
    print(f"salt = {salt}")
    print("-" * 50)
    
    print(f"\n验证信息:")
    print(f"明文密码: {password}")
    print(f"生成的盐: {salt}")
    print(f"最终Token: {token}")

if __name__ == "__main__":
    main()
