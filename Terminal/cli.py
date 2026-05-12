"""
Backward-compatible `python -m Terminal` launcher.

Important: do not duplicate CLI logic here. We delegate to `lorne.py` so
`Terminal` always matches the main entrypoint behavior after any updates.
"""
import sys
from pathlib import Path

_CLI_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _CLI_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> None:
    from lorne import main as lorne_main

    lorne_main()


if __name__ == "__main__":
    main()
