@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Сначала запусти run.bat, чтобы установить зависимости.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name ARGB-Krutoy main.py
if errorlevel 1 (
  echo Сборка завершилась с ошибкой.
  pause
  exit /b 1
)
echo Готово: dist\ARGB-Krutoy\ARGB-Krutoy.exe
pause
