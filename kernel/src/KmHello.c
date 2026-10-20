/* KmHello.c -- 最小的 KMDF 驱动。
 *
 * 它做的事只有一件：注册一个控制设备 \\.\KmHello，收到 IOCTL_KMHELLO_GET_INFO
 * 时，把此刻内核里的真实状态（PID、CPU 数、IRQL、系统时间）填进返回缓冲区。
 *
 * 一个非 PnP 的控制设备驱动，是"我能不能进内核"这个问题最短的一条验证路径：
 * 少到没有硬件、没有 PnP、没有电源管理要处理，出了错也只有一处。
 *
 * 编译：src\build.ps1（需要 VS Build Tools + WDK）。
 * 本机没有 MSVC，所以这个 .sys 还没有被真编译过。但本文件不是"没人看过"：
 * tools\stubcheck 用一份照 WDK 10.0.26100 抄的存根做了 -Wall -Wextra 的类型检查，
 * 通过。缺什么、试过哪些路、为什么都断了，见 docs\toolchain-dead-ends.md。
 */

#include <ntddk.h>
#include <wdf.h>
#include "kmhello.h"

/* 这个文件是内核态：用 ntddk.h 的 ULONG/ULONGLONG，不是 kmhello.h 里为
 * 用户态留的 unsigned int。两个宽度在这台机器上一致（都是 4 字节），
 * 断言一次，免得以后换平台时悄悄错位。 */
C_ASSERT(sizeof(ULONG) == 4);
C_ASSERT(sizeof(ULONGLONG) == 8);

#define KMHELLO_DRIVER_VERSION  0x00010000UL   /* 1.0.0.0 */

DRIVER_INITIALIZE DriverEntry;
EVT_WDF_DRIVER_UNLOAD            KmHelloEvtDriverUnload;
EVT_WDF_IO_QUEUE_IO_DEVICE_CONTROL KmHelloEvtIoDeviceControl;

static NTSTATUS
KmHelloCreateDevice(
    _In_ WDFDRIVER Driver
    );

/* ---- 卸载：把符号链接删掉，控制设备由框架回收 ---- */
VOID
KmHelloEvtDriverUnload(
    _In_ WDFDRIVER Driver
    )
{
    UNREFERENCED_PARAMETER(Driver);

    {
        UNICODE_STRING symLink;
        RtlInitUnicodeString(&symLink, KMHELLO_SYMLINK_NAME);
        (VOID)IoDeleteSymbolicLink(&symLink);
    }

    DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_INFO_LEVEL,
               "KmHello: unloaded\n");
}

/* ---- 唯一的入口：把内核现场填进返回缓冲区 ---- */
VOID
KmHelloEvtIoDeviceControl(
    _In_ WDFQUEUE   Queue,
    _In_ WDFREQUEST Request,
    _In_ size_t     OutputBufferLength,
    _In_ size_t     InputBufferLength,
    _In_ ULONG      IoControlCode
    )
{
    PKMHELLO_INFO info = NULL;
    size_t        outLen = 0;
    NTSTATUS      status;

    UNREFERENCED_PARAMETER(Queue);
    UNREFERENCED_PARAMETER(InputBufferLength);
    /* 这个 IOCTL 不返回变长数据，输出长度就在这里做个边界断言，
     * 顺便把参数用掉 —— 不然 -Wunused-parameter 会一直响。 */
    if (OutputBufferLength < sizeof(KMHELLO_INFO)) {
        WdfRequestComplete(Request, STATUS_BUFFER_TOO_SMALL);
        return;
    }

    if (IoControlCode != (ULONG)IOCTL_KMHELLO_GET_INFO) {
        WdfRequestComplete(Request, STATUS_INVALID_DEVICE_REQUEST);
        return;
    }

    status = WdfRequestRetrieveOutputBuffer(Request,
                                            sizeof(KMHELLO_INFO),
                                            (PVOID*)&info,
                                            &outLen);
    if (!NT_SUCCESS(status)) {
        WdfRequestComplete(Request, status);
        return;
    }

    /* 这些取值都发生在驱动的分派里，也就是"正在有人调它"的那一刻。
     * 静态看一个 .sys 是看不到这几个数字的 ---- 它们在这里才存在。 */
    RtlZeroMemory(info, sizeof(KMHELLO_INFO));
    info->StructSize      = (ULONG)sizeof(KMHELLO_INFO);
    info->DriverVersion   = KMHELLO_DRIVER_VERSION;
    info->CallerProcessId = (ULONG)(ULONG_PTR)PsGetCurrentProcessId();
    info->CpuCount        = KeQueryActiveProcessorCountEx(ALL_PROCESSOR_GROUPS);
    info->IrqlAtEntry      = (ULONG)KeGetCurrentIrql();
    info->SystemTimeUtc    = (ULONGLONG)KeQuerySystemTimePrecise();

    {
        RTL_OSVERSIONINFOW vi;
        RtlZeroMemory(&vi, sizeof(vi));
        vi.dwOSVersionInfoSize = sizeof(vi);
        if (NT_SUCCESS(RtlGetVersion(&vi))) {
            info->OsMajor = vi.dwMajorVersion;
            info->OsMinor = vi.dwMinorVersion;
            info->OsBuild = vi.dwBuildNumber;
        }
    }

    WdfRequestCompleteWithInformation(Request, STATUS_SUCCESS,
                                      (ULONG_PTR)sizeof(KMHELLO_INFO));
}

