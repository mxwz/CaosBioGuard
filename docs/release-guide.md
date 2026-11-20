# Caos BioGuard - Release & GPG Signature Guide

为确保发布版本（Release）的真实性和完整性，防止他人冒用名义发布恶意代码，我们建议对每一个发布的版本进行 GPG（GNU Privacy Guard）签名。

以下是完整的 GPG 签名与验证流程指南：

## 1. 安装 GPG 工具
- **Windows**: 下载并安装 [Gpg4win](https://gpg4win.org/)。
- **macOS**: 使用 Homebrew 安装 `brew install gnupg`，或下载 [GPG Suite](https://gpgtools.org/)。
- **Linux (Ubuntu/Debian)**: 运行 `sudo apt install gnupg`。

## 2. 生成 GPG 密钥对
如果您还没有 GPG 密钥，请在终端（命令行）中运行以下命令生成：
```bash
gpg --full-generate-key
```
1. 选择密钥类型（默认 `RSA and RSA` 即可）。
2. 选择密钥长度（推荐 `4096` 位）。
3. 选择过期时间（可选择永不过期，或设置 `1y` 等）。
4. 输入您的真实姓名、邮箱地址（须与 GitHub 邮箱一致）和备注。
5. 设置一个强密码（Passphrase）保护您的私钥。

## 3. 获取您的密钥 ID
运行以下命令列出您的密钥：
```bash
gpg --list-secret-keys --keyid-format=long
```
输出示例：
```
sec   rsa4096/3AA5C34371567BD2 2026-06-29 [SC]
```
这里的 `3AA5C34371567BD2` 就是您的密钥 ID。

## 4. 将公钥上传至 GitHub
1. 导出公钥：
   ```bash
   gpg --armor --export 3AA5C34371567BD2
   ```
2. 复制输出的全部内容（包括 `-----BEGIN PGP PUBLIC KEY BLOCK-----` 和结尾）。
3. 登录 GitHub -> `Settings` -> `SSH and GPG keys` -> `New GPG key`，粘贴并保存。

## 5. 在本地 Git 中配置 GPG 签名
告诉 Git 您的密钥 ID，并开启全局签名：
```bash
git config --global user.signingkey 3AA5C34371567BD2
git config --global commit.gpgsign true
```

## 6. 签名发布版本 (Release)
当您准备发布一个新版本（如 `v1.0.0`）时，创建一个带签名的 Git 标签（Tag）：
```bash
git tag -s v1.0.0 -m "Release v1.0.0"
```
（系统会提示您输入之前设置的 GPG 私钥密码）。

然后将标签推送到远程仓库：
```bash
git push origin v1.0.0
```
在 GitHub 的 Release 页面中，带有该 Tag 的版本旁边会自动显示一个绿色的 **Verified** 徽章。

## 7. 为打包的二进制文件或压缩包签名（可选）
如果您对外提供预编译的压缩包（如 `CaosBioGuard-v1.0.0-win64.zip`），您也可以单独对其签名：
```bash
gpg --armor --detach-sign CaosBioGuard-v1.0.0-win64.zip
```
这会生成一个名为 `CaosBioGuard-v1.0.0-win64.zip.asc` 的签名文件。
您可以将这个 `.asc` 文件与压缩包一起上传到 GitHub Release 的附件中。用户下载后，可以通过以下命令验证：
```bash
gpg --verify CaosBioGuard-v1.0.0-win64.zip.asc CaosBioGuard-v1.0.0-win64.zip
```
