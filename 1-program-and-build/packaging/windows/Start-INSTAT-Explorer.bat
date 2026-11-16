@echo off
setlocal EnableExtensions
title INSTAT Explorer
cd /d "%~dp0"

set "PY=%~dp0python\python.exe"
if not exist "%PY%" goto :unzip

rem Downloaded files and exports stay in the "data" folder next to this file, so the whole folder can be copied to a USB stick.
set "INSTAT_DATA_DIR=%~dp0data"
"%PY%" -m instatkit serve
if errorlevel 1 pause
exit /b 0

:unzip
echo.
echo  The program files were not found next to this file.
echo  Unzip the WHOLE download first (right-click the zip file, Extract All), then open this file from the new folder.
echo  Do not start it from inside the zip file.
echo.
echo  Skedaret e programit nuk u gjeten. Hapni (Extract All) te gjithe paketen zip dhe nisni skedarin nga dosja e re.
echo.
pause
exit /b 1
