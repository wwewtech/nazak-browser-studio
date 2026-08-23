@echo off
title Nazak Browser Studio - Test Suite Runner
cd /d "%~dp0"
echo Running Nazak Browser Studio automated test suite...
python -m pytest -p no:asyncio tests -v
pause
