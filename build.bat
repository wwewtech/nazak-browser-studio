@echo off
setlocal enabledelayedexpansion
title Nazak Browser Studio PRO - Production Build Pipeline

echo ====================================================================
echo        NAZAK BROWSER STUDIO PRO - SENIOR PRODUCTION BUILD
echo ====================================================================
echo.

cd /d "%~dp0"

python build_exe.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed with error code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [SUCCESS] Production build completed!
pause
