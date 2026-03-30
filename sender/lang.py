from __future__ import annotations

import json
from pathlib import Path

from core.infrastructure.appdirs import appdata_dir, ensure_dir, install_dir


def app_dir() -> Path:
    return ensure_dir(appdata_dir("Sender"))


def bundle_dir() -> Path:
    import sys

    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


CONFIG_FILE = app_dir() / "config.json"
DEFAULT_CONFIG_FILE = install_dir() / "defaults" / "sender.config.default.json"
LANG_DIR = bundle_dir() / "lang"
ROOT_LANG_DIR = bundle_dir().parent / "language"


def _load_default_config() -> dict:
    defaults = {"language": "en"}
    if DEFAULT_CONFIG_FILE.exists():
        try:
            with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                defaults.update(payload)
        except Exception:
            pass
    return defaults


def _load_config() -> dict:
    defaults = _load_default_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                for key, value in defaults.items():
                    payload.setdefault(key, value)
                return payload
        except Exception:
            pass
    _save_config(defaults)
    return dict(defaults)


def _save_config(config: dict) -> None:
    ensure_dir(CONFIG_FILE.parent)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


_cfg = _load_config()
LANG = _cfg.get("language", "en")
_cache: dict[str, dict] = {}


def _load_lang(lang_code: str) -> dict:
    if lang_code in _cache:
        return _cache[lang_code]

    lang_file = LANG_DIR / f"{lang_code}.json"
    if not lang_file.exists():
        _cache[lang_code] = {}
        return _cache[lang_code]

    with open(lang_file, "r", encoding="utf-8") as f:
        _cache[lang_code] = json.load(f)
    return _cache[lang_code]


def _load_root_lang(lang_code: str) -> dict:
    lang_file = ROOT_LANG_DIR / f"{lang_code}.json"
    if not lang_file.exists():
        return {}
    with open(lang_file, "r", encoding="utf-8") as f:
        return json.load(f)


def tr(key: str) -> str:
    value = _load_lang(LANG).get(key)
    if value is not None:
        return value
    root_value = _load_root_lang(LANG).get(key)
    if root_value is not None:
        return root_value
    return key


def set_language(lang_code: str) -> None:
    global LANG
    LANG = lang_code
    _cfg["language"] = lang_code
    _save_config(_cfg)

