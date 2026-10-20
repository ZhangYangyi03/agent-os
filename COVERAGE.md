# COVERAGE -- how much of this operating system an agent can actually drive

生成方式：`cd osctl && python osctl.py --md`。下表每一行都是当场跑出来的，
不是从 API 文档抄的。刷新时间 2026-10-20，本机 Windows 11 家庭中文版 / AMD Ryzen 7 6800H。

计数：14 个对象类，17 个动作被允许，6 个被拒绝（每个拒绝都带自己的码）。
"被允许"要求真的改动了对象再改回去，不是"这个 API 存在"。

| object class | what was attempted | objects | granted | refused | codes |
|---|---|---|---|---|---|
| process | enumerate + read/write handles per process | 337 | 2 | 1 | 5 |
| service | list + query + stop attempt | 770 | 2 | 1 | 5 |
| driver | enumerate + load privilege | 442 | 1 | 1 | - |
| filesystem | write in own space vs system dir | 1 | 1 | 1 | - |
| registry | HKCU vs HKLM | 2 | 1 | 1 | 5 |
| network | listeners + firewall | 1 | 2 | 0 | - |
| scheduled task | create+query+delete | 1 | 1 | 0 | - |
| session | enumerate logon sessions | 1 | 1 | 0 | - |
| window | enumerate titled windows | 1 | 1 | 0 | - |
| device | enumerate PnP devices | 1 | 1 | 0 | - |
| storage | enumerate volumes | 1 | 1 | 0 | - |
| event log | read System vs Security | 2 | 1 | 1 | 5 |
| power | reboot capability | 1 | 1 | 0 | - |
| package | enumerate Appx packages | 1 | 1 | 0 | - |


## 怎么读这张表

三列分开看，混在一起就没有信息量：

    objects  这一类里系统肯报出多少东西          ← 可观测性
    granted  多少动作真的做成了（都做了再撤销）    ← 控制面
    refused  多少被系统拒绝，code 是拒绝的理由     ← 边界，而且是量出来的边界

拒绝不是缺项。stop wuauserv 返回 5、HKLM 建键返回 5、读 Security 日志返回 5、
202 个进程的句柄返回 5 —— 这些恰恰是最有价值的一半：接口在，系统说不。

## 这 6 个拒绝，合起来是什么

    进程      202 个（PPL / 受保护 / 别的完整性级别）
    服务      停止任何非本人服务
    驱动      装载任何驱动（SeLoadDriverPrivilege 根本不在令牌里）
    文件系统  写 C:\Windows
    注册表    写 HKLM
    事件日志  读 Security

六条拒绝的根是同一个：这个进程是 medium 完整性、未提权、只有 5 个特权。
也就是说"控制整个操作系统"这个目标，在这台机器上当前的状态是：
**每一个可观测的对象类都摸得到，每一处要改系统的动作都被同一道墙挡住，
而那道墙有名字——令牌。**

## 那堵墙后面是什么，也量过了

    提权到 High          →  需要 UAC，只有操作者能点
    拿 SeLoadDriverPrivilege →  本身就是提权
    签一个驱动            →  要么微软的密钥（没有），要么测试签名（要重启，整机降级）
    微码                  →  CPU 熔断校验，提权和签名都动不了（见 kernel/control/l0reach.py，2/5 道闸）

所以从"当前这一层"到"控制整个操作系统"，路径是明确的，四步，不是感觉：
1. 提权（操作者点一次 UAC）→ 打开文件系统、注册表、服务、事件日志这四道拒绝；
2. 拿 SeLoadDriverPrivilege + 测试签名 + 驱动 → 打开内核态，进程那道 202 也会一起塌；
3. 内核驱动拿到任意读写 → 可以改任何对象，仍然改不了微码；
4. 微码那一层不在可及范围：CPU 只认厂商签名的 blob 且要过熔断校验。

第 3 步做成之后，"Agent 直接控制整个操作系统"在技术上成立，且只有第 4 步永远不成立。
这也解释了为什么这个仓库把这两件事分开写：操作系统可及，硅不可及。
