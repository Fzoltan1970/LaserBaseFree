import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

import sketch.lang as lang

# Support script-style imports used by sketch/main_window.py (e.g. `import lang`).
SKETCH_DIR = Path(__file__).resolve().parent
if str(SKETCH_DIR) not in sys.path:
    sys.path.insert(0, str(SKETCH_DIR))

from sketch.main_window import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    base_dir = lang.bundle_dir()
    icon_path = (
        base_dir / "assets" / "app.ico"
        if hasattr(sys, "_MEIPASS")
        else base_dir.parent / "assets" / "app.ico"
    )
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
