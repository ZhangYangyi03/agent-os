"""Elevate.cmd -- the one place the operator clicks, and nothing happens without a click.

It does exactly one thing: start elevate.py --run with an elevated token, after showing
the plan. No arguments are forwarded from the command line, no environment variable is
read except a self-set marker, so this file cannot be turned into a launcher for
something outside the allow-list in elevate.py.

    double-click             show the plan and the UAC prompt
"""
@echo off
setlocal
cd /d "%~dp0"

if not "%AF_ELEVATE_CHILD%"=="1" (
    echo === plan: actions that will be reverted in the same run ===
    python "%~dp0elevate.py" --plan
    echo.
    echo === the prompt you are about to see asks for administrator rights ===
    echo === nothing on this list survives the run: no service is started, no driver is
    echo === loaded, no signature setting changed, no startup entry written ===
    echo.
    set AF_ELEVATE_CHILD=1
    powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList '\"%~dp0elevate.py\" --run' -Verb RunAs -Wait"
    echo.
    echo === receipt written to %~dp0elevation-receipt.json ===
    type "%~dp0elevation-receipt.json" 2>nul
    pause
    exit /b 0
)
