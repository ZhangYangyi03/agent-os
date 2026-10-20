# uninstall.ps1 -- 停掉并删掉 KmHello 服务，删掉驱动文件。
# 用法（管理员）: powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1
$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "要管理员。" }

& sc.exe stop KmHello 2>$null | Out-Null
Start-Sleep -Seconds 1
& sc.exe delete KmHello 2>$null | Out-Null
$dest = Join-Path $env:SystemRoot 'System32\drivers\KmHello.sys'
if (Test-Path $dest) { Remove-Item $dest -Force }
Write-Host "已卸载 KmHello。" -ForegroundColor Green
Write-Host "要彻底恢复环境: scripts\enable-testsigning.ps1 -Undo，然后进 BIOS 打开 Secure Boot，再重启。" -ForegroundColor Yellow
