/* UserPing.c -- 用户态那一半。
 *
 * 它只做三件事：打开 \\.\KmHello，发 IOCTL_KMHELLO_GET_INFO，把内核带回来的
 * 数字打印出来。编译不需要 WDK，cl 就够。
 *
 * 跑起来的输出就是"动态分析"的实物证据：这些数字（IRQL、CPU 数、内核返回的
 * 系统时间）在静态读一个 .sys 文件时并不存在，只有驱动真的在核心里跑着、
 * 并且有人调它，它们才会出现。
 */

#include <windows.h>
#include <winioctl.h>
#include <stdio.h>
#include "kmhello.h"

int
main(void)
{
    HANDLE        h;
    KMHELLO_INFO  info;
    DWORD         returned = 0;
    BOOL          ok;

    h = CreateFileW(KMHELLO_WIN32_NAME,
                    GENERIC_READ | GENERIC_WRITE,
                    0, NULL, OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        printf("打不开 %ls  (Win32 error %lu)\n", KMHELLO_WIN32_NAME, (unsigned long)GetLastError());
        printf("先确认驱动已装且已启动:  sc query KmHello\n");
        return 1;
    }

    ZeroMemory(&info, sizeof(info));
    ok = DeviceIoControl(h, IOCTL_KMHELLO_GET_INFO,
                         NULL, 0,
                         &info, sizeof(info),
                         &returned, NULL);
    if (!ok) {
        printf("DeviceIoControl 失败 (Win32 error %lu)\n", GetLastError());
        CloseHandle(h);
        return 1;
    }

    printf("驱动回的字节数 : %lu (结构 %u)\n", (unsigned long)returned, info.StructSize);
    printf("驱动版本       : %u.%u.%u.%u\n",
           (info.DriverVersion >> 24) & 0xff,
           (info.DriverVersion >> 16) & 0xff,
           (info.DriverVersion >>  8) & 0xff,
           (info.DriverVersion      ) & 0xff);
    printf("调用者 PID     : %u   (本进程是 %lu)\n",
           info.CallerProcessId, (unsigned long)GetCurrentProcessId());
    printf("内核版本       : %u.%u build %u\n", info.OsMajor, info.OsMinor, info.OsBuild);
    printf("活动处理器数   : %u\n", info.CpuCount);
    printf("进入时 IRQL    : %u\n", info.IrqlAtEntry);
    printf("内核系统时间   : %llu (100ns since 1601)\n", info.SystemTimeUtc);

    /* PID 对上了，才算这条链真的通了：驱动的返回值确实来自"我正在调它"这一次，
     * 而不是某个写死的常量。 */
    if (info.CallerProcessId == GetCurrentProcessId()) {
        printf("\n[通] PID 对上了：这些数字是从内核里取回来的。\n");
    } else {
        printf("\n[怪] PID 不对，返回的不是本次调用的现场。\n");
    }

    CloseHandle(h);
    return 0;
}
