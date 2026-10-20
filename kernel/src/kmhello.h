/* kmhello.h -- 驱动和用户态共用的一份定义。
 * 两边必须看到同一个 IOCTL 号和同一个返回结构，否则出来的数字是错的字节。 */
#pragma once

/* 内核对象名。驱动用它创建，用户态通过 Win32 名打开。 */
#define KMHELLO_DEVICE_NAME   L"\\Device\\KmHello"
#define KMHELLO_SYMLINK_NAME  L"\\DosDevices\\KmHello"
#define KMHELLO_WIN32_NAME    L"\\\\.\\KmHello"
#define KMHELLO_SERVICE_NAME  L"KmHello"

#define KMHELLO_DEVICE_TYPE  0x9C00
#ifndef CTL_CODE
/* 用户态那边由 winioctl.h 提供，内核态由 ntddk.h 提供。都没有时手动算。 */
#define CTL_CODE(DeviceType, Function, Method, Access) \
    (((DeviceType) << 16) | ((Access) << 14) | ((Function) << 2) | (Method))
#endif

#define IOCTL_KMHELLO_GET_INFO \
    CTL_CODE(KMHELLO_DEVICE_TYPE, 0x800, 0 /*METHOD_BUFFERED*/, 1 /*FILE_READ_DATA*/)

/* 从内核里带回来的东西。全部是驱动在被调用的那一刻现场取的，
 * 不是驱动加载时缓存的 ---- 这样"动态观察"才有意义。 */
typedef struct _KMHELLO_INFO {
    unsigned int      StructSize;        /* sizeof(KMHELLO_INFO)，用来发现版本错配 */
    unsigned int      DriverVersion;     /* 驱动自己的版本号 */
    unsigned int      CallerProcessId;   /* 谁在调我 */
    unsigned int      OsMajor;
    unsigned int      OsMinor;
    unsigned int      OsBuild;
    unsigned int      CpuCount;          /* KeQueryActiveProcessorCountEx 现场取 */
    unsigned int      IrqlAtEntry;       /* 进来时的 IRQL */
    unsigned long long SystemTimeUtc;    /* KeQuerySystemTimePrecise，100ns 为单位 */
} KMHELLO_INFO, *PKMHELLO_INFO;
