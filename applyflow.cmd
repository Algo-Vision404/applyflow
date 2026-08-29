@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
  set "PYW=%~dp0.venv\Scripts\pythonw.exe"
) else (
  set "PY=python"
  set "PYW=pythonw"
)

if "%~1"=="" goto open_gui
if /I "%~1"=="gui" goto open_gui

"%PY%" -m applyflow %*
goto :eof

:open_gui
echo Opening the Applyflow window...
if exist "%PYW%" (
  start "Applyflow" "%PYW%" -m applyflow gui
) else (
  start "Applyflow" "%PY%" -m applyflow gui
)
