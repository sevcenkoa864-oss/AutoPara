#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -d "dist/AutoPara.app" ]; then
    open dist/AutoPara.app
elif [ -f ".venv/bin/python" ]; then
    .venv/bin/python -m autopara "$@"
else
    python3 -m autopara "$@"
fi
