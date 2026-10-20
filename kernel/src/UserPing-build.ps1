# UserPing-build.ps1 -- 单独编用户态那半边。只需要 cl.exe，不需要 WDK。
# 用法: 先跑 VS 的 "x64 Native Tools Command Prompt"，再
#       powershell -ExecutionPolicy Bypass -File src\UserPing-build.ps1

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    throw "当前会话里没有 cl.exe。用开始菜单里的 'x64 Native Tools Command Prompt for VS' 打开再来。"
}

New-Item -ItemType Directory -Force -Path (Join-Path $root 'out') | Out-Null
Push-Location $here
try {
    & cl.exe /nologo /W4 /O2 /utf-8 UserPing.c /Fe:"$root\out\UserPing.exe" user32.lib
    if ($LASTEXITCODE -ne 0) { throw "cl 失败，退出码 $LASTEXITCODE" }
    Write-Host ""
    Write-Host ("编好了: " + (Join-Path $root 'out\UserPing.exe')) -ForegroundColor Green
} finally { Pop-Location }
