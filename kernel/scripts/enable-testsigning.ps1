# enable-testsigning.ps1 -- 打开测试签名模式（并可选打开内核调试）。
# 这是微软给驱动开发者的官方门，不是绕过签名。
#
# 用法（必须管理员）:
#   powershell -ExecutionPolicy Bypass -File scripts\enable-testsigning.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\enable-testsigning.ps1 -WithDebug
#   powershell -ExecutionPolicy Bypass -File scripts\enable-testsigning.ps1 -Undo
param(
    [switch]$WithDebug,
    [switch]$Undo
)

$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "要管理员。右键 PowerShell -> 以管理员身份运行，再跑这个脚本。" }

if ($Undo) {
    Write-Host "== 恢复原样 ==" -ForegroundColor Cyan
    & bcdedit /deletevalue testsigning 2>$null
    & bcdedit /deletevalue debug        2>$null
    & bcdedit /deletevalue debugtype    2>$null
    & bcdedit /deletevalue nointegritychecks 2>$null
    Write-Host "已清除 testsigning / debug / nointegritychecks。" -ForegroundColor Green
    Write-Host "如果之前为这一步关过 Secure Boot，现在要进 BIOS 重新打开它。" -ForegroundColor Yellow
    Write-Host "然后重启。" -ForegroundColor Yellow
    return
}

# ---- 先看安全启动：开着的话 testsigning 不会生效 ----
$sb = $null
try { $sb = Confirm-SecureBootUEFI } catch { $sb = $null }
if ($sb -eq $true) {
    Write-Host ""
    Write-Host "安全启动是开着的。Windows 在 Secure Boot 下不会加载测试签名的驱动。" -ForegroundColor Yellow
    Write-Host "两个选择:" -ForegroundColor Yellow
    Write-Host "  A. 进 BIOS 关掉 Secure Boot（这是主板固件的开关，微软管不到）" -ForegroundColor Yellow
    Write-Host "  B. 去虚拟机里做这件事，别动这台真机" -ForegroundColor Yellow
    Write-Host ""
    $ans = Read-Host "已经关了 Secure Boot 吗? 继续输入 y，退出输入 n"
    if ($ans -ne 'y') { Write-Host "退出了，什么都没改。"; return }
}

Write-Host "== 打开测试签名 ==" -ForegroundColor Cyan
& bcdedit /set testsigning on
if ($LASTEXITCODE -ne 0) { throw "bcdedit 失败（退出码 $LASTEXITCODE）。" }

# HVCI / 内存完整性开着时 testsigning 也不生效
$hvci = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' -ErrorAction SilentlyContinue
if ($hvci -and $hvci.Enabled -eq 1) {
    Write-Host "内存完整性(HVCI)是开着的，它会挡住测试签名驱动。" -ForegroundColor Yellow
    Write-Host "关它: Windows 安全中心 -> 设备安全性 -> 内核隔离 -> 内存完整性 -> 关，然后重启。" -ForegroundColor Yellow
}

if ($WithDebug) {
    Write-Host "== 打开内核调试 ==" -ForegroundColor Cyan
    & bcdedit /debug on
    & bcdedit /dbgsettings net hostip:0.0.0.0 port:50000
    Write-Host ""
    Write-Host "记下上面打印的 key（形如 1.2.3.4）。WinDbg 连过来时要用它。" -ForegroundColor Yellow
    Write-Host "虚拟机里做的话，把网络设成'桥接'或'仅主机'，再在宿主机上用 WinDbg 连。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "改完要重启才生效。重启后确认:" -ForegroundColor Green
Write-Host "  bcdedit /enum {current} | findstr testsigning     # 应该看到 Yes"
Write-Host "  桌面右下角会出现'测试模式'水印 ---- 这是正常现象，不是中毒。" -ForegroundColor Green
