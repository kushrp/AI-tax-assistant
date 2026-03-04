from __future__ import annotations

import sys
from pathlib import Path

import pytest


def main() -> int:
    root = Path(__file__).resolve().parent
    # Allow test imports from local source tree without editable install.
    sys.path.insert(0, str(root))
    return pytest.main(["-q", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
