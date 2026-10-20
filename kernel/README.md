# kernel-lab — 自己开发内核驱动的正规路径

这是一套可以在你自己机器上跑起来的 Windows 内核驱动实验。全部走微软给的官方路径，
不开后门、不用任何"绕过签名"的办法。

## 这台机器的实测前提（2026-10-19 测的）

    Windows 版本      Windows 11 家庭中文版（EditionID = CoreCountrySpecific）
    CPU               AMD Ryzen 7 6800H
    hypervisor        HypervisorPresent = True（VBS 在跑，不是 Hyper-V 角色）
    VBS               运行中（VirtualizationBasedSecurityStatus = 2）
    HVCI / 内存完整性  未开（SecurityServicesRunning = 0）
    启动链            要求微软签名（RequireMicrosoftSignedBootChain = 1）
    当前权限          Medium Mandatory Level（不是管理员）
    已有工具          无 MSVC / cl / link / msbuild / signtool / WDK / Windows Kits
    已装虚拟机         无（VBoxManage / vmrun 都不在 PATH）
    已有              Docker / WSL2（Ubuntu 在跑）

家庭版没有 Hyper-V 管理器，做实验用 VirtualBox 或 VMware Workstation Player 最省事。
WSL2 和 Docker 不能拿来当内核驱动的实验田 —— 那是 Linux 内核，不是 Windows。

## 目录

    src/KmHello.c           驱动本体（KMDF，一个 IOCTL，返回内核里的版本和调用者 PID）
    src/KmHello.inf         INF：怎么把这个 .sys 装进系统
    src/kmhello.h           驱动和用户态共用的 IOCTL 定义
    src/UserPing.c          用户态测试程序：打开设备、发 IOCTL、打印结果
    src/build.ps1           用 MSBuild 编（需要 VS Build Tools + WDK）
    src/UserPing-build.ps1  单独编用户态小程序（cl 就够）
    scripts/preflight.ps1   环境自检：跑完就知道缺什么、下一步做什么
    scripts/fetch_wdk.py    微软安装器下不动时的备胎：从 NuGet 取 WDK 头文件与库
    scripts/testsign.ps1    生成自签证书并给 .sys 签名
    scripts/install.ps1     sc create + start（要先开测试签名并重启）
    scripts/uninstall.ps1   停服务、删服务
    scripts/enable-testsigning.ps1   开测试签名模式（会提示关安全启动）

## 整条链是什么样（按顺序，一条不能跳）

1. 装 Visual Studio Build Tools（勾"使用 C++ 的桌面开发"）
   https://aka.ms/vs/17/release/vs_BuildTools.exe
2. 装 Windows Driver Kit（和你的 Windows SDK 版本对齐）
   https://learn.microsoft.com/windows-hardware/drivers/download-the-wdk
3. 跑 scripts/preflight.ps1 确认工具链齐了
4. 编：src/build.ps1  → 得到 KmHello.sys
5. 开测试签名：管理员跑 scripts/enable-testsigning.ps1，然后重启
   （如果安全启动开着，会先要求你进 BIOS 关掉它）
6. 签：管理员跑 scripts/testsign.ps1
7. 装：管理员跑 scripts/install.ps1
8. 验：跑 UserPing.exe，它打印驱动版本和你的 PID —— 这些数字是从内核里回来的
9. 拆：管理员跑 scripts/uninstall.ps1


## 现在就能跑的验证（不等 WDK）

这台机器上没有 MSVC、没有 MSBuild，所以 .sys 编不出来。但源码不是"没被任何编译器
看过"就交出去的 —— tools\stubcheck 里有一份按 WDK 10.0.26100 的 km 头抄下来的
存根，加上 gcc -fsyntax-only，能真的做类型检查：

    powershell -ExecutionPolicy Bypass -File tools\stubcheck\check-source.ps1

实测（2026-10-19）：

    [通过]   KmHello.c 在存根下无告警          (-Wall -Wextra)
    [通过]   UserPing.c 编并链接成功            (gcc 编的 mingw 版，能跑)
    [通过]   UserPing.exe 跑起来报 "打不开 \\\\.\\KmHello (Win32 error 2)"
             —— 这正是驱动没装时该看到的那句话，说明用户态这一半的逻辑是对的

它已经抓到过三个真错误：EVT_* 宏被我当成函数指针（真 WDK 里是函数类型的
typedef）、static 前向声明与宏冲突、printf 的 %ws 与参数类型不匹配。

它不验：链接、ABI、KMDF 版本、INF、签名、运行时。见 tools\stubcheck\README.md。

## WDK 已经在仓库里了（vendor\wdk）

vendor\wdk\10.0.26100.6584 是从 NuGet 取的 WDK 官方包解出来的：km 头文件、
ntoskrnl.lib、wdfldr.lib、KMDF 的 targets，400 MB 里这些都在。

    learn.microsoft.com 在这台机器上 TLS 握手失败（实测），go.microsoft.com 也不通，
    而 api.nuget.org 通。所以这条路是必须的，不是凑合。
    scripts\fetch_wdk.py 可以重下，也能取到更新的版本。

但它**不含编译器**：cl.exe / link.exe / MSBuild 都在 Visual Studio Build Tools 里，
那个包还下不下来（aka.ms 同样超时）。也就是说：

    头文件、库、SDK 工具 —— 有了
    编译器、链接器、MSBuild —— 没有

所以 src\build.ps1 现在跑不了，缺的不是 WDK 而是 MSVC。补上的方法见
docs\kernel-debug-in-vm.md（在虚拟机里装 Build Tools）。

## 关于风险，说清楚

- 开关测试签名 + 关安全启动，会让这台机器更容易被 rootkit 感染。这是真的代价。
- 所以：别在主力机上做。在虚拟机里做，砸坏了删掉重来。
- 恢复原样：scripts/enable-testsigning.ps1 -Undo，然后进 BIOS 重新打开安全启动。
