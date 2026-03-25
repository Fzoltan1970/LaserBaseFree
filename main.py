import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app import create_app


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--open", dest="open_path")
    args, _ = parser.parse_known_args(sys.argv[1:])

    qt_app = QApplication(sys.argv)
    icon_path = Path(__file__).resolve().parent / "assets" / "app.ico"
    if icon_path.exists():
        qt_app.setWindowIcon(QIcon(str(icon_path)))

    application = create_app()
    if not application.start(open_path=args.open_path):
        sys.exit(0)

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
