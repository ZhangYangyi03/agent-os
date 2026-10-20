# agent-os

一个断言：AI 要接管的不只是一个 App 的界面，而是**从微码之上的每一层**。
这个仓库把那句话变成可测的层次表 —— 每一层标注谁真的能碰、碰的入口是什么、
以及在本机上的实测状态。**不做到的部分直接写成做不到。**

## 层次表（微码 L0 往上）

| 层 | 名字 | 谁说了算 | 本机能碰吗 | 入口 | 实测状态 |
|---|---|---|---|---|---|
| L0 | 微码 microcode | CPU 厂商私钥 | 不能，永远不能 | — | 已测：Update Revision 0x0a404105，Update Status=6；这层没有任何个人入口 |
| L1 | 固件 firmware / ACPI / SMBIOS | OEM + 微软签名链 | 只读 | GetSystemFirmwareTable | 已测：ACPI FACP 表 268 字节，OEM 字段读作 CB-01（2026-10-20 复测；10-19 版误记 LENOVO）；写需厂商签名，无入口 |
| L2 | 内核 kernel | 微软签名链 | 可读；自签驱动只在测试签名模式下能装载 | kernel/ 子目录 | 骨架已交付（KMHello + 签名/安装脚本 + stubcheck），本机未 install：缺 MSVC，微软安装器域名 TLS 断；见 kernel/docs/toolchain-dead-ends.md |
| L3 | 驱动 / 服务 | 系统 ACL | 可枚举、可查询；停止/启动要有权限 | kernel/control/l0ctl.py | 已测：770 个服务、442 个驱动可枚举；对 wuauserv 发 stop 被拒，exit 5；机上有 5 个 360 内核组件 + WdFilter |
| L4 | 进程 / 内存 | 同用户可读写 | 同用户内可读可写，PPL/受保护进程直接拒 | kernel/control/l0ctl.py | 已测：336 个进程里 132 个可读可写，202 个被内核拒绝（System / lsass / csrss …），本进程未提权、完整性 medium、只有 5 个特权 |
| L5 | 本地数据 | 文件 ACL + 应用加密 | 明文可读；加密需取密钥 | SQLite / CDP / 配置文件 | 已测：28 个应用 122 个明文库；飞书 SQLCipher 参数已定位 |
| L6 | 应用界面 | 应用自己 | 可驱动 | CDP / 命令行 / UI 自动化 | 已测：Cursor CDP 9222 返回 200（2026-10-19；10-20 复测时该客户端未运行，端口关） |
| L7 | 网络 API | 服务方 | 可调 | 官方 OpenAPI / HTTP | 已测：Ollama 11434 契约已知；飞书 OpenAPI 待授权 |
| L8 | 云端数据 | 服务方 | 只能通过 L6/L7 | API | 不能越权；只拿被授权的数据 |

## 一个仓库，不是三个

L2 的实现在 kernel/（原 kernel-lab），L5/L6/L7 的实现在 anyapp/（原 agent-anyapp），
两处都是 2026-10-20 逐字节搬进来的，出处写在各自的 SOURCE.txt，原仓库保留不动作为历史。

理由：agent-os 主张一张层表，另外两个仓库是这张表里的两段实现，分开就变成
"论点和它的证据各在一个仓库里"。现在两次命令就把这张表跑完：

    python layers.py                        # L0..L8 逐层探测，这台机器的真实状态
    cd anyapp    && python demo.py          # 三条通道收敛成同一个 {name,args,returns,channel}
    cd kernel/control && python l0ctl.py    # L3/L4 的控制面：枚举、查询、打开、被拒的 Win32 码

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
