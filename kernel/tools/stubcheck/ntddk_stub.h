/* ntddk_stub.h -- 只为语法检查，不参与真编译。
 *
 * 为什么有它：这台机器上没有 MSVC、没有 WDK，而把一个从未被编译器看过的
 * .c 交出去是不负责任的。这个存根把 KmHello.c 用到的那些内核 API 按 WDK
 * 10.0.26100 km 头里的真实签名抄了一遍，让 gcc -fsyntax-only 能真的跑通
 * 类型检查。真编译仍然必须在 WDK + MSVC 下。
 *
 * 检查过什么、没检查过什么，写在 tools\stubcheck\README.md 里。
 */
#pragma once
#include <stddef.h>
#include <string.h>
#include <stdint.h>

/* ---- 基本类型（宽度与 x64 WDK 一致） ---- */
typedef void                VOID;
typedef unsigned long       ULONG;
typedef long                LONG;
typedef unsigned long long  ULONGLONG;
typedef long long           LONGLONG;
typedef long                NTSTATUS;
typedef void               *PVOID;
typedef const void         *PCVOID;
typedef unsigned short      USHORT;
typedef unsigned char       UCHAR;
typedef uintptr_t           ULONG_PTR;
typedef int32_t             BOOLEAN;
typedef char               *PCHAR;
typedef const char         *PCSTR;

#define NT_SUCCESS(s)        (((NTSTATUS)(s)) >= 0)
#define STATUS_SUCCESS       ((NTSTATUS)0x00000000L)
#define STATUS_INSUFFICIENT_RESOURCES ((NTSTATUS)0xC000009AL)
#define STATUS_INVALID_DEVICE_REQUEST ((NTSTATUS)0xC0000010L)
#define STATUS_BUFFER_TOO_SMALL   ((NTSTATUS)0xC0000023L)

#define ALL_PROCESSOR_GROUPS 0xFFFF
#define DPFLTR_IHVDRIVER_ID  77
#define DPFLTR_INFO_LEVEL    3
#define DPFLTR_ERROR_LEVEL   0

#define C_ASSERT(e)          typedef char _c_assert_##__LINE__[(e) ? 1 : -1]
#define UNREFERENCED_PARAMETER(p) ((void)(p))
#define _In_
#define _Out_
#define _Inout_
#define _In_opt_
#define _Out_opt_
#define _Inout_opt_
#define _IRQL_requires_max_(x)
#define _Must_inspect_result_
#define WDF_NO_OBJECT_ATTRIBUTES ((void*)0)
#define WDF_NO_HANDLE            ((void*)0)
#define WDF_NO_EVENT_CALLBACK    ((void*)0)

typedef struct _UNICODE_STRING {
    USHORT Length;
    USHORT MaximumLength;
    wchar_t *Buffer;
} UNICODE_STRING, *PUNICODE_STRING;

typedef struct _RTL_OSVERSIONINFOW {
    ULONG  dwOSVersionInfoSize;
    ULONG  dwMajorVersion;
    ULONG  dwMinorVersion;
    ULONG  dwBuildNumber;
    ULONG  dwPlatformId;
    wchar_t szCSDVersion[128];
} RTL_OSVERSIONINFOW, *PRTL_OSVERSIONINFOW;

size_t wcslen_stub(const wchar_t *);
static inline void RtlInitUnicodeString(UNICODE_STRING *d, const wchar_t *s) {
    size_t n = 0; while (s[n]) n++;
    d->Buffer = (wchar_t *)s;
    d->Length = (USHORT)(n * sizeof(wchar_t));
    d->MaximumLength = d->Length;
}
static inline void RtlZeroMemory(void *p, size_t n) { memset(p, 0, n); }
NTSTATUS RtlGetVersion(PRTL_OSVERSIONINFOW);
NTSTATUS IoDeleteSymbolicLink(PUNICODE_STRING);
ULONG KeQueryActiveProcessorCountEx(USHORT);
ULONGLONG KeQuerySystemTimePrecise(void);
unsigned char KeGetCurrentIrql(void);
void *PsGetCurrentProcessId(void);
unsigned long DbgPrintEx(ULONG, ULONG, const char *, ...);

/* ---- 驱动/设备/队列/请求：只声明到被用到的那些 ---- */
typedef struct WDFDRIVER__  *WDFDRIVER;
typedef struct WDFDEVICE__  *WDFDEVICE;
typedef struct WDFQUEUE__   *WDFQUEUE;
typedef struct WDFREQUEST__ *WDFREQUEST;
typedef struct WDF_OBJECT_ATTRIBUTES__ *PWDF_OBJECT_ATTRIBUTES;
typedef struct WDFDEVICE_INIT__        *PWDFDEVICE_INIT;

/* 真 WDK 里 EVT_* 是**函数类型**的 typedef，不是函数指针 —— 所以
 * `EVT_WDF_DRIVER_UNLOAD Foo;` 声明的是一个函数，不是变量。存根必须照抄这一点，
 * 否则同一份 .c 在两种头下行为不同，语法检查就失去意义。 */
