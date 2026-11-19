param(
    [string]$Script = (Join-Path $PSScriptRoot "windows_installer.iss"),
    [switch]$SkipCompile
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($iscc) {
    $compiler = $iscc.Source
} else {
    $candidates = @(
        Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
        "C:\Program Files\Inno Setup 6\ISCC.exe"
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    )
    $compiler = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $compiler) {
    throw "ISCC.exe not found. Please install Inno Setup or add it to PATH."
}

if (-not (Test-Path $Script)) {
    throw "Inno Setup script not found: $Script"
}

if ($SkipCompile) {
    Write-Host "Inno Setup compiler found: $compiler"
    return
}

& $compiler $Script
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }

$out = Join-Path $root "dist\installer\CaosBioGuardKioskSetup.exe"
if (Test-Path $out) {
    Write-Host "Installer build completed: $out"
}
