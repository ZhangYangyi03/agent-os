# 编译链在这台机器上试过的路，和它们为什么都断了

记下来，免得下一个会话（或者我自己）把时间再花一遍。

## 背景

要编一个 .sys，最小需求是：C 编译器 + 链接器 + WDK 头/库。
这台机器（2026-10-19 实测）一开始四样都没有。

## 试过的路

### 1. 微软官方安装器 —— 网络层就断了

    https://aka.ms/vs/17/release/vs_BuildTools.exe     curl 超时
    https://learn.microsoft.com/...                     TLS 握手失败
    https://go.microsoft.com/fwlink/?linkid=...         TLS 握手失败
    https://download.microsoft.com                      不通

curl 报 `schannel: failed to receive handshake`。不是证书问题，是连接被掐。
api.nuget.org 通、pypi.org 通、github.com 通 —— 所以不是断网，是这几个域名到不了。

结论：微软的安装器这条路，在这台机器上走不通。这是需要改网络环境才能解决的事，
不是脚本能绕的。

### 2. NuGet 上的 WDK 包 —— 成功，但不完整

    microsoft.windows.wdk.x64 10.0.26100.6584 (105.7 MB)

下来了，解开在 vendor\wdk\10.0.26100.6584，里面有：

    Include\10.0.26100.0\km\ntddk.h / wdm.h   内核头
    Include\wdf\kmdf\1.15 ... 1.35             KMDF 头
    Lib\10.0.26100.0\km\x64\ntoskrnl.lib      等等
    Lib\wdf\kmdf\x64\1.15\wdfldr.lib          KMDF 库
    build\10.0.26100.0\*.props / *.targets    MSBuild 的驱动规则
    bin\10.0.26100.0\x64\stampinf.exe         改 INF 时间戳的
    bin\10.0.26100.0\x86\Inf2Cat.exe          生成 .cat 的

没有：cl.exe / link.exe / MSBuild.exe / signtool.exe。

关键的一点：这个包**不含 sal.h**（在 Windows SDK 的 shared\ 里），而 wdm.h
第一件事就是 `#include <winapifamily.h>` 和用 `_Analysis_mode_()` 这些 SAL 宏。
所以它必须叠在一份 Windows SDK 的 Include 上面才能编。单独用它，缺头。

### 3. 用 msys2 的 gcc 直接吃真 WDK 头 —— 失败，且是有信息量的失败

    gcc -fsyntax-only -I vendor\wdk\...\km KmHello.c

产出 1.5 MB、上千条错误：`__declspec`、SAL 宏、`CPER_FIELD_CHECK` 里的
`FIELD_OFFSET` 展开方式，全是 MSVC 专有扩展。gcc 不是配置问题，是本来就不吃这套。

结论：真头 + gcc 这条路不存在。

### 4. 用 zig 自带的 clang（pip install ziglang，94 MB，能装）

zig 0.16.0 自带 clang 21.1.0，支持 `-fms-extensions -fms-compatibility`。
这台机器 pip 通，所以拿到了。

    zig cc -target x86_64-windows-msvc ... -> "unable to parse target query: UnknownOperatingSystem"
        这个 zig 版本没编入 msvc 目标。
    zig cc -target x86_64-windows-gnu  ... -> "failed to find libc installation: WindowsSdkNotFound"
        gnu 目标反而要求一份 Windows SDK，而 SDK 下不下来。
    加 -nostdlibinc 绕过去 -> 回到第 3 条那堆 SAL/__declspec 错误，只是换了措辞。

结论：zig 这条路也断在同一个地方 —— 没有 Windows SDK。要通，需要
Microsoft.Windows.SDK.CPP.x64 这个 NuGet 包（含 shared\sal.h 等），本机没取到。

## 所以现在到底缺什么

一句话：**缺一份 Windows SDK 的头文件，和一个能吃它们的 MSVC 或 clang-cl。**

    WDK 的头和库       有（vendor\wdk，从 NuGet 取的）
    编译器             没有
    Windows SDK 头     没有（sal.h 在这儿）
    网络能不能拿到      我这儿拿不到（curl 实测）

## 下一步该干什么

不要在真机上继续凿这条链。按 docs\kernel-debug-in-vm.md 走：
在虚拟机里装 VS Build Tools（那一刻网络是你那边的，不是我这个沙箱的），
WDK 一起装上，然后 src\build.ps1 就能跑。

如果非要在本机编，需要的是：能访问 aka.ms / download.microsoft.com 的网络，
或者手工把 Microsoft.Windows.SDK.CPP.x64 从 NuGet 取下来解到 vendor\sdk。
两条我都试不动了，写在这里交接。
