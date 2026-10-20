# agent-os

一个断言：AI 要接管的不只是一个 App 的界面，而是**从微码之上的每一层**。
这个仓库把那句话变成可测的层次表 —— 每一层标注谁真的能碰、碰的入口是什么、
以及在本机上的实测状态。**不做到的部分直接写成做不到。**

## 层次表（微码 L0 往上）

| 层 | 名字 | 谁说了算 | 本机能碰吗 | 入口 | 实测状态 |
|---|---|---|---|---|---|
| L0 | 微码 microcode | CPU 厂商私钥 | 不能写；距离量成 5 道闸，本机过 2 道 | kernel/control/l0reach.py | 已测：Revision 0x0541400a、Update Status=6、加载器 mcupdate_AuthenticAMD.dll 签名 Valid 且不可写（G1/G2 过）；G3 缺编译器、G4 缺签名密钥、G5 是 CPU 自己的熔断校验 |
| L1 | 固件 firmware / ACPI / SMBIOS | OEM + 微软签名链 | 只读 | GetSystemFirmwareTable | 已测：ACPI FACP 表 268 字节，OEM 字段读作 CB-01（2026-10-20 复测；10-19 版误记 LENOVO）；写需厂商签名，无入口 |
| L2 | 内核 kernel | 微软签名链 | 可读；自签驱动只在测试签名模式下能装载 | kernel/ 子目录 | 骨架已交付（KMHello + 签名/安装脚本 + stubcheck），本机未 install：缺 MSVC，微软安装器域名 TLS 断；见 kernel/docs/toolchain-dead-ends.md |
| L3 | 驱动 / 服务 | 系统 ACL | 可枚举、可查询；停止/启动要有权限 | kernel/control/l0ctl.py | 已测：770 个服务、442 个驱动可枚举；对 wuauserv 发 stop 被拒，exit 5；机上有 5 个 360 内核组件 + WdFilter |
| L4 | 进程 / 内存 | 同用户可读写 | 同用户内可读可写，PPL/受保护进程直接拒 | kernel/control/l0ctl.py | 已测：336 个进程里 132 个可读可写，202 个被内核拒绝（System / lsass / csrss …），本进程未提权、完整性 medium、只有 5 个特权 |
| L5 | 本地数据 | 文件 ACL + 应用加密 | 明文可读；加密需取密钥 | anyapp/census.py | 已测：44 个应用扫完，31 个有可打开的明文库共 129 个；5 个一条通道都走不通；飞书 SQLCipher 参数已定位 |
| L6 | 应用界面 | 应用自己 | 可驱动 | CDP / 命令行 / UI 自动化 | 已测：23 个应用有 Chromium Local State，8 个可判 client-drive；当场 33 个 loopback 监听里 0 个开着 CDP |
| L7 | 网络 API | 服务方 | 可调 | 官方 OpenAPI / HTTP | 已测：当场只有 1/33 个监听真回了契约（18001 /health）；另有 2 个 200 但 body 是 HTML/XML，被单列成"答了但不是契约" |
| L8 | 云端数据 | 服务方 | 只能通过 L6/L7 | API | 不能越权；只拿被授权的数据 |

## 一个仓库，不是三个

L2 的实现在 kernel/（原 kernel-lab），L5/L6/L7 的实现在 anyapp/（原 agent-anyapp），
两处都是 2026-10-20 逐字节搬进来的，出处写在各自的 SOURCE.txt，原仓库保留不动作为历史。

理由：agent-os 主张一张层表，另外两个仓库是这张表里的两段实现，分开就变成
"论点和它的证据各在一个仓库里"。现在两次命令就把这张表跑完：

    python layers.py                        # L0..L8 逐层探测，这台机器的真实状态
    cd anyapp    && python census.py         # 全机应用普查：每条通道各收得住几个应用
    cd anyapp    && python demo.py           # 三条通道收敛成同一个 {name,args,returns,channel}
    cd kernel/control && python l0ctl.py     # L3/L4 的控制面：枚举、查询、打开、被拒的 Win32 码

