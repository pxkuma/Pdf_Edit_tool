@echo off
rem Run PDF Studio on Windows: double-click this file, or run it in a terminal.
rem Extra options go to the server, e.g.  run.bat --port 9000 --no-browser
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py %*
  goto :done
)
where python >nul 2>nul
if %errorlevel%==0 (
  python run.py %*
  goto :done
)
echo.
echo PDF Studio needs Python 3.11 or newer. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer), then run this file again.
pause
exit /b 1
:done
exit /b %errorlevel%
