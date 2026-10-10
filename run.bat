@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  py -3.12 -m venv .venv 2>nul
  if errorlevel 1 py -3.11 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Не удалось установить зависимости. Проверь Python 3.11/3.12 x64 и интернет.
  pause
  exit /b 1
)
python main.py
if errorlevel 1 pause
