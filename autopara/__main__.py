"""Entry point: ``python -m autopara [--hidden] [--no-rebuild]``.

A source run refreshes the installed copy before starting, so testing a change does not mean
reinstalling; ``--no-rebuild`` opts out. See ``core/refresh.py``.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
