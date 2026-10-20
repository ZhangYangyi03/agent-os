# build.ps1 -- 用 MSBuild 编 KmHello.sys
# 需要: VS Build Tools(含 C++ 桌面开发) + WDK。
# 用法: powershell -ExecutionPolicy Bypass -File src\build.ps1

$ErrorActionPreference = 'Stop'


# ---- 环境兜底 ------------------------------------------------
# 有些受限环境里 %ProgramFiles(x86)% 不在进程环境里（实测：从沙箱子进程启动
# PowerShell 时它读到的是 $null），直接 Join-Path 会报路径为空的错。写两个
# 变量兜住，比让整个脚本在第一行就崩掉好。
$PF86 = ${env:ProgramFiles(x86)}
if (-not $PF86) { $PF86 = 'C:\Program Files (x86)' }
$PF64 = ${env:ProgramFiles}
if (-not $PF64) { $PF64 = 'C:\Program Files' }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

$vswhere = Join-Path $PF86 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) {
    throw "找不到 vswhere。先装 VS Build Tools: https://aka.ms/vs/17/release/vs_BuildTools.exe"
}
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "Build Tools 里没装 C++ 工具链（勾'使用 C++ 的桌面开发'）。" }

$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
if (-not (Test-Path $msbuild)) { throw "找到 VS 但没有 MSBuild: $msbuild" }

$kits = Join-Path $PF86 'Windows Kits\10\Include'
if (-not (Test-Path $kits)) { throw "没有 Windows SDK。装 WDK 时会一起装。" }

# 这条生成器把 WDK 的 KMDF 模板接进 MSBuild。没有它就编不出 .sys。
$kmdfProps = Join-Path $PF86 'Windows Kits\10\build\Kmdf.props'
if (-not (Test-Path $kmdfProps)) {
    Write-Host "提示: 没找到 Kmdf.props，WDK 可能没装全，先跑 scripts\preflight.ps1" -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path (Join-Path $root 'out') | Out-Null

& $msbuild (Join-Path $here 'KmHello.vcxproj') `
    /p:Configuration=Release /p:Platform=x64 `
    /p:OutDir="$root\out\" /m /v:minimal
if ($LASTEXITCODE -ne 0) { throw "编译失败，退出码 $LASTEXITCODE" }

$sys = Join-Path $root 'out\KmHello.sys'
if (Test-Path $sys) {
    Write-Host ""
    Write-Host ("编好了: " + $sys) -ForegroundColor Green
    Write-Host ("大小  : " + (Get-Item $sys).Length + " 字节")
    Write-Host "下一步: 管理员跑 scripts\enable-testsigning.ps1 -> 重启 -> scripts\testsign.ps1 -> scripts\install.ps1"
} else {
    throw "MSBuild 说成功了，但 out\KmHello.sys 不存在。看上面的输出。"
}
