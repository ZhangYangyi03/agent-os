# 互联网软件 Agent 化的实测证据矩阵

生成时间 2026-10-19 16:26  主机 Windows 11 / Python 3.13

## 三条通道，一个契约

任何联网软件被 AI 接管的通道只有三条，优先级从上到下：

1. 官方 API / CLI —— 云端全量，最稳，有配额和审批
2. 本地数据平面 —— SQLite / LevelDB / 配置文件，离线、无配额、无审批，但只有本机同步过的副本
3. 客户端驱动 —— CDP / 命令行 / 窗口自动化，等于让人手替 AI 点，最后手段

把三条通路的返回都收敛成同一个工具契约（名字 + 参数 JSON + 返回 JSON），上层 AI 就不需要知道背后是 API 还是本地库还是点按钮。

## 实测矩阵（本机，非推测）

- 飞书 LarkShell｜通道：官方 OpenAPI + 本地库 + Chromium｜实测：cookie 链已破（DPAPI→AES-256-GCM，16 条 session/session_list/osession）；persistent_storage.db 明文；im.db 走 SQLCipher 已定位参数未取 key｜状态：部分打通
- 微信 Weixin 4.1.15｜通道：仅本地库（无官方 API）｜实测：28 个库全加密，零明文；密钥不落盘、登录态派生；MMKV 带 CRC 防篡改｜状态：需运行时抓密钥
- WPS kingsoft｜通道：本地库 + COM/命令行｜实测：27 个明文库；wps.db 3171 条命令定义可直接实例化为工具｜状态：可接管
- Cursor｜通道：Chromium CDP｜实测：9222 端口实测在线，/json/version 200，3 个 page target｜状态：已接管
- 腾讯 Tencent｜通道：本地库 + Chromium｜实测：11 个明文库 + Local State｜状态：部分打通
- 百度 baidu｜通道：本地库 + Chromium｜实测：9 个明文库（最大 15 表）｜状态：部分打通
- Zoom｜通道：本地库 + Chromium｜实测：5 个明文库｜状态：可读
- Ollama｜通道：本地 HTTP API｜实测：11434 端口（当前未启动，tags 接口契约已知）｜状态：按需
- Clash｜通道：本地 HTTP API｜实测：9090 控制口（当前未启动）｜状态：按需

## 规模数字（本机实测）

- 装有可自治通道证据的应用：47 个
- 存在明文可读 SQLite 的应用：28 个，库文件 122 个
- 全机 PE 二进制：53615 个 / 65.5 GB（反编译口径的基数）
