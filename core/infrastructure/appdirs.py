import os
import sys
from pathlib import Path


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def appdata_dir(app_name: str) -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / app_name
    return Path.home() / "AppData" / "Roaming" / app_name


def localdata_dir(app_name: str) -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / app_name
    return Path.home() / "AppData" / "Local" / app_name


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
