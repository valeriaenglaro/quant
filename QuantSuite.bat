@echo off
rem =====================================================================
rem  QuantSuite one-click launcher for Windows (runs the server in WSL)
rem  Edit APPDIR if you keep the app somewhere else inside WSL.
rem =====================================================================
set APPDIR=~/QuantSuite/app
start "QuantSuite server" wsl.exe bash -lc "cd %APPDIR% && ./QuantSuite.sh"
timeout /t 4 >nul
start "" http://localhost:8002/
