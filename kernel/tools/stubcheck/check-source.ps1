# check-source.ps1 -- 在没有 MSVC 的机器上，对驱动源码做一次语法/类型检查。
# 用法: powershell -ExecutionPolicy Bypass -File tools\stubcheck\check-source.ps1
#
# 为什么用 Start-Process 而不是 "& gcc ... | Out-File"：在这台机器上实测，
# 通过 Start-Process 重定向能跑，通过管道再接原生命令会报
# "无法在管道中间运行文档"（PowerShell 把 .exe 当成文档去打开了）。
# 重定向到文件是这里唯一稳定的写法。

param([switch]$TryRealWdk)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$src  = Join-Path $root 'src'

function Invoke-Native {
    # 参数名不能叫 $Args（PowerShell 的自动变量），调用时也必须具名传数组：
    # 位置参数里的 @(...) 会被展开成多个参数，$Args 只会拿到第一个。
    param([string]$Exe, [string[]]$CliArgs, [string]$WorkDir, [string]$Tag)
    $out = Join-Path $WorkDir "$Tag.out"
    $err = Join-Path $WorkDir "$Tag.err"
    $p = Start-Process -FilePath $Exe -ArgumentList $CliArgs -WorkingDirectory $WorkDir `
         -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $text = ''
    if (Test-Path $out) { $text += (Get-Content $out -Raw) }
    if (Test-Path $err) { $text += (Get-Content $err -Raw) }
    return @{ Code = $p.ExitCode; Text = $text; Out = $out; Err = $err }
}

$gcc = Get-Command gcc.exe -ErrorAction SilentlyContinue
if (-not $gcc) { $gcc = Get-Command gcc -ErrorAction SilentlyContinue }
if (-not $gcc) {
    Write-Host "[缺 gcc]  没找到 gcc，跳过源码静态检查。装了 msys2/mingw 再来。" -ForegroundColor Yellow
    exit 0
}
$gccPath = $gcc.Source
Write-Host ("gcc: " + $gccPath)

# 中文路径下 mingw 的日志会乱码；把所有输入拷到一个纯 ASCII 的临时目录再跑。
$tmp = Join-Path $env:TEMP 'kl_stubcheck'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
Copy-Item (Join-Path $src 'KmHello.c'), (Join-Path $src 'kmhello.h'), (Join-Path $src 'UserPing.c') $tmp
Copy-Item $here (Join-Path $tmp 'stub') -Recurse

# ---- 1. 驱动源码，在存根下做类型检查 ----
$r = Invoke-Native -Exe $gccPath -CliArgs @('-fsyntax-only','-Wall','-Wextra','-I','stub','KmHello.c') -WorkDir $tmp -Tag 'km'
if ($r.Code -eq 0 -and -not ($r.Text -match 'error:|warning:')) {
    Write-Host "[通过]   KmHello.c 在存根下无告警" -ForegroundColor Green
} elseif ($r.Code -eq 0) {
    Write-Host "[通过有告警] KmHello.c 编过了，但有告警:" -ForegroundColor Yellow
    ($r.Text -split "`n" | Select-Object -First 12) | ForEach-Object { Write-Host ("         " + $_) }
} else {
    Write-Host "[失败]   KmHello.c 在存根下有编译错误:" -ForegroundColor Red
    ($r.Text -split "`n" | Select-Object -First 20) | ForEach-Object { Write-Host ("         " + $_) }
    Write-Host ("         完整日志: " + $r.Out + " / " + $r.Err) -ForegroundColor Yellow
}

# ---- 2. 用户态那半边能真的编出 .exe ----
$r2 = Invoke-Native -Exe $gccPath -CliArgs @('-Wall','-Wextra','-O2','-o','UserPing.exe','UserPing.c') -WorkDir $tmp -Tag 'user'
if ($r2.Code -eq 0) {
    Write-Host "[通过]   UserPing.c 编并链接成功（gcc/mingw 版，不是最终产物）" -ForegroundColor Green
} else {
    Write-Host "[失败]   UserPing.c:" -ForegroundColor Red
    ($r2.Text -split "`n" | Select-Object -First 15) | ForEach-Object { Write-Host ("         " + $_) }
}

# ---- 3. 仓库里带了从 NuGet 取的 WDK 时，额外用真头试一次 ----
# 真 WDK 头这一步默认跳过：msys gcc 读真头会产出 1.5 MB 的报错（缺 MSVC 扩展），
# 跑一次要几分钟，结论却总是"预期失败"。要试就加 -TryRealWdk。
$wdkDir = Join-Path $root 'vendor\wdk'
$wdk = $null
if (-not $TryRealWdk) { $wdkDir = $null }
if ($wdkDir -and (Test-Path $wdkDir)) { $wdk = Get-ChildItem $wdkDir -Directory -ErrorAction SilentlyContinue | Select-Object -First 1 }
if ($wdk) {
    Write-Host ""
    Write-Host ("[真实 WDK 头] 找到 " + $wdk.FullName) -ForegroundColor Cyan
    $c = Join-Path $wdk.FullName 'c'
    $inc = @(
        '-I' + (Join-Path $c 'Include\10.0.26100.0\km'),
        '-I' + (Join-Path $c 'Include\10.0.26100.0\shared'),
        '-I' + (Join-Path $c 'Include\wdf\kmdf\1.15')
    )
    $r3 = Invoke-Native -Exe $gccPath -CliArgs (@('-fsyntax-only','-D_AMD64_','-DAMD64','-D_WIN64=1') + $inc + @('KmHello.c')) -WorkDir $tmp -Tag 'realwdk'
    if ($r3.Code -eq 0) {
        Write-Host "[通过]   真 WDK 头也能过 —— 说明存根没掩盖什么" -ForegroundColor Green
    } else {
        $n = ([regex]::Matches($r3.Text, ' error:')).Count
        Write-Host ("[预期失败] 真 WDK 头下 $n 处错误。msys gcc 缺 MSVC 的扩展" +
                    "（__declspec、SAL 的某些宏），这不代表源码有问题。") -ForegroundColor Yellow
        Write-Host "           要偏执地验只能在 WDK + MSVC 下编，见 docs\kernel-debug-in-vm.md" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "提醒：只挡『明显写错』。链接、ABI、KMDF 版本、INF、签名都没验过。" -ForegroundColor Yellow
