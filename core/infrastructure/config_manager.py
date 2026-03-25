import json
from pathlib import Path

from core.infrastructure.paths import APPDATA_DIR, DEFAULTS_DIR, LANGUAGE_DIR

CONFIG_FILE = APPDATA_DIR / "config.json"
DEFAULT_CONFIG_FILE = DEFAULTS_DIR / "laserbasefree.config.default.json"
LANG_DIR = LANGUAGE_DIR

DEFAULT_CONFIG = {
    "language": "en",
    "show_start_guide": True,
}


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
        return data if isinstance(data, dict) else {}


def _build_default_config() -> dict:
    if DEFAULT_CONFIG_FILE.exists():
        try:
            merged = dict(DEFAULT_CONFIG)
            merged.update(_read_json(DEFAULT_CONFIG_FILE))
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def _ensure_user_config_exists() -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        return

    defaults = _build_default_config()
    with CONFIG_FILE.open("w", encoding="utf-8") as handle:
        json.dump(defaults, handle, indent=4, ensure_ascii=False)


def load_config():
    _ensure_user_config_exists()
    try:
        data = _read_json(CONFIG_FILE)
    except Exception:
        return _build_default_config()

    defaults = _build_default_config()
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def save_config(config: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=4, ensure_ascii=False)


def load_language(lang_code: str):
    file_path = LANG_DIR / f"{lang_code}.json"

    if not file_path.exists():
        print(f"[WARN] Missing language file: {file_path}")
        return {}

    try:
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as e:
        print(f"[ERROR] Failed to load translation: {e}")
        return {}


class ConfigManager:
    def __init__(self):
        self._config = None

    def load(self):
        if self._config is None:
            self._config = load_config()
        return self._config

    def save(self, config: dict):
        self._config = config
        return save_config(config)

    def save_config(self, config: dict):
        return self.save(config)

    def load_language(self, lang_code: str):
        return load_language(lang_code)

    def translate(self, key: str, default: str) -> str:
        lang_code = self.load().get("language", "en")
        translations = self.load_language(lang_code)
        return translations.get(key, default)

    def get_available_languages(self) -> list[str]:
        if not LANG_DIR.exists():
            return []

        return sorted(path.stem for path in LANG_DIR.iterdir() if path.suffix == ".json")

    def add_machine_profile(self, profile: dict):
        config = self.load()
        profiles = config.get("profiles")
        if not isinstance(profiles, list):
            profiles = []
            config["profiles"] = profiles

        profiles.append(profile)
        self.save(config)
