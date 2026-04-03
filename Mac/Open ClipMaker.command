#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
chmod +x ./Launch_ClipMaker.command
./Launch_ClipMaker.command
