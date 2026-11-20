$ErrorActionPreference = 'Stop'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..' '..')
$sdkRoot = Join-Path $projectRoot 'TEMP' 'baidu_face_SDK' 'extracted' 'Windows_Cpp_8.4' 'FaceOfflineSdk'
$buildDir = Join-Path $projectRoot 'vendor_wrappers' 'build' 'baidu_face'
$cmake = 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'

if (-not (Test-Path $sdkRoot)) {
    throw "Baidu SDK not found: $sdkRoot"
}

& $cmake -S $PSScriptRoot -B $buildDir -A x64 "-DBDFACE_SDK_ROOT=$sdkRoot"
& $cmake --build $buildDir --config Release