typedef VOID EVT_WDF_DRIVER_UNLOAD(WDFDRIVER);
typedef VOID EVT_WDF_IO_QUEUE_IO_DEVICE_CONTROL
    (WDFQUEUE, WDFREQUEST, size_t, size_t, ULONG);

typedef VOID (*PFN_WDF_DRIVER_UNLOAD)(WDFDRIVER);
typedef VOID (*PFN_WDF_IO_QUEUE_IO_DEVICE_CONTROL)
    (WDFQUEUE, WDFREQUEST, size_t, size_t, ULONG);

typedef struct _WDF_DRIVER_CONFIG {
    ULONG Size;
    ULONG DriverInitFlags;
    PFN_WDF_DRIVER_UNLOAD EvtDriverUnload;
} WDF_DRIVER_CONFIG, *PWDF_DRIVER_CONFIG;

#define WdfDriverInitNonPnpDriver 0x00000002

typedef enum _WDF_IO_QUEUE_DISPATCH_TYPE {
    WdfIoQueueDispatchInvalid = 0,
    WdfIoQueueDispatchSequential,
    WdfIoQueueDispatchParallel,
    WdfIoQueueDispatchManual
} WDF_IO_QUEUE_DISPATCH_TYPE;

typedef struct _WDF_IO_QUEUE_CONFIG {
    ULONG Size;
    WDF_IO_QUEUE_DISPATCH_TYPE DispatchType;
    PFN_WDF_IO_QUEUE_IO_DEVICE_CONTROL EvtIoDeviceControl;
} WDF_IO_QUEUE_CONFIG, *PWDF_IO_QUEUE_CONFIG;

typedef enum _WDF_DEVICE_IO_TYPE {
    WdfDeviceIoUndefined = 0,
    WdfDeviceIoBuffered,
    WdfDeviceIoDirect
} WDF_DEVICE_IO_TYPE;

typedef enum _WDF_DEVICE_TYPE_UNUSED { WdfDeviceTypeUnused = 0 } WDF_DEVICE_TYPE_UNUSED;
#define FILE_DEVICE_UNKNOWN 0x00000022

#define WDF_DRIVER_CONFIG_INIT(cfg, cb) \
    do { memset((cfg), 0, sizeof(*(cfg))); (cfg)->Size = sizeof(*(cfg)); \
         (cfg)->EvtDriverUnload = (cb); } while (0)
#define WDF_IO_QUEUE_CONFIG_INIT_DEFAULT_QUEUE(cfg, disp) \
    do { memset((cfg), 0, sizeof(*(cfg))); (cfg)->Size = sizeof(*(cfg)); \
         (cfg)->DispatchType = (disp); } while (0)

/* SDDL_DEVOBJ_SYS_ALL_ADM_ALL：只让 SYSTEM 和管理员打开这个设备 */
extern const void *SDDL_DEVOBJ_SYS_ALL_ADM_ALL;

NTSTATUS WdfDriverCreate(void *, PUNICODE_STRING, PWDF_OBJECT_ATTRIBUTES,
                         PWDF_DRIVER_CONFIG, WDFDRIVER *);
PWDFDEVICE_INIT WdfControlDeviceInitAllocate(WDFDRIVER, const void *);
void WdfDeviceInitSetDeviceType(PWDFDEVICE_INIT, ULONG);
void WdfDeviceInitSetIoType(PWDFDEVICE_INIT, WDF_DEVICE_IO_TYPE);
NTSTATUS WdfDeviceInitAssignName(PWDFDEVICE_INIT, PUNICODE_STRING);
NTSTATUS WdfDeviceCreate(PWDFDEVICE_INIT *, PWDF_OBJECT_ATTRIBUTES, WDFDEVICE *);
NTSTATUS WdfDeviceCreateSymbolicLink(WDFDEVICE, PUNICODE_STRING);
NTSTATUS WdfIoQueueCreate(WDFDEVICE, PWDF_IO_QUEUE_CONFIG, PWDF_OBJECT_ATTRIBUTES, WDFQUEUE *);
void WdfControlFinishInitializing(WDFDEVICE);
void WdfDeviceInitFree(PWDFDEVICE_INIT);
NTSTATUS WdfRequestRetrieveOutputBuffer(WDFREQUEST, size_t, PVOID *, size_t *);
void WdfRequestComplete(WDFREQUEST, NTSTATUS);
void WdfRequestCompleteWithInformation(WDFREQUEST, NTSTATUS, ULONG_PTR);

typedef struct _DRIVER_OBJECT DRIVER_OBJECT, *PDRIVER_OBJECT;
typedef NTSTATUS DRIVER_INITIALIZE(PDRIVER_OBJECT, PUNICODE_STRING);
#define CTL_CODE(t, f, m, a) (((t) << 16) | ((a) << 14) | ((f) << 2) | (m))
