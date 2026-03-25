import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from start.start_overlay import main


if __name__ == "__main__":
    raise SystemExit(main())
