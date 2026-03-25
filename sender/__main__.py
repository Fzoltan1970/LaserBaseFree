from __future__ import annotations

import os
import sys
import traceback

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from sender.lang import bundle_dir
from sender.sender_window import SenderWindow

def excepthook(exc_type, exc_value, exc_traceback):
    print("UNCAUGHT EXCEPTION:")
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    input("Press Enter to exit...")

sys.excepthook = excepthook

def main() -> int:
    if os.getenv("SENDER_WORKER", "0").strip() == "1" or "--sender-worker" in sys.argv[1:]:
        if "--sender-worker" in sys.argv[1:]:
            marker_index = sys.argv.index("--sender-worker")
            argv = sys.argv[marker_index + 1 :]
        else:
            argv = sys.argv[1:]
        from sender.sender_worker import main as worker_main

        original_argv = sys.argv[:]
        try:
            sys.argv = [original_argv[0], *argv]
            return int(worker_main())
        finally:
            sys.argv = original_argv

    app = QApplication(sys.argv)
    base_dir = bundle_dir()
    icon_path = (
        base_dir / "assets" / "app.ico"
        if hasattr(sys, "_MEIPASS")
        else base_dir.parent / "assets" / "app.ico"
    )
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = SenderWindow()
    app._sender_window = window  # type: ignore[attr-defined]
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
