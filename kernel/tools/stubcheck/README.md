# stubcheck -- 在没有编译器的机器上，先把源码验一遍

## 它是什么

三个存根头（ntddk.h / ntddk_stub.h / wdf.h）加一个检查脚本。存根里的每个函数
签名都是照 WDK 10.0.26100 的 km 头抄的。目的不是替代 WDK，是让 gcc 的
`-fsyntax-only` 能对 KmHello.c 真的跑一遍类型检查。

## 为什么需要它

这台机器上没有 MSVC、没有 cl.exe、没有 link.exe。把一份从未被任何编译器看过的
驱动源码交出去，是拿操作者的时间去调试我的错字。存根让最常见的错误（类型宽度、
函数签名不符、宏拼错、结构体字段名错）在几秒钟内暴露。

实际抓到过的：

    - KmHello.c 里 static 前向声明和 EVT_ 宏（EVT_* 是**函数类型**的 typedef，
      不是函数指针）冲突 —— 这条是真的 C 错误，不是存根造出来的
    - UserPing.c 里 printf 的 %ws（MSVC 认，gcc 不认）与参数类型不匹配
    - ULONG 宽度断言、结构体布局

## 它不检查什么 —— 这段比上面重要

    x  链接：没有 link.exe，没验证过 ntoskrnl.lib / wdfldr.lib 的导入是否齐全
    x  ABI：没用 MSVC 的调用约定和结构体对齐规则核对过
    x  KMDF 版本：没跑 KmdfVerifier，不知道 1.15 的最低兼容要求是否满足
    x  INF：只做了语法和编码检查（UTF-16LE），没跑 inf2cat / stampinf
    x  签名：没签过，也不知道签名后 sys 会不会被 Windows 拒
    x  运行时：一次都没跑过，因为这台机器装不上

所以：存根通过 ≠ 能编过，更 ≠ 能装。它只是把"明显写错"这一类挡在门外。
真编译必须在 WDK + MSVC 下做，也就是 docs\kernel-debug-in-vm.md 里那套。

## 参数化检查

    powershell -ExecutionPolicy Bypass -File tools\stubcheck\check-source.ps1

输出三种结果之一：
    [通过]            gcc -fsyntax-only 在存根下无告警
    [真实 WDK 头]     本机有 vendor\wdk 时，额外用真 WDK 头试一次；失败是正常的，
                      msys 的 gcc 没有 MSVC 的 __declspec 等扩展
    [缺 gcc]          没有 gcc 就跳过，不当成失败
