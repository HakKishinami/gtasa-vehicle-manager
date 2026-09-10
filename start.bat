@echo off
title GTASA Vehicle Mod Manager
cd /d "%~dp0"

if exist "%~dp0dist\GTASA_Vehicle_Manager\GTASA_Vehicle_Manager.exe" (
    start "" "%~dp0dist\GTASA_Vehicle_Manager\GTASA_Vehicle_Manager.exe"
    exit /b 0
)
if exist "%~dp0GTASA_Vehicle_Manager.exe" (
    start "" "%~dp0GTASA_Vehicle_Manager.exe"
    exit /b 0
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0server.py"
    exit /b 0
)

where python >nul 2>&1
if %errorlevel%==0 (
    start "" python "%~dp0server.py"
    exit /b 0
)

echo [Error] Could not find GTASA_Vehicle_Manager.exe or Python on your system PATH.
echo Please install Python 3.9+ from https://www.python.org/
pause