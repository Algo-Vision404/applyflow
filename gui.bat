@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo Opening the Applyflow window...
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "Applyflow" "%~dp0.venv\Scripts\pythonw.exe" -m applyflow gui
) else if exist "%~dp0.venv\Scripts\python.exe" (
  start "Applyflow" "%~dp0.venv\Scripts\python.exe" -m applyflow gui
) else (
  start "Applyflow" pythonw -m applyflow gui
)
