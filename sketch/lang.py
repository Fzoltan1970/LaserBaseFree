import json
from pathlib import Path

from core.infrastructure.appdirs import appdata_dir, ensure_dir, install_dir


def app_dir() -> Path:
    return ensure_dir(appdata_dir("SketchFree"))


def bundle_dir() -> Path:
    import sys

    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


CONFIG_FILE = app_dir() / "config.json"
DEFAULT_CONFIG_FILE = install_dir() / "defaults" / "sketch.config.default.json"


def _load_default_config() -> dict:
    defaults = {"language": "en", "laserbase_exe_path": ""}
    if DEFAULT_CONFIG_FILE.exists():
        try:
            with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                defaults.update(payload)
        except Exception:
            pass
    return defaults


def _load_config():
    defaults = _load_default_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                for k, v in defaults.items():
                    payload.setdefault(k, v)
                return payload
        except Exception:
            pass

    _save_config(defaults)
    return dict(defaults)


def _save_config(cfg):
    ensure_dir(CONFIG_FILE.parent)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def get_config_value(key: str, default=None):
    return _cfg.get(key, default)


def set_config_value(key: str, value):
    _cfg[key] = value
    _save_config(_cfg)


_cfg = _load_config()
LANG = _cfg.get("language", "en")

LANG_DIR = bundle_dir() / "lang"
_cache = {}


def _load_lang(lang):
    if lang in _cache:
        return _cache[lang]

    file = LANG_DIR / f"{lang}.json"
    if not file.exists():
        _cache[lang] = {}
        return _cache[lang]

    with open(file, "r", encoding="utf-8") as f:
        _cache[lang] = json.load(f)

    return _cache[lang]


def tr(key):
    return _load_lang(LANG).get(key, key)


def set_language(new_lang):
    global LANG
    LANG = new_lang
    _cfg["language"] = new_lang
    _save_config(_cfg)
