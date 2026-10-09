@echo off
rem NovaNote 启动脚本（Windows）
setlocal
cd /d "%~dp0"
set PY=D:\DevTools\Python\Python312\Python.exe
if not exist "%PY%" set PY=python
"%PY%" main.py %*
endlocal
