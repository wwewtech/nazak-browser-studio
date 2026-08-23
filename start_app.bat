@echo off
cd /d "%~dp0"

if exist "dist\NazakBrowserStudio\NazakBrowserStudio.exe" (
    start "" "dist\NazakBrowserStudio\NazakBrowserStudio.exe"
) else (
    start "" pythonw -m nazak.main --mode gui
)
