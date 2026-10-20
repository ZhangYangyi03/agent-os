# install.ps1 -- 把已签名的 KmHello.sys 装成一个内核服务并启动。
# 用法（管理员）:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
param([string]$Sys = "")
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "要管理员。" }

if (-not $Sys) { $Sys = Join-Path $root 'out\KmHello.sys' }
if (-not (Test-Path $Sys)) { throw "找不到 $Sys。先 build 再 testsign。" }

$bcd = & bcdedit /enum '{current}' | Out-String
if ($bcd -notmatch 'testsigning\s+Yes') {
    Write-Host "测试签名模式没开，装上去也不会加载。先跑 scripts\enable-testsigning.ps1 并重启。" -ForegroundColor Yellow
}

$dest = Join-Path $env:SystemRoot 'System32\drivers\KmHello.sys'

Write-Host "== 复制到 $dest ==" -ForegroundColor Cyan
Copy-Item $Sys $dest -Force

# 已经在跑就先停
$existing = & sc.exe query KmHello 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "服务已存在，先停掉再重写。" -ForegroundColor Yellow
    & sc.exe stop KmHello | Out-Null
    Start-Sleep -Seconds 1
    & sc.exe delete KmHello | Out-Null
    Start-Sleep -Seconds 1
}

Write-Host "== 创建内核服务 ==" -ForegroundColor Cyan
& sc.exe create KmHello type= kernel start= demand binPath= $dest DisplayName= "KmHello minimal KMDF control device"
if ($LASTEXITCODE -ne 0) { throw "sc create 失败（$LASTEXITCODE）。" }

Write-Host "== 启动 ==" -ForegroundColor Cyan
& sc.exe start KmHello
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "启动失败。最常见两个原因:" -ForegroundColor Yellow
    Write-Host "  1) 测试签名没开 / Secure Boot 还开着 / HVCI 还开着  -> bcdedit 和 BIOS 里确认" -ForegroundColor Yellow
    Write-Host "  2) 文件没签名或签名证书不在受信任根里 -> 重跑 scripts\testsign.ps1" -ForegroundColor Yellow
    Write-Host "看内核日志: Event Viewer -> Windows Logs -> System，来源 'KmHello'" -ForegroundColor Yellow
    throw "sc start 失败（$LASTEXITCODE）。"
}

Write-Host ""
& sc.exe query KmHello
Write-Host ""
Write-Host "装了并跑起来了。下一步: out\UserPing.exe  —— 它会从核心里把数字取回来。" -ForegroundColor Green
