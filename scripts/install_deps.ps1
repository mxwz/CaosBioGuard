#Requires -Version 5.1
<#
.SYNOPSIS
    CaosBioGuard 一键依赖安装脚本（Windows）
.DESCRIPTION
    自动识别操作系统与 CPU 架构，创建或复用项目根目录下的 .venv 虚拟环境，
    并按角色安装 requirements/ 目录中对应的依赖文件。
.PARAMETER Role
    依赖角色：edge（边缘 Kiosk，默认）、web（Web 服务）、build（打包工具）、all（全部）
.PARAMETER Python
    自定义基础 Python 可执行文件路径或命令；默认自动查找 py / python / python3。
.PARAMETER SystemPython
    直接安装到当前 Python 环境，不创建 .venv（不推荐）。
.EXAMPLE
    .\scripts\install_deps.ps1
.EXAMPLE
    .\scripts\install_deps.ps1 -Role web
.EXAMPLE
    .\scripts\install_deps.ps1 -Role all
#>
param(
    [ValidateSet('edge', 'web', 'build', 'all')]
    [string]$Role = 'edge',
    [string]$Python,
    [switch]$SystemPython
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- 操作系统与架构识别 ---
if ($IsWindows -or $env:OS -eq 'Windows_NT') { $osName = 'Windows' }
elseif ($IsLinux) { $osName = 'Linux' }
elseif ($IsMacOS) { $osName = 'macOS' }
else { $osName = 'Unknown' }

switch ($env:PROCESSOR_ARCHITECTURE) {
    'AMD64' { $archName = 'x86_64 (64位)' }
    'ARM64' { $archName = 'ARM64 (64位)' }
    'ARM'   { $archName = 'ARM (32位)' }
    default { $archName = $env:PROCESSOR_ARCHITECTURE }
}
Write-Host "==> 运行平台: $osName / CPU 架构: $archName" -ForegroundColor Cyan

# --- 选择基础 Python ---
if (-not $Python) {
    foreach ($c in @('py', 'python', 'python3')) {
        if (Get-Command $c -ErrorAction SilentlyContinue) { $Python = $c; break }
    }
}
if (-not $Python) {
    throw '未找到 Python，请先安装 Python 3.13，或通过 -Python 指定可执行文件路径。'
}
& $Python --version | Out-Null

# --- 创建或复用虚拟环境 ---
$venvDir = Join-Path $root '.venv'
if ($SystemPython) {
    $pyExe = $Python
    Write-Host '==> 使用系统 Python，不创建 .venv' -ForegroundColor Yellow
} else {
    if (-not (Test-Path $venvDir)) {
        Write-Host "==> 创建虚拟环境: $venvDir" -ForegroundColor Cyan
        & $Python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            throw '创建虚拟环境失败。请确认已安装标准 Python（含 venv 模块），或使用 -SystemPython。'
        }
    } else {
        Write-Host "==> 复用已有虚拟环境: $venvDir" -ForegroundColor Cyan
    }
    $pyExe = Join-Path $venvDir 'Scripts\python.exe'
    if (-not (Test-Path $pyExe)) { throw "虚拟环境不完整，缺少: $pyExe" }
}

# --- 解析角色对应的依赖文件 ---
$reqMap = @{
    edge  = 'requirements-edge.txt'
    web   = 'requirements-web.txt'
    build = 'requirements-build.txt'
}
if ($Role -eq 'all') {
    $files = @($reqMap.edge, $reqMap.web, $reqMap.build)
} else {
    $files = @($reqMap[$Role])
}
foreach ($f in $files) {
    $full = Join-Path $root (Join-Path 'requirements' $f)
    if (-not (Test-Path $full)) { throw "缺少依赖文件: $full" }
}

Write-Host '==> 升级 pip / setuptools / wheel' -ForegroundColor Cyan
& $pyExe -m pip install --upgrade pip setuptools wheel

foreach ($f in $files) {
    $full = Join-Path $root (Join-Path 'requirements' $f)
    Write-Host "==> 安装依赖: requirements/$f" -ForegroundColor Green
    & $pyExe -m pip install -r $full
    if ($LASTEXITCODE -ne 0) { throw "安装 $f 失败" }
}

Write-Host "==> 依赖安装完成（角色: $Role）。建议执行: & '$pyExe' -m pytest -q" -ForegroundColor Green
