# agent-os

一个断言：AI 要接管的不只是一个 App 的界面，而是**从微码之上的每一层**。
这个仓库把那句话变成可测的层次表 —— 每一层标注谁真的能碰、碰的入口是什么、
以及在本机上的实测状态。**不做到的部分直接写成做不到。**

## 层次表（微码 L0 往上）

| 层 | 名字 | 谁说了算 | 本机能碰吗 | 入口 | 实测状态 |
|---|---|---|---|---|---|
| L0 | 微码 microcode | CPU 厂商私钥 | 不能，永远不能 | — | 已测：Update Revision 0x0a404105，Update Status=6；这层没有任何个人入口 |
| L1 | 固件 firmware / ACPI / SMBIOS | OEM + 微软签名链 | 只读 | GetSystemFirmwareTable | 已测：ACPI FACP 表 268 字节，OEM=LENOVO；写需厂商签名，无入口 |
| L2 | 内核 kernel | 微软签名链 | 可读、可加载自签驱动（测试模式） | kernel-lab 仓库 | 已交付：KMHello 驱动骨架 + 自签脚本，未在本机 install（需开测试签名并重启） |
| L3 | 驱动 / 服务 | 系统 ACL | 可枚举、可控制已授权项 | sc / driverquery | 已测：303 个服务、442 个驱动可枚举 |
| L4 | 进程 / 内存 | 同用户可读写 | 可读可写 | Win32 API | 已测：飞书 cookie 用 DPAPI 解出、微信密钥靠运行时读内存 |
| L5 | 本地数据 | 文件 ACL + 应用加密 | 明文可读；加密需取密钥 | SQLite / CDP / 配置文件 | 已测：28 个应用 122 个明文库；飞书 SQLCipher 参数已定位 |
| L6 | 应用界面 | 应用自己 | 可驱动 | CDP / 命令行 / UI 自动化 | 已测：Cursor CDP 9222 返回 200 |
| L7 | 网络 API | 服务方 | 可调 | 官方 OpenAPI / HTTP | 已测：Ollama 11434 契约已知；飞书 OpenAPI 待授权 |
| L8 | 云端数据 | 服务方 | 只能通过 L6/L7 | API | 不能越权；只拿被授权的数据 |

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

    kernel-lab    L2 的可操作证明：KMDF 驱动骨架 + 自签 + VM 调试，一个 IOCTL 只返回调用者 PID
    agent-anyapp  L5/L6/L7 的统一契约：三条通道 -> 同一个 {name,args,returns,channel}
    agent-os      把 L0..L8 说成一张可测的表，并明确 L0/L1 不可写

三者是同一条链：kernel-lab 说明"内核这层我进得去，但只走官方签名路"，
agent-anyapp 说明"数据这层三条通道我能收敛成一个契约"，
agent-os 说明"整条从微码到云端，谁说了算、我碰得到哪、碰不到的地方是什么原因"。

一句能被验证的话：Linux 的 /proc 与 /sys 是同一件事的下界；Windows 上等价物是
WMI、ETW、驱动程序、CDP。把这些入口接进同一个工具契约，就是 Agent OS 的定义。

## 与正在进行的进程的接口

- kernel-lab（L2）：已有，未在本机 install（需开测试签名 + 重启，属操作者决定）
- robot-spine / eda-spine / covagent（领域内核）：都是"把某层的状态机变成可被 AI 调用的安全动作"，与 anyapp 同构
- autoforge（本 agent）：L7/L8 的调用方，所有通道最终都落到工具契约
