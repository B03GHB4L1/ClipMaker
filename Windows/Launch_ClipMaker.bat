@echo off
title Clip Maker
cd /d "%~dp0"

echo.
echo  ================================================
echo    ClipMaker 1.1 by B4L1 - Starting up...
echo  ================================================
echo.

:: -----------------------------------------------
:: STEP 1 - Check Python
:: -----------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo  [!] Python is not installed on this computer.
    echo.
    echo  To fix this:
    echo.
    echo  1. Open your web browser and go to:
    echo         https://www.python.org/downloads
    echo.
    echo  2. Click the big yellow "Download Python" button.
    echo.
    echo  3. Run the installer. On the FIRST screen,
    echo     make sure to check the box that says:
    echo     "Add Python to PATH"  ^<-- this is important
    echo.
    echo  4. Once installed, double-click this launcher again.
    echo.
    echo  ================================================
    pause
    exit /b 1
)

echo  [OK] Python is installed.

:: -----------------------------------------------
:: STEP 2 - Install missing packages
:: Uses python -m pip to ensure correct environment
:: Shows output so errors are visible
:: -----------------------------------------------
echo  [..] Checking required packages...
echo.

python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing streamlit ^(this may take a minute^)...
    python -m pip install streamlit
    echo.
)

python -c "import moviepy" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing moviepy ^(this may take a minute^)...
    python -m pip install moviepy
    echo.
)

python -c "import pandas" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing pandas...
    python -m pip install pandas
    echo.
)

python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!] A component called tkinter is missing.
    echo      The Browse buttons may not work.
    echo      To fix this, reinstall Python from https://www.python.org/downloads
    echo      and use the default installation options.
    echo.
)

:: Verify streamlit actually installed correctly
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!] Streamlit could not be installed.
    echo.
    echo  Please take a screenshot of this window and
    echo  send it to whoever shared this app with you.
    echo.
    pause
    exit /b 1
)

echo  [OK] All packages ready.
echo.

:: -----------------------------------------------
:: STEP 3 - Suppress Streamlit email prompt
:: Write credentials file so the prompt never appears
:: -----------------------------------------------
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

:: -----------------------------------------------
:: STEP 4 - Launch
:: -----------------------------------------------
echo  [..] Opening ClipMaker 1.1 in your browser...
echo.
echo  Note: A browser tab will open automatically.
echo  Keep this window open while using the app.
echo  Close this window when you are done.
echo.
echo  ================================================
echo.

python -m streamlit run "%~dp0app_streamlit.py" --server.headless false --browser.gatherUsageStats false

pause
