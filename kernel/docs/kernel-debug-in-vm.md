# 在虚拟机里做内核驱动实验，并把 WinDbg 接上去

一步一步，按顺序做。每一步能验证的时候，都说怎么验证。

## 为什么要在虚拟机里

开测试签名、关安全启动，你的真机就少了两层防护。这是真实的代价，不是吓唬。
虚拟机里做，弄坏了删掉重来，十分钟的事。

## 0. 这台机器的现状（2026-10-19 实测）

    Windows 11 家庭中文版       没有 Hyper-V 管理器
    已装: Docker、WSL2(Ubuntu)   这两个是 Linux 内核，不能拿来试 Windows 驱动
    虚拟化: hypervisor 在跑      VBS 在用，不代表有 Hyper-V 角色
    虚拟化软件: 没装             要新装一个

## 1. 装一个虚拟机软件

家庭版用这两个之一：

    VirtualBox        https://www.virtualbox.org/wiki/Downloads   （免费，最省事）
    VMware Workstation Player  https://www.vmware.com/products/workstation-player.html （个人免费）

VirtualBox 装的时候会问要不要装网络驱动，选是，装完重启。

验证：命令行里 `VBoxManage --version` 能打印版本号。

## 2. 虚拟机里装一个 Windows

    下载 Windows 11 官方 ISO:
    https://www.microsoft.com/software-download/windows11

    VirtualBox 里新建虚拟机：类型 Microsoft Windows / 版本 Windows 11
    内存给 4096 MB 以上，磁盘 60 GB 以上
    设置 -> 系统 -> 启用 EFI（Windows 11 要）
    设置 -> 系统 -> 处理器：勾上嵌套分页（Nested Paging）

装完进系统，第一件事：装 Guest Additions（VirtualBox 菜单 设备 -> 安装增强功能），
这样剪贴板和文件夹共享才好用，后面拷文件不用来回折腾。

## 3. 虚拟机里准备工具链

在虚拟机里装（不是宿主机）：

    https://aka.ms/vs/17/release/vs_BuildTools.exe
    勾选 "使用 C++ 的桌面开发"，其余默认

    https://learn.microsoft.com/windows-hardware/drivers/download-the-wdk
    跟着向导装，版本要和 Windows SDK 对齐

然后把这个 kernel-lab 目录整个拷进虚拟机（VirtualBox 共享文件夹最方便），
在里面跑：

    powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1

它会把缺什么列出来。全绿了再往下。

## 4. 虚拟机里开测试签名

管理员 PowerShell：

    powershell -ExecutionPolicy Bypass -File scripts\enable-testsigning.ps1 -WithDebug

这个脚本做三件事：`bcdedit /set testsigning on`、`bcdedit /debug on`、
`bcdedit /dbgsettings net hostip:0.0.0.0 port:50000`。

它会打印一个 key，形如 `1.2.3.4`。记下来，WinDbg 要用。

虚拟机里 Secure Boot 如果是开的，先在虚拟机设置里关掉（设置 -> 系统 -> 取消
"启用安全启动"）。

重启。看到桌面右下角有"测试模式"水印 = 成了。

验证：

    bcdedit /enum {current} | findstr /i "testsigning debug"

## 5. 编译、签名、装

    powershell -ExecutionPolicy Bypass -File src\build.ps1
    powershell -ExecutionPolicy Bypass -File scripts\testsign.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    out\UserPing.exe

UserPing 打印出来的 PID 应该等于它自己的 PID，最后一行会是 `[通] PID 对上了`。
那一行就是"我确实进内核了"的实物证据。

## 6. 把 WinDbg 接上去（这是真正的动态观察）

宿主机上装 WinDbg：

    winget install Microsoft.WinDbg
    或 https://learn.microsoft.com/windows-hardware/drivers/debugger/

虚拟机网络设成"桥接网卡"或"仅主机(Host-Only)"，记下虚拟机的 IP。

宿主机上启动 WinDbg，File -> Attach to kernel -> Net 标签：

    Port:      50000
    Key:       第 4 步打印的那个

点 OK，等它显示 `Waiting to reconnect...` 然后变成 `Connected to target`。

在 WinDbg 命令行里试：

    .sympath srv*C:\symbols*https://msdl.microsoft.com/download/symbols
    .reload
    g                       # 让虚拟机继续跑
    !drvobj KmHello 2       # 看这个驱动对象的内部结构
    lm m KmHello            # 看它的加载地址和符号
    bp KmHello!KmHelloEvtIoDeviceControl
    g
    # 然后在虚拟机里跑 out\UserPing.exe，断点会在这里命中断下来
    k                       # 看调用栈 —— 这一条就是从 WinDbg 看到的"内核里发生了什么"

断在断点上以后，`dv` 看局部变量，`!process 0 0` 看当前进程表，
这些都是静态反汇编给不了你的东西。

## 7. 收工，恢复环境

虚拟机里：

    powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1
    powershell -ExecutionPolicy Bypass -File scripts\enable-testsigning.ps1 -Undo

真机（如果之前在真机上动过）：同样两条，然后进 BIOS 把 Secure Boot 打开，重启。

## 常见卡点

    装驱动时报 577 / 0xC0000428（签名无效）
        -> 测试签名没生效，或者 Secure Boot 还开着，或者 HVCI 还开着

    sc start 报 1053 / 超时
        -> 驱动加载了但 DriverEntry 返回失败。看 Event Viewer -> System，
           来源是 KmHello 的那条。DbgPrint 的输出默认不到用户态，
           要在 WinDbg 里看，或者用 DebugView 开内核捕获。

    DbgPrint 看不到
        -> 静态编译的驱动里 DbgPrintEx 的级别不够。把 DPFLTR_INFO_LEVEL 换成
           DPFLTR_ERROR_LEVEL 试，或者干脆用 WinDbg 的断点看，更准。

    WinDbg 连不上
        -> 虚拟机和宿主机不在一个网段；或者 bcdedit 的 hostip 写错了；
           或者虚拟机防火墙挡了 50000。
