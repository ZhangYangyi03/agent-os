# 不降级机器的替代路线（2026-10-20，全部当场实测）

被否掉的那条路是：`bcdedit /set testsigning on` → 重启 → 装自签驱动 → 拿到内核读写。
它确实work，代价是整机对所有进程失去强制签名校验，且与 Secure Boot 冲突。为了一个 agent
把一台机器降级，这个交易不划算——除非操作者本人判断划算，那不是我该替他做的决定。

下面是五条不用降级的路。前三条现在就能用，第四五条是"自己拥有一整个内核"。

## route 1 厂商签名驱动（已经跑在 OS 下面，但不是我的）

已签、AUTO_START、RUNNING：`AMDRyzenMasterDriverV31` → `\??\C:\WINDOWS\system32\AMDRyzenMasterDriver.sys`
它 import 的内核函数说明它能干什么：`MmMapIoSpace` / `HalGetBusDataByOffset`（裸 PCI 配置空间）、
`IoCreateDeviceSecure` + 显式 DACL（所以设备有 ACL）、`ZwCreateKey`（写注册表）、
`KeQueryGroupAffinity`（绑核）。这就是 SMU / MSR 那一层的通行证。

实测它的设备对象存在但打不开：

    \\.\AMDRyzenMasterDriverV31             query / read / read_write   全部 win32 5
    \\.\GLOBALROOT\Device\AMDRyzenMasterDriverV31                       win32 5

所以这一条的真实状态是：**能力在机器上，钥匙在厂商手里**。它不是签名边界（我们不去降级就能过），
是权限边界（设备对象的 ACL）。要它得成为它的调用方，而不是去改签名设置。

## route 2 可观测面（只读，白给）

    WMI root\wmi 类              1542
    ETW provider                 1137
    PDH 计数器集                   214
    UIA 顶层元素                    11

不要驱动、不要提权、不要改任何设置。它能给的是所有计数器、内核 trace 事件、WMI 实例、
以及 UI 元素树；它给不了的是操作系统没发布的那些东西：裸 MSR、SMU、IOMMU 寄存器、物理内存。

## route 3 WSL2 root —— 这一条实测到 MSR 读写

`wsl -u root` 里内核是 6.18.33.2-microsoft-standard-WSL2，uid 0，44 个模块已载。

    /dev/cpu/0/msr          crw------- root root      读：TSC / APIC_BASE / MTRRCAP 都有值
                            写：把 APIC_BASE 原值写回，读回一致 → WRITE ok
    /dev/mem                crw-r----- root kmem
    tracing                 available_filter_functions 里有 86 个 kprobe 目标
    insmod / modprobe       /usr/sbin 下都在，gcc 也在
    kptr_restrict=1  perf_event_paranoid=2   都是 root 可绕过的默认值

代价：Windows 侧零。不重启、不改签名设置、Hyper-V 保持开启。
边界：这是 VM，root 是自己内核的 root，不是 Windows 的。没有 Windows MSR、没有 Windows 内核内存、
没有 Windows 设备栈。

## route 4 VirtualBox（已装，7.2.16r174877）

可丢弃的 guest：装任何签不了的模块、改内核、快照回滚。对宿主零代价。
比 WSL2 慢，适合"要折腾就要能回滚"的场合。

## route 5 UI 自动化（没有 API 的软件的正规合同）

UIAutomationClient 当场看到 11 个顶层元素、9 个有名字。Invoke / SetValue / Select / Expand / Scroll
是结构化动作，不是鼠标坐标。不需要提权。reaches：任何发布了可访问性树的程序；
给不了：自己绘制、没有 provider 的程序（部分游戏/自绘 UI），那就只剩像素。

## 一句话结论

**要"控制整台 Windows"，不降级的路线是提权（已实测 6 条里 5 条变绿），剩下的内核态那一道
要么等厂商给接口，要么把机器降级——这两条都不该由我单方面决定。
要"控制一整个内核"，不用碰 Windows 的设置：WSL2 root 现在就能读写 MSR，VirtualBox 能给可丢弃的。**
