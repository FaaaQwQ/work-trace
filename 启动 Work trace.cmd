@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python environment missing. Install project dependencies first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0worktrace.py"
