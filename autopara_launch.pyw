"""Windowless entry script used by the autostart registry entry.

A .pyw run through pythonw.exe starts with no console window. Using an absolute path to this file
means the Run key works regardless of the working directory Windows gives it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from autopara.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv))
