@echo off
chcp 65001 >nul
setlocal
set VENV=D:\venvs\voicelib\Scripts\python.exe
if exist "%VENV%" (
  "%VENV%" "%~dp0server.py"
) else (
  echo [!] 未找到 venv,使用系统 Python;采集功能会降级
  python "%~dp0server.py"
)
pause
