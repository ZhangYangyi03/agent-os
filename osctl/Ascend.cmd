@echo off
REM ===========================================================================
REM Ascend.cmd -- the operator asked for this path explicitly (2026-10-20).
REM
REM One action: ask the OS to run elevate.py --run with an elevated token. The
REM consent is the UAC prompt. EnableLUA=1 on this machine, so no process becomes
REM High integrity without that prompt being answered. Nothing here bypasses,
REM disables or pre-answers it.
REM
REM What runs elevated is elevate.py --run: six actions, each reverted in a
REM finally block, a receipt written next to this file. Nothing is started,
REM loaded, signed, scheduled, or written to a startup entry.
REM
REM No "pause": this script must be safe to run non-interactively.
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM resolve the interpreter once and pass the absolute path into the elevated call,
REM so the elevated process does not depend on inheriting a PATH
set "PYEXE="
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYEXE set "PYEXE=%%i"
if not defined PYEXE for /f "delims=" %%i in ('where py 2^>nul') do if not defined PYEXE set "PYEXE=%%i -3"
if not defined PYEXE (
    echo no python on PATH: install one, or run: python elevate.py --run from an elevated shell
    exit /b 4
)

echo === plan \(no elevation needed to see it\) ===
"%PYEXE%" "%~dp0elevate.py" --plan
echo.
echo === asking the OS for an elevated token: the UAC prompt is the consent ===
powershell -NoProfile -Command "Start-Process -FilePath '%PYEXE%' -ArgumentList '\"%~dp0elevate.py\" --run' -Verb RunAs -Wait"
echo.
echo === receipt ===
if exist "%~dp0elevation-receipt.json" (
    "%PYEXE%" "%~dp0show_receipt.py"
    exit /b 0
)
echo no receipt: the prompt was declined, or the elevated run failed to start
exit /b 5
