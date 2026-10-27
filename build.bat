@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [2/4] Generating icon (tiptip.ico)...
python make_icon.py
if errorlevel 1 goto :fail

echo [3/4] Building exe with PyInstaller...
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name tiptip --icon tiptip.ico main.py
if errorlevel 1 goto :fail

echo [4/4] Verifying exe (--smoke)...
"dist\tiptip.exe" --smoke

echo.
echo Done: dist\tiptip.exe
pause
exit /b 0

:fail
echo.
echo Build failed. Check the messages above.
pause
exit /b 1
