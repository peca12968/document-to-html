@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Please install first: python -m venv .venv
    echo Then run: .venv\Scripts\python.exe -m pip install -e ".[word,layout]"
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m document_to_html --gui