/* ---- 建控制设备 + 符号链接 + 队列 ---- */
static NTSTATUS
KmHelloCreateDevice(
    _In_ WDFDRIVER Driver
    )
{
    PWDFDEVICE_INIT deviceInit;
    WDFDEVICE       device;
    WDF_IO_QUEUE_CONFIG queueConfig;
    UNICODE_STRING  deviceName;
    UNICODE_STRING  symLinkName;
    NTSTATUS        status;

    deviceInit = WdfControlDeviceInitAllocate(Driver,
                            &SDDL_DEVOBJ_SYS_ALL_ADM_ALL);
    if (deviceInit == NULL) {
        return STATUS_INSUFFICIENT_RESOURCES;
    }

    WdfDeviceInitSetDeviceType(deviceInit, FILE_DEVICE_UNKNOWN);
    WdfDeviceInitSetIoType(deviceInit, WdfDeviceIoBuffered);

    RtlInitUnicodeString(&deviceName, KMHELLO_DEVICE_NAME);
    status = WdfDeviceInitAssignName(deviceInit, &deviceName);
    if (!NT_SUCCESS(status)) {
        WdfDeviceInitFree(deviceInit);
        return status;
    }

    status = WdfDeviceCreate(&deviceInit, WDF_NO_OBJECT_ATTRIBUTES, &device);
    if (!NT_SUCCESS(status)) {
        /* WdfDeviceCreate 失败时框架已经把 deviceInit 回收了 */
        return status;
    }

    RtlInitUnicodeString(&symLinkName, KMHELLO_SYMLINK_NAME);
    status = WdfDeviceCreateSymbolicLink(device, &symLinkName);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    WDF_IO_QUEUE_CONFIG_INIT_DEFAULT_QUEUE(&queueConfig,
                                           WdfIoQueueDispatchParallel);
    queueConfig.EvtIoDeviceControl = KmHelloEvtIoDeviceControl;

    status = WdfIoQueueCreate(device, &queueConfig,
                              WDF_NO_OBJECT_ATTRIBUTES, WDF_NO_HANDLE);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    WdfControlFinishInitializing(device);

    DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_INFO_LEVEL,
               "KmHello: loaded, waiting on %ws\n", KMHELLO_WIN32_NAME);

    return STATUS_SUCCESS;
}

NTSTATUS
DriverEntry(
    _In_ PDRIVER_OBJECT  DriverObject,
    _In_ PUNICODE_STRING RegistryPath
    )
{
    WDF_DRIVER_CONFIG config;
    WDFDRIVER         driver;
    NTSTATUS          status;

    WDF_DRIVER_CONFIG_INIT(&config, WDF_NO_EVENT_CALLBACK);
    config.DriverInitFlags |= WdfDriverInitNonPnpDriver;
    config.EvtDriverUnload  = KmHelloEvtDriverUnload;

    status = WdfDriverCreate(DriverObject, RegistryPath,
                             WDF_NO_OBJECT_ATTRIBUTES, &config, &driver);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    return KmHelloCreateDevice(driver);
}
