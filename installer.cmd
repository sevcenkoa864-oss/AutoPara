@echo off
rem Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
rem AutoPara installer bootstrap -- the no-exe path.
rem
rem installer.exe carries its own Python; this file is the fallback for anyone who cloned the
rem repository and already has Python. It runs exactly the same installer:
rem installer\install_app.py, whose own window is in Ukrainian.
rem
rem ASCII only on purpose: a .cmd file is read in the console code page, and non-ASCII text here
rem would show up as mojibake on a default Windows console.

setlocal
cd /d "%~dp0"

py -3 --version >nul 2>&1 && (
    py -3 "installer\install_app.py"
    goto :eof
)

python --version >nul 2>&1 && (
    python "installer\install_app.py"
    goto :eof
)

echo.
echo Python was not found. Trying to install it with winget...
echo.
winget --version >nul 2>&1 || (
    echo winget is not available. Install Python from https://www.python.org/downloads/
    echo and run installer.cmd again.
    pause
    exit /b 1
)

winget install --exact --id Python.Python.3.13 --source winget --scope user ^
    --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Could not install Python. Please install it manually from python.org.
    pause
    exit /b 1
)

py -3 "installer\install_app.py" || python "installer\install_app.py"
