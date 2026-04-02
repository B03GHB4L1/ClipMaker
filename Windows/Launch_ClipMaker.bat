@echo off
title ClipMaker v1.2 by B4L1
cd /d "%~dp0"

echo.
echo  ================================================
echo    ClipMaker v1.2 by B4L1 - Starting up...
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
    python -m pip install streamlit --user
    echo.
)

python -c "import moviepy" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing moviepy ^(this may take a minute^)...
    python -m pip install moviepy --user
    echo.
)

python -c "import pandas" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing pandas...
    python -m pip install pandas --user
    echo.
)

python -c "import plotly" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing plotly ^(needed for Shot Map Parlour^)...
    python -m pip install plotly --user
    echo.
)

python -c "import curl_cffi" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing curl_cffi ^(needed for WhoScored scraper^)...
    python -m pip install curl_cffi --user
    echo.
)

python -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing playwright ^(needed for supplementary data^)...
    python -m pip install playwright --user
    echo.
)

:: Install Playwright Chromium browser (one-time, ~150MB)
:: Check if already installed by looking for the chromium executable
python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.executable_path; p.stop(); exit(0 if __import__('os').path.exists(b) else 1)" >nul 2>&1
if errorlevel 1 (
    echo  [..] Downloading Chromium browser for supplementary data ^(one-time, ~150MB^)...
    python -m playwright install chromium
    echo.
)

python -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo  [..] Installing numpy...
    python -m pip install numpy --user
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

:: -----------------------------------------------
:: STEP 2b - Download Plotly.js for Analyst Room maps (one-time)
:: -----------------------------------------------
set "PLOTLY_JS=%~dp0smp_component\frontend\plotly-2.27.0.min.js"
if not exist "%PLOTLY_JS%" (
    echo  [..] Downloading Plotly.js for Analyst Room maps ^(one-time^)...
    curl -sL -o "%PLOTLY_JS%" "https://cdn.plot.ly/plotly-2.27.0.min.js"
    if exist "%PLOTLY_JS%" (
        echo  [OK] Plotly.js downloaded.
    ) else (
        echo  [!] Could not download Plotly.js - maps may not render.
        echo      You can download it manually from:
        echo      https://cdn.plot.ly/plotly-2.27.0.min.js
        echo      and save it to: smp_component\frontend\plotly-2.27.0.min.js
    )
    echo.
)

echo  [OK] All packages ready.
echo.

:: -----------------------------------------------
:: STEP 2c - Patch Streamlit index.html (one-time)
:: Keeps sidebar typography stable before page CSS loads
:: -----------------------------------------------
set "INDEX_MARKER="
for /f "delims=" %%i in ('python -c "import streamlit,os; print(os.path.join(os.path.dirname(streamlit.__file__),'static','index.html'))" 2^>nul') do set "STREAMLIT_INDEX=%%i"
if defined STREAMLIT_INDEX (
    if exist "%STREAMLIT_INDEX%" (
        python -c "open('%STREAMLIT_INDEX%','r',encoding='utf-8').read().index('CLIPMAKER_THEME_START')" >nul 2>&1
        if errorlevel 1 (
            echo  [..] Applying ClipMaker theme patch to Streamlit ^(one-time^)...
            python "%~dp0patch_streamlit.py" >nul 2>&1
            echo  [OK] Theme patch applied.
            echo.
        )
    )
)


if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

:: -----------------------------------------------
:: STEP 4 - Create desktop shortcut with icon (once only)
:: Runs silently — user never sees this happen
:: -----------------------------------------------
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\ClipMaker v1.2.lnk"
if not exist "%SHORTCUT%" (
    powershell -NoProfile -NonInteractive -Command ^
        "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT%');" ^
        "$s.TargetPath='%~dp0Launch_ClipMaker.bat';" ^
        "$s.WorkingDirectory='%~dp0';" ^
        "$s.IconLocation='%~dp0ClipMaker.ico';" ^
        "$s.Description='ClipMaker v1.2 by B4L1';" ^
        "$s.Save()" >nul 2>&1
    echo  [OK] Shortcut added to your Desktop.
)

:: -----------------------------------------------
:: STEP 5 - Launch
:: -----------------------------------------------
echo  [..] Opening ClipMaker v1.2 in your browser...
echo.
echo  Note: A browser tab will open automatically.
echo  Keep this window open while using the app.
echo  Close this window when you are done.
echo.
echo  ================================================
echo.

set "CHOSEN_PORT="
for /f "delims=" %%i in ('powershell -NoProfile -NonInteractive -Command "$ports=8501..8510; foreach($p in $ports){ $busy=Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue; if(-not $busy){ Write-Output $p; break } }"') do set "CHOSEN_PORT=%%i"

if not defined CHOSEN_PORT (
    echo  [!] Could not find a free local port between 8501 and 8510.
    echo      Please close other local web apps and try again.
    pause
    exit /b 1
)

if "%CHOSEN_PORT%"=="8501" (
    echo  [..] Launching ClipMaker on http://localhost:%CHOSEN_PORT% ...
) else (
    echo  [!] Port 8501 is busy.
    echo  [..] Launching ClipMaker on http://localhost:%CHOSEN_PORT% instead ...
)

python -m streamlit run "%~dp0ClipMaker.py" --server.port %CHOSEN_PORT% --server.headless false --browser.gatherUsageStats false

pause
