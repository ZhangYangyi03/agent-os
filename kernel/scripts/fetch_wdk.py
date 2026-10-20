#!/usr/bin/env python
"""fetch_wdk.py -- 微软安装器下不动时的备胎。

背景（2026-10-19 在这台机器上实测）：learn.microsoft.com 和 go.microsoft.com
的 TLS 握手在这里直接失败（curl 报 schannel 握手失败），而 api.nuget.org 通。
WDK 同时也发布在 NuGet 上，包里有内核头文件和库，所以这条路能走。

这不是"绕过微软"，是改用微软的另一个官方分发渠道。

用法（不需要管理员，只是下载解压）:
    python scripts\fetch_wdk.py            # 取最新的稳定版
    python scripts\fetch_wdk.py 10.0.26100.6584

它会解到 vendor\\wdk\\<版本>\\ 并打印目录结构。

重要限制，别指望它包办一切：
  - WDK 的 NuGet 包只有头文件、库和工具，没有编译器。
    你仍然需要 Visual Studio Build Tools（cl.exe / link.exe / MSBuild）。
  - 装完 Build Tools 后，把 vendor\\wdk\\<版本>\\ 里的 Include、Lib 指给工程
    才能编。src\\build.ps1 默认找 C:\\Program Files (x86)\\Windows Kits\\10；
    要用手工解出来的 WDK，就得设 WDKContentRoot 环境变量。
  - 有网能装官方 WDK 安装器时，优先用官方的。这个脚本是退路，不是首选。
"""
import io
import os
import sys
import json
import zipfile
import urllib.request

PKG = "microsoft.windows.wdk.x64"
FLAT = "https://api.nuget.org/v3-flatcontainer"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEST = os.path.join(ROOT, "vendor", "wdk")


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "kernel-lab-fetch"})
    return urllib.request.urlopen(req, timeout=timeout)


def versions():
    with get("%s/%s/index.json" % (FLAT, PKG)) as r:
        return json.load(r)["versions"]


def pick(arg):
    vs = versions()
    if arg:
        if arg not in vs:
            raise SystemExit("没有这个版本。可选: %s" % ", ".join(vs[-6:]))
        return arg
    stable = [v for v in vs if "-" not in v]
    return stable[-1] if stable else vs[-1]


def main():
    ver = pick(sys.argv[1] if len(sys.argv) > 1 else None)
    out = os.path.join(DEST, ver)
    print("版本:", ver)
    print("目标:", out)
    if os.path.isdir(out) and os.listdir(out):
        print("已经解压过了，跳过。删掉目录可以重下。")
        return 0

    url = "%s/%s/%s/%s.%s.nupkg" % (FLAT, PKG, ver, PKG, ver)
    print("下载:", url)
    with get(url, timeout=300) as r:
        data = r.read()
    print("大小: %.1f MB" % (len(data) / 1048576.0))

    os.makedirs(out, exist_ok=True)
    z = zipfile.ZipFile(io.BytesIO(data))
    z.extractall(out)
    n = len(z.namelist())
    print("解出 %d 个文件" % n)

    # 打印一眼能看懂的结构，别让人自己摸
    tops = sorted({p.split("/")[0] for p in z.namelist()})
    print("顶层:", ", ".join(tops))
    for want in ("Include", "Lib", "bin", "build"):
        p = os.path.join(out, want)
        if os.path.isdir(p):
            sub = sorted(os.listdir(p))[:6]
            print("  %-8s %s" % (want, ", ".join(sub)))

    print()
    print("下一步: 装 VS Build Tools（含 C++ 桌面开发），然后设")
    print("  setx WDKContentRoot \"%s\"" % out)
    print("再跑 src\\build.ps1。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
