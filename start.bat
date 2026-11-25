@echo off
REM Start LeaseSynth AI with the production server and open it in the browser.
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found. Create it first:
    echo     python -m venv venv
    echo     venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"
"venv\Scripts\python.exe" serve.py
pause
