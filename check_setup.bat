@echo off
cd /d "%~dp0"
set "PY=python"
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
"%PY%" check_setup.py
pause
