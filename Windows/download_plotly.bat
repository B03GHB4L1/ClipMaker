@echo off
echo Downloading Plotly.js to smp_component\frontend\ ...
curl -o "%~dp0smp_component\frontend\plotly-2.27.0.min.js" "https://cdn.plot.ly/plotly-2.27.0.min.js"
if %ERRORLEVEL% EQU 0 (
    echo Done! Plotly downloaded successfully.
) else (
    echo Failed. Please download manually from:
    echo   https://cdn.plot.ly/plotly-2.27.0.min.js
    echo and save it to smp_component\frontend\plotly-2.27.0.min.js
)
pause
