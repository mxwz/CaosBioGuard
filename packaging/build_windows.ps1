param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path $Python)) {
    throw "未找到 Python: $Python；请先创建 .venv 并安装 requirements/requirements-edge.txt + requirements/requirements-build.txt"
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "缺少 PyInstaller，请执行: $Python -m pip install -r requirements/requirements-build.txt"
}

$args = @("-m", "PyInstaller", "packaging\edge_kiosk.spec", "--noconfirm")
if ($Clean) { $args += "--clean" }
& $Python @args

if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

$out = Join-Path $root "dist\CaosBioGuardKiosk\CaosBioGuardKiosk.exe"
if (Test-Path $out) {
    Write-Host "构建完成: $out"
    Write-Host "首次运行会在 exe 同级生成 config.ini / dd/；请把 config.ini 与模型文件放到同一目录。"
} else {
    Write-Host "构建完成，但未找到 exe，请检查 dist 目录。"
}
