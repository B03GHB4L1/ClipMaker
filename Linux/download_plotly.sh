#!/bin/bash
echo "Downloading Plotly.js to smp_component/frontend/ ..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
curl -o "$SCRIPT_DIR/smp_component/frontend/plotly-2.27.0.min.js" "https://cdn.plot.ly/plotly-2.27.0.min.js"
if [ $? -eq 0 ]; then
    echo "Done! Plotly downloaded successfully."
else
    echo "Failed. Please download manually from:"
    echo "  https://cdn.plot.ly/plotly-2.27.0.min.js"
    echo "and save it to smp_component/frontend/plotly-2.27.0.min.js"
fi
