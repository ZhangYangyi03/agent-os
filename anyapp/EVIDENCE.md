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

## 复测：2026-10-20，全部由 census.py 生成，不是回忆

    python census.py --quick      # 44 个 AppData 应用，5.4 秒

    apps_scanned                 44
    local-db                     31   （有明文 SQLite 且能打开，共 129 个库文件）
    client-drive                  8   （有 Chromium Local State，即有能力，不等于被允许）
    unsupported                   5
    chromium_apps                23

L6/L7 这一次是当场量的，不是引用 README：当时 33 个 loopback 监听，只有 1 个真的
回了契约（18001 /health，com.docker.backend.exe，JSON 带 ok/resources/events/chain_ok）。
另外两个"答了但不是契约"的，值得单独记：

    21962  /v1/models  -> 200，但 body 是 HTML（ollama app.exe 的 GUI 页面）
    37989  /api/tags   -> 200，但 body 是 XML 且 status_code=404（XrRuntime.exe）

只看状态码的探测会把这两个算成"通道可用"。这不是假设出来的错误，是这台机器上
真实发生的一次误判，所以 census.py 现在把"200 但不是契约"单独归一类。

## 与 10-19 版的差异，逐条

    plaintext_sqlite_apps     28 -> 31
    plaintext_sqlite_files   122 -> 129
    新增：census.py          全机扫一遍，输出上面这些数字
    修正：client-drive 不再把"有 Local State"说成"可驱动"
