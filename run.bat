@echo off
rem Run PDF Studio on Windows: double-click this file, or run it in a terminal.
rem Extra options go to the server, e.g.  run.bat --port 9000 --no-browser
setlocal
cd /d "%~dp0"
set "NODE_MIN_MAJOR=20"

call :ensure_node

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

rem ---------------------------------------------------------------------------
rem Make sure Node.js (LTS, v%NODE_MIN_MAJOR%+) is available; it builds the web UI.
rem If it is missing or too old, install Node.js LTS with winget.
rem ---------------------------------------------------------------------------
:ensure_node
call :node_ok
if %errorlevel%==0 exit /b 0

where winget >nul 2>nul
if not %errorlevel%==0 (
  echo.
  echo Node.js %NODE_MIN_MAJOR% or newer was not found, and winget is not available to install it.
  echo Install the LTS version from https://nodejs.org if the web UI needs to be built.
  exit /b 0
)

echo Node.js %NODE_MIN_MAJOR% or newer was not found. Installing Node.js LTS with winget...
winget install --id OpenJS.NodeJS.LTS --exact --silent --accept-source-agreements --accept-package-agreements
rem winget updates PATH for new terminals only; add the default install folder for this one.
if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%ProgramFiles%\nodejs;%PATH%"

call :node_ok
if %errorlevel%==0 (
  echo Node.js installed.
  exit /b 0
)
echo.
echo Node.js could not be installed automatically. Install the LTS version from
echo https://nodejs.org if the web UI needs to be built, then run this file again.
exit /b 0

rem Sets errorlevel 0 when node is on PATH and its major version is at least NODE_MIN_MAJOR.
:node_ok
where node >nul 2>nul
if not %errorlevel%==0 exit /b 1
set "NODE_MAJOR="
for /f "delims=" %%v in ('node -p "process.versions.node.split('.')[0]" 2^>nul') do set "NODE_MAJOR=%%v"
if not defined NODE_MAJOR exit /b 1
if %NODE_MAJOR% LSS %NODE_MIN_MAJOR% exit /b 1
exit /b 0
