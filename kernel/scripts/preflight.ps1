# preflight.ps1 -- 环境自检。不需要管理员，跑完就知道下一步该干什么。
# 用法: powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1

$ErrorActionPreference = 'Continue'


# ---- 环境兜底 ------------------------------------------------
# 有些受限环境里 %ProgramFiles(x86)% 不在进程环境里（实测：从沙箱子进程启动
# PowerShell 时它读到的是 $null），直接 Join-Path 会报路径为空的错。写两个
# 变量兜住，比让整个脚本在第一行就崩掉好。
$PF86 = ${env:ProgramFiles(x86)}
if (-not $PF86) { $PF86 = 'C:\Program Files (x86)' }
$PF64 = ${env:ProgramFiles}
if (-not $PF64) { $PF64 = 'C:\Program Files' }
# Same for System32: a PowerShell started from an environment without the
# normal PATH cannot resolve bcdedit / where / sc, and "not found" then looks
# exactly like "the setting is off". Use absolute paths for the native tools.
$WinRoot = $env:SystemRoot
if (-not $WinRoot) { $WinRoot = 'C:\Windows' }
$Sys32 = Join-Path $WinRoot 'System32'
$Bcdedit = Join-Path $Sys32 'bcdedit.exe'
if (-not (Test-Path $Bcdedit)) { $Bcdedit = 'bcdedit.exe' }
function Line($name, $ok, $detail) {
    $mark = if ($ok) { '[ok]  ' } else { '[缺]  ' }
    $color = if ($ok) { 'Green' } else { 'Yellow' }
    Write-Host ($mark + $name.PadRight(28) + $detail) -ForegroundColor $color
}

Write-Host ""
Write-Host "== 系统 ==" -ForegroundColor Cyan
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor
Write-Host ("     " + $os.Caption + "  build " + $os.BuildNumber)
Write-Host ("     " + $cpu.Name + "  |  " + $cs.Model)
$edition = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').EditionID
Line "Windows 版本" ($true) $edition

Write-Host ""
Write-Host "== 权限 ==" -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Line "管理员" $isAdmin ($(if ($isAdmin) { "是" } else { "否 —— 装驱动要管理员，右键以管理员身份运行 PowerShell" }))

Write-Host ""
Write-Host "== 编译工具链 ==" -ForegroundColor Cyan
$vswhere = Join-Path $PF86 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsPath = $null
if (Test-Path $vswhere) { $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath }
Line "Visual Studio / BuildTools" ([bool]$vsPath) ($(if ($vsPath) { $vsPath } else { "没装 —— 去 https://aka.ms/vs/17/release/vs_BuildTools.exe 勾'使用C++的桌面开发'" }))

$kits = Join-Path $PF86 'Windows Kits\10\Include'
Line "Windows SDK" (Test-Path $kits) ($(if (Test-Path $kits) { (Get-ChildItem $kits | Select-Object -Expand Name) -join ', ' } else { "没装 —— 装 VS Build Tools 时一起勾上" }))

# WDK: 装在 Windows Kits 下的算一份，仓库里从 NuGet 解出来的 vendor\wdk 也算一份。
# 两处的头文件是同一批，区别只是有没有被登记到系统里。
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$vendored = Get-ChildItem (Join-Path $root 'vendor\wdk') -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
$wdf = Get-ChildItem $kits -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'km\wdf') }
if (-not $wdf -and $vendored) { $wdf = @([pscustomobject]@{ Name = ('vendor\wdk\' + $vendored.Name) }) }
Line "WDK (km 头/库)" ([bool]$wdf) ($(if ($wdf) { ($wdf | Select-Object -Expand Name) -join ', ' } else { "没装 —— scripts\fetch_wdk.py 可以从 NuGet 取" }))

$signtool = Get-ChildItem (Join-Path $PF86 'Windows Kits\10\bin') -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $signtool -and $vendored) {
    $signtool = Get-ChildItem (Join-Path $vendored.FullName 'c\bin') -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue | Select-Object -First 1
}
Line "signtool" ([bool]$signtool) ($(if ($signtool) { $signtool.FullName } else { "随 Windows SDK 一起装（NuGet 那份里没有它）" }))

# 编译器：头的有无不重要，能编 .sys 的是 cl.exe + link.exe + MSBuild
$cl = $null
if ($vsPath) {
    $cl = Get-ChildItem (Join-Path $vsPath 'VC\Tools\MSVC') -Recurse -Filter cl.exe -ErrorAction SilentlyContinue |
          Where-Object { $_.FullName -match 'Hostx64\\x64' } | Select-Object -First 1
}
Line "cl.exe (编译器)" ([bool]$cl) ($(if ($cl) { $cl.FullName } else { "没有 —— 缺的就是这一样，见 docs\kernel-debug-in-vm.md" }))

Write-Host ""
Write-Host "== 测试签名与安全启动 ==" -ForegroundColor Cyan
$bcd = ''
try { $bcd = & $Bcdedit /enum '{current}' 2>$null | Out-String } catch { $bcd = '' }
if (-not $bcd) { $bcd = '(读不到 bcdedit 输出，可能不是管理员或 PATH 缺 System32)' }
$ts = $bcd -match 'testsigning\s+Yes'
Line "测试签名模式 (testsigning)" $ts ($(if ($ts) { "已开" } else { "未开 —— scripts\enable-testsigning.ps1" }))
$dbg = $bcd -match 'debug\s+Yes'
Line "内核调试 (debug)" $dbg ($(if ($dbg) { "已开" } else { "未开 —— 只在需要 WinDbg 时开" }))

$sb = $null
try { $sb = Confirm-SecureBootUEFI } catch { $sb = "无法读取(需管理员)" }
Line "安全启动 (Secure Boot)" ($sb -eq $false) ("$sb  —— 开测试签名要求它关掉")

Write-Host ""
Write-Host "== 现有虚拟化 ==" -ForegroundColor Cyan
$hv = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
Line "hypervisor 在跑" $hv ($(if ($hv) { "是（VBS/虚拟机监控程序）。不代表有 Hyper-V 管理器" } else { "否" }))
$vbox = Get-Command VBoxManage.exe -ErrorAction SilentlyContinue
Line "VirtualBox" ([bool]$vbox) ($(if ($vbox) { $vbox.Source } else { "没装 —— 建议装它做实验田，别用主力机" }))
$vmrun = Get-Command vmrun.exe -ErrorAction SilentlyContinue
Line "VMware Workstation/Player" ([bool]$vmrun) ($(if ($vmrun) { $vmrun.Source } else { "没装" }))
$editionNow = $edition
if ($editionNow -like '*Core*') {
    Write-Host "     注意：家庭版没有 Hyper-V 管理器。用 VirtualBox 或 VMware，别指望 Hyper-V。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== 结论 ==" -ForegroundColor Cyan
$missing = @()
if (-not $vsPath) { $missing += 'Visual Studio Build Tools' }
if (-not (Test-Path $kits)) { $missing += 'Windows SDK' }
if (-not $wdf) { $missing += 'WDK' }
if (-not $isAdmin) { $missing += '管理员权限（装驱动那几步要）' }
if (-not $ts) { $missing += '测试签名模式（要重启）' }
if ($missing.Count -eq 0) {
    Write-Host "     齐了，可以 build → sign → install。" -ForegroundColor Green
} else {
    Write-Host ("     还缺: " + ($missing -join ' / ')) -ForegroundColor Yellow
    Write-Host "     下一步: 先装 Build Tools 和 WDK，再回来跑一遍本脚本。" -ForegroundColor Yellow
}
Write-Host ""
