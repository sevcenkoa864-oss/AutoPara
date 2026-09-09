#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -f ".venv/bin/python" ]; then
    .venv/bin/python build_mac.py "$@"
else
    python3 build_mac.py "$@"
fi
