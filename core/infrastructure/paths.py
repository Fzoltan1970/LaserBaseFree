from core.infrastructure.appdirs import appdata_dir, ensure_dir, install_dir


APP_NAME = "LaserBaseFree"
BASE_DIR = install_dir()
APPDATA_DIR = ensure_dir(appdata_dir(APP_NAME))
DATA_DIR = ensure_dir(APPDATA_DIR / "data")
DEFAULTS_DIR = BASE_DIR / "defaults"
LANGUAGE_DIR = BASE_DIR / "language"
KNOWLEDGE_DIR = BASE_DIR / "docs" / "knowledge"
