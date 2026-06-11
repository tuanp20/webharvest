@echo off
echo ========================================
echo  WebHarvest Desktop - Windows Build
echo ========================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+ first.
    pause
    exit /b 1
)

echo [1/3] Installing dependencies...
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet

echo [2/3] Building desktop app...
python build_desktop.py

echo [3/3] Done!
echo.
echo Output: dist\WebHarvest\WebHarvest.exe
echo.
pause
