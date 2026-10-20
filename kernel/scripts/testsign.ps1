# testsign.ps1 -- 生成自签证书并给 KmHello.sys 签名。
# 这是"自己给自己发工牌"。测试签名模式开着时，Windows 认这张工牌。
#
# 用法（管理员）:
#   powershell -ExecutionPolicy Bypass -File scripts\testsign.ps1
param(
    [string]$Sys = "",
    [string]$CertSubject = "CN=kernel-lab-test",
    [switch]$RemoveCert
)
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

if ($RemoveCert) {
    Get-ChildItem Cert:\LocalMachine\Root, Cert:\LocalMachine\TrustedPublisher -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $CertSubject } | ForEach-Object {
            Write-Host ("删除证书: " + $_.Thumbprint)
            Remove-Item ("Cert:\LocalMachine\" + $_.PSParentPath.Split('\\')[-1] + "\" + $_.Thumbprint) -Force -ErrorAction SilentlyContinue
        }
    Write-Host "已清理测试证书。" -ForegroundColor Green
    return
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "要管理员（要往 LocalMachine 证书库里写东西）。" }

if (-not $Sys) { $Sys = Join-Path $root 'out\KmHello.sys' }
if (-not (Test-Path $Sys)) { throw "找不到 $Sys。先跑 src\build.ps1 编出 .sys。" }

$signtool = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } | Select-Object -First 1
if (-not $signtool) { throw "找不到 signtool.exe。它随 Windows SDK 一起装。" }
Write-Host ("signtool: " + $signtool.FullName)

# ---- 1. 自签证书 ----
$cert = Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue | Where-Object { $_.Subject -eq $CertSubject } | Select-Object -First 1
if (-not $cert) {
    Write-Host "生成自签证书 $CertSubject ..."
    $cert = New-SelfSignedCertificate `
        -Type Custom `
        -Subject $CertSubject `
        -KeyUsage DigitalSignature `
        -FriendlyName "kernel-lab test signing" `
        -CertStoreLocation "Cert:\LocalMachine\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
} else {
    Write-Host ("复用已有证书 " + $cert.Thumbprint)
}

# ---- 2. 把证书放进受信任根 + 受信任发布者，否则内核不认 ----
foreach ($store in @('Root','TrustedPublisher')) {
    $path = "Cert:\LocalMachine\$store"
    if (-not (Test-Path (Join-Path $path $cert.Thumbprint))) {
        $tmp = Join-Path $env:TEMP ("kl-" + $cert.Thumbprint + ".cer")
        Export-Certificate -Cert $cert -FilePath $tmp -Type CERT | Out-Null
        Import-Certificate -FilePath $tmp -CertStoreLocation $path | Out-Null
        Remove-Item $tmp -Force
        Write-Host ("已导入 $store")
    } else {
        Write-Host ("$store 里已有")
    }
}

# ---- 3. 签名 ----
Write-Host "给 $Sys 签名 ..."
& $signtool.FullName sign /v /fd SHA256 /a /s My /n $CertSubject /t http://timestamp.digicert.com $Sys
if ($LASTEXITCODE -ne 0) { throw "signtool 失败（退出码 $LASTEXITCODE）。" }
& $signtool.FullName verify /v /pa $Sys
if ($LASTEXITCODE -ne 0) { Write-Host "verify 没过。测试签名模式下这未必挡装机，但要知道。" -ForegroundColor Yellow }

Write-Host ""
Write-Host "签完了。下一步: 管理员跑 scripts\install.ps1" -ForegroundColor Green
