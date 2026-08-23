@echo off
title Nazak Browser Studio - Web Dashboard
cd /d "%~dp0"
echo Starting Nazak Browser Studio Web Dashboard at http://127.0.0.1:8899 ...
python -m nazak.main --mode web
pause