## 迁移到别的机器：git clone 就能跑，但只有 Windows 那半边是真跑

    git clone https://github.com/ZhangYangyi03/agent-os && cd agent-os
    python osctl/hostenv.py      # 先说清这台机器上哪些文件能跑、哪些不能，以及为什么

实测：在这台机器上把仓库 clone 到临时目录，四层探针全部当场跑通——layers.py、osctl.py --md、
census.py --quick、l0ctl.py，clone 3.7 秒，没有一处写死的本机路径（全仓库搜 "C:\Users\china"
零命中，路径都从 __file__ 和环境变量推）。

可移植的四个文件和不可移植的五个文件是分开的，hostenv.py 报的就是这个：

    anyapp/contract.py probe.py census.py test_census.py   纯 python，任何系统都能跑
    layers.py osctl/*.py kernel/control/*.py               ctypes 进 kernel32/advapi32、
                                                           sc.exe、schtasks.exe、mcupdate DLL

拿到 Linux 机器（比如那台 KOS 机）能直接跑的是 anyapp 那四个：契约、分类、普查、测试。
其余五个会当场报"这台机器没有 sc.exe / 没有这个 DLL"，而不是假装跑出数字。
这个边界不是设计缺陷，是"控制操作系统"这件事本身就跟操作系统绑定。

## 提权：做成 allow-list + 每个动作自带 revert，不是"保证"两个字

osctl/elevate.py + osctl/Elevate.cmd（双击就是你点 UAC 的地方）。安全不是承诺，是四条结构：

    1  allow-list   动作是文件里写死的 6 个，没有开关、没有环境变量能加。CI 断言杜绝 bcdedit/testsigning/driver/schtasks
    2  revert or die 每个动作声明 revert，在 finally 里跑；revert 失败 → 回执标 REVERTED:false、退出码 2，绝不报成功
    3  read-back    改完要读回来确认变了，撤销后要读回来确认恢复了，否则不算 granted
    4  不持久化      不启动任何服务、不加载驱动、不改签名设置、不写启动项；创建的那个服务是 stopped 且同一次运行里删掉

    六条允许的动作：写 C:\Windows 一个文件 / 建一个 HKLM\SOFTWARE 键 / 建一个从不启动的占位服务 /
                     读一条 Security 日志 / 查令牌是否真在 Administrators 里 / 验证受保护进程提权后仍被拒

最后一条是故意放进去的：提权不会打开 lsass，回执里会明写 refused。提权能打开的是文件系统、
HKLM、服务、事件日志那四道；进程那 202 条要的是内核态，不是提权。

现在没提权时，elevate.py --run 直接拒绝并把 integrity 报出来（medium），退出码 3。

**实测（2026-10-20，两次真实运行）**：`osctl/Ascend.cmd` 调一次 `Start-Process -Verb RunAs`，
机器 EnableLUA=1 / ConsentPromptBehaviorAdmin=5 / PromptOnSecureDesktop=1，所以那一下必然弹框——
本次是操作者要的，所以由操作者答。回执 integrity=high，6 条动作 5 条 GRANTED、1 条 refused：

    fs.write.system_dir           granted  C:\Windows 写入成功并删掉
    registry.write.hklm           granted  HKLM\SOFTWARE 建键成功并删掉
    service.create.never_started  granted  占位服务创建、查询、删除（从未启动）
    eventlog.read.security        granted  读到一条 Security 事件
    token.administrators_group    granted  IsInRole(Administrator)=True
    process.ppl_still_refused     refused  lsass pid 2020，PROCESS_VM_READ=False win32 5

最后一条就是提权买不到的东西：High 完整性令牌读 lsass 仍然被内核拒（PPL）。提权把
磁盘/注册表/服务/事件日志四道打开，进程那 202 条要的是内核态。

所以这句话要改得准确：**它能自己发起提权请求，但"变成管理员"这一步永远是 UAC 回答的**。
脚本不绕过、不关闭、不预答 UAC；它做的是把 Start-Process -Verb RunAs 这一句写下来，
省掉去右键的那一下。回执带链式 sha256（prev_sha256 指向上一次的 sha256），
连跑两次实测 5a5e3c55 → 9e49c816 → 8032d94c。

## 不降级的替代路线（详见 NO-DOWNGRADE.md，五条都实测过）

    route 1  厂商签名驱动      能力在机器上、钥匙在厂商手里：设备 \\.\AMDRyzenMasterDriverV31 打不开，win32 5
    route 2  可观测面          1542 个 WMI 类 / 1137 个 ETW provider / 214 个 PDH 计数器集，零成本
    route 3  WSL2 root         实测 MSR 可读可写（写回 APIC_BASE 原值并读回一致），86 个 kprobe 目标，insmod+gcc 都在
    route 4  VirtualBox 7.2.16 可丢弃的 guest 内核，对宿主零代价
    route 5  UI 自动化         UIA 11 个顶层元素；没有 API 的程序的正规合同

所以"不降级"不是一句态度：要控制整台 Windows，是提权（已实测）+ 等厂商接口；
要控制一整个内核，WSL2 root 现在就能读写 MSR，且 Windows 侧一个设置都没动。

## 目标：Agent 直接控制整个操作系统 —— 现在是 6/14 类做得到，拒绝的地方有名字

osctl/osctl.py 是控制面本身：14 个对象类，每类不只是枚举，还真的去改一次再改回来，
结果记 allowed 或 refused 加码。COVERAGE.md 是它生成的表。

    14 个对象类 / 17 个动作做成 / 6 个被拒绝
    被拒绝的六条，根是同一个：medium 完整性、未提权、5 个特权

    process   337 个进程可见，132 个可读内存，202 个被内核拒（PPL/受保护）  代码 5
    service   770 个可枚举可查询，停 wuauserv 被拒                        代码 5
    driver    442 个可枚举，SeLoadDriverPrivilege 不在令牌里               无 privileges
    filesystem 自己目录写得进并读回并删掉，C:\Windows 写不进               拒绝
    registry  HKCU 建/写/读/删成功，HKLM 被拒                             代码 5
    eventlog  System 读得到，Security 读不到                              代码 5

十七个做成里包括：调度任务 create+query+delete、窗口枚举、会话枚举、PnP 设备 442、
卷、防火墙状态、Appx 包、监听端口 —— 也就是说**这台机器上每一个可观测的对象类都摸得到**。

从当前这一层到"控制整个操作系统"是四步，路径是量出来的，不是猜的：

    1  提权（操作者点一次 UAC）          打开文件系统/注册表/服务/事件日志四道拒绝
    2  测试签名 + SeLoadDriverPrivilege   打开内核态；进程那 202 条会一起塌
    3  内核驱动任意读写                  改得动任何对象，仍然改不动微码
    4  微码                              不在可及范围，CPU 只认厂商签名并过熔断（见下一节 2/5）

所以这个仓库对"整个操作系统"和"整台机器"是分开写的：前者可及，最后一步到内核驱动即止；
后者（硅）永远差一道熔断校验。

## 离"在微码层控制这台机器"还有多远 —— 量过，不是感觉

kernel/control/l0reach.py 把这段距离拆成五道有名字的闸，逐道在本机判定：

    G1 这台 CPU 有厂商微码、且系统已经加载了它        过  Revision 0x0541400a / Update Status 6
    G2 那个加载器不可被用户进程改写                    过  mcupdate_AuthenticAMD.dll 签名 Valid（Microsoft Windows），写被拒
    G3 要应用自己的 blob 就得有驱动，驱动要先有编译器   不过  本机无 cl.exe/link.exe/MSBuild，微软下载域名 TLS 断
    G4 有驱动还得有签名：要么微软的密钥，要么测试签名   不过  测试签名要重启，且整机失去强制签名保护
    G5 即使签好了，CPU 只认本机 family/model/stepping 的
       blob 并通过熔断校验                              不过  这一道本地特权动不了，是硅上的

结论就一句：2/5。前两道说明"厂商那条路在这台机器上是通的"，后三道说明"通的是厂商，
不是我"。剩下的三道具名：编译器、密钥、CPU 熔断。没有一件是靠提权能挪动的。

本机离 L0 最近的东西反倒不是我能写的驱动，而是一个已经签好、正在跑、由厂商提供的
内核驱动：AMDRyzenMasterDriverV31（\??\C:\WINDOWS\system32\AMDRyzenMasterDriver.sys，
AUTO_START，RUNNING）。它能碰 SMU/PCI 那一层。真正的距离不是"能不能进到那层"，
而是"它不给我这个合同"——没有文档的 IOCTL，没有可用的接口。这跟微码那道闸是同一句话：
差的是许可，不是能力。

## "控制"在这里是量的，不是说的

低层控制不需要自写驱动。kernel/control/l0ctl.py 在本机（未提权、无 WDK、无测试签名）实测：

    进程      336 个可见，132 个可读且可写，202 个被内核拒绝
    服务      770 个可枚举可查询，对 wuauserv 发 stop 返回 exit 5
    驱动      442 个可枚举；其中 360AntiHijack/360Box64/360Camera/360FsFlt/360reskit64/WdFilter 是别人家的内核组件
    特权      本进程只拿 5 个（SeChangeNotify 是唯一启用的），完整性级别 medium
    受保护对象 SAM/SYSTEM/SECURITY 连 stat 都被拒；hosts 可读不可写；System32\Tasks 可列不出但能建文件

这就是"不起驱动时控制到哪"的答案：能看见、能查询、能碰自己那一份，
越界的地方每一处都有明确回执。自写驱动不是为了让控制存在，是为了把这条线往下挪一层——
而挪这一层要先有编译器，本机现在没有，原因写在 kernel/docs/toolchain-dead-ends.md。

## 三条通道 -> 一个契约

L5/L6/L7 是同一种东西的三个来源，统一成 `{name, args, returns, channel}`，
上层 AI 不需要知道背后是 SQLite 还是 HTTP 还是点浏览器。见 agent-anyapp。

## 这个仓库主张什么、不主张什么

主张：微码以上每一层都有**合法入口**，把它们接进同一个契约，就是 Agent OS。

不主张：不碰 L0/L1 的写入，不做 rootkit，不改别人的机器。理由写在
kernel-lab/docs/what-is-not-here.md：同样的内核能力，观察自己的系统是学习，
藏进别人的机器是恶意软件，区别只在有没有得到机器主人的同意。

## 实测命令

```bash
python layers.py          # 逐层探测，打印这一台机器的真实状态
```

## 与另外两个仓库的关系（为什么不是三个孤立项目）

    kernel/   L2/L3/L4：KMDF 驱动骨架 + 自签脚本 + 不起驱动就能用的控制面 l0ctl.py
    anyapp/   L5/L6/L7：三条通道 -> 同一个 {name,args,returns,channel}

两者是同一条链：kernel/ 回答"内核这层我进得去，但只走官方签名路，且不起驱动时控制线在哪"，
anyapp/ 回答"数据这层三条通道我能收敛成一个契约"。

一句能被验证的话：Linux 的 /proc 与 /sys 是同一件事的下界；Windows 上等价物是
WMI、ETW、驱动程序、CDP。把这些入口接进同一个工具契约，就是 Agent OS 的定义。

## 与正在进行的进程的接口

- kernel/control/l0ctl.py（L3/L4）：现在就能跑，不需要驱动，不需要提权
- robot-spine / eda-spine / covagent（领域内核）：都是"把某层的状态机变成可被 AI 调用的安全动作"，与 anyapp 同构
- autoforge（本 agent）：L7/L8 的调用方，所有通道最终都落到工具契约
