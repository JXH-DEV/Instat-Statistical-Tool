@echo off
setlocal EnableExtensions
title INSTAT Explorer - check
cd /d "%~dp0"
if not exist "%~dp0python\python.exe" (
  echo Unzip the whole download first, then open this file from the new folder.
  pause
  exit /b 1
)
set "INSTAT_DATA_DIR=%~dp0data"
"%~dp0python\python.exe" -m instatkit doctor --online
echo.
pause
