#!/usr/bin/env python3
"""Entry point for the Elite Dangerous Binds Editor.

Usage:
    python main.py                  # auto-detect a .binds file in the project
    python main.py path\\to\\file.binds
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bindseditor.gui import run  # noqa: E402


def main() -> None:
    initial_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run(initial_path=initial_path)


if __name__ == "__main__":
    main()
