import json
import locale
import subprocess
import sys
from pathlib import Path

from PyQt6.QtGui import QGuiApplication, QIcon
from core.infrastructure.appdirs import appdata_dir, ensure_dir
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMenu,
    QApplication,
    QMessageBox,
    QComboBox,
)
from PyQt6.QtCore import Qt


_START_LANG_DIR = Path(__file__).resolve().parent / "lang"


def load_start_translations(language: str) -> dict[str, str]:
    lang = (language or "en").strip().lower()
    candidates = [_START_LANG_DIR / f"{lang}.json"]
    if lang != "en":
        candidates.append(_START_LANG_DIR / "en.json")

    for path in candidates:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            continue
    return {}


def build_start_tr(language: str):
    translations = load_start_translations(language)

    def _tr(key: str, default: str | None = None) -> str:
        value = translations.get(key)
        if value is not None:
            return value
        return default if default is not None else key

    return _tr


class StartOverlay(QWidget):
    """
    Floating start guide overlay.

    This widget is intentionally passive:
    - It does not modify application state.
    - It does not open dialogs by itself.
    - It only emits intent via callbacks set by the parent.
    """

    def __init__(self, parent=None, tr=None, language_code: str = "en"):

        super().__init__(parent)

        # Use a fully frameless top-level window so only the custom launcher
        # surface is visible.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        self.tr = tr or (lambda k, d=None: d)
        self.language_code = language_code
        self._current_language = (language_code or "en").strip().lower() or "en"
        self._current_unit = "mm"
        self._current_mode = "diode"

        # Visual-only: card-sized, centered start panel
        self.setFixedWidth(460)
        self.adjustSize()

        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

        self.on_load_image = None
        self.on_new_entry = None
        self.on_continue_without_guide = None
        self.on_language_change = None
        self.on_unit_change = None
        self.on_mode_change = None

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self.setStyleSheet(
            """
            StartOverlay {
                background-color: #323c50;
                border: 1px solid #4c5a75;
                border-radius: 16px;
            }
        """
        )

        self.close_control = QLabel("X")
        self.close_control.setObjectName("closeControl")
        self.close_control.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_control.setStyleSheet(
            """
            QLabel#closeControl {
                color: #b8c0d4;
                font-size: 13px;
                font-weight: 600;
                background: transparent;
                border: none;
            }
            QLabel#closeControl:hover {
                color: #eef1f6;
            }
        """
        )
        self.close_control.mousePressEvent = self._handle_close_control
        layout.addWidget(
            self.close_control,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        self.title_label = QLabel(self.tr("suite_start_title", "LaserBase Suite"))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(
            """
            font-size: 18px;
            font-weight: 600;
            color: #e7eaf0;
            background: transparent;
            border: none;
            margin-bottom: 8px;
        """
        )
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(self.tr("suite_start_subtitle", "Choose an app to launch"))
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet("color: #b8c0d4;")
        layout.addWidget(self.subtitle_label)

        self.btn_load_image = QPushButton(self.tr("suite_start_laserbase", "LaserBase"))
        self.btn_load_image.clicked.connect(self._handle_load_image)
        self.btn_load_image.setStyleSheet(
            """
            QPushButton {
                background-color: #1b2538;
                border: 1px solid #2a3a55;
                border-radius: 12px;
                padding: 10px;
                font-weight: 600;
                color: #eef1f6;
            }
        """
        )
        layout.addWidget(self.btn_load_image)

        self.btn_new_entry = QPushButton(self.tr("suite_start_sketch", "Sketch"))
        self.btn_new_entry.clicked.connect(self._handle_new_entry)
        self.btn_new_entry.setStyleSheet(
            """
            QPushButton {
                background-color: #1b2538;
                border: 1px solid #2a3a55;
                border-radius: 12px;
                padding: 10px;
                color: #eef1f6;
            }
        """
        )
        layout.addWidget(self.btn_new_entry)

        self.btn_continue = QPushButton(self.tr("suite_start_sender", "Sender"))
        self.btn_continue.clicked.connect(self._handle_continue)
        self.btn_continue.setStyleSheet(
            """
            QPushButton {
                background-color: #1b2538;
                border: 1px solid #2a3a55;
                border-radius: 12px;
                padding: 8px;
                color: #c9d1e3;
            }
        """
        )
        layout.addWidget(self.btn_continue)

        selectors_layout = QHBoxLayout()
        selectors_layout.setContentsMargins(0, 0, 0, 0)
        selectors_layout.setSpacing(12)

        self.btn_language = QPushButton()
        self.btn_language.clicked.connect(self._handle_language_menu)
        self.btn_language.setFlat(True)
        self.btn_language.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_language.setStyleSheet(
            """
            QPushButton {
                color: #b8c0d4;
                background: transparent;
                border: none;
                text-align: left;
                padding-top: 4px;
            }
        """
        )
        selectors_layout.addWidget(self.btn_language, 1, Qt.AlignmentFlag.AlignLeft)

        self.unit_selector = QComboBox()
        self.unit_selector.addItems(["mm", "inch"])
        self.unit_selector.currentTextChanged.connect(self._handle_unit_changed)
        self.unit_selector.setStyleSheet(
            """
            QComboBox {
                background-color: #1b2538;
                border: 1px solid #2a3a55;
                border-radius: 8px;
                padding: 6px 10px;
                color: #eef1f6;
                min-width: 80px;
            }
        """
        )
        selectors_layout.addWidget(self.unit_selector)

        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["diode", "fiber"])
        self.mode_selector.currentTextChanged.connect(self._handle_mode_changed)
        self.mode_selector.setStyleSheet(
            """
            QComboBox {
                background-color: #1b2538;
                border: 1px solid #2a3a55;
                border-radius: 8px;
                padding: 6px 10px;
                color: #eef1f6;
                min-width: 90px;
            }
        """
        )
        selectors_layout.addWidget(self.mode_selector)

        layout.addLayout(selectors_layout)

        self._apply_translations()

    def _apply_translations(self) -> None:
        self.title_label.setText(self.tr("suite_start_title", "LaserBase Suite"))
        self.subtitle_label.setText(self.tr("suite_start_subtitle", "Choose an app to launch"))
        self.btn_load_image.setText(self.tr("suite_start_laserbase", "LaserBase"))
        self.btn_new_entry.setText(self.tr("suite_start_sketch", "Sketch"))
        self.btn_continue.setText(self.tr("suite_start_sender", "Sender"))
        self.btn_language.setText(
            f"{self.tr('language_label', 'Language')} / {self._current_language}"
        )

    def update_translations(self, tr, language_code: str) -> None:
        self.tr = tr or (lambda k, d=None: d)
        self.language_code = (language_code or "en").strip().lower() or "en"
        self._current_language = self.language_code
        self._apply_translations()

    # ------------------------------------------------------------------
    # Internal handlers (callbacks only, no logic)
    # ------------------------------------------------------------------

    def _handle_load_image(self):
        if callable(self.on_load_image):
            self.on_load_image()

    def _handle_new_entry(self):
        if callable(self.on_new_entry):
            self.on_new_entry()

    def _handle_continue(self):
        if callable(self.on_continue_without_guide):
            self.on_continue_without_guide()

    def _handle_language_menu(self):
        menu = QMenu(self)
        for code in ("en", "hu", "de", "fr", "it"):
            action = menu.addAction(code)
            action.triggered.connect(lambda checked=False, lang=code: self._select_language(lang))
        menu.exec(self.btn_language.mapToGlobal(self.btn_language.rect().bottomLeft()))

    def _handle_close_control(self, _event):
        self.close()

    def _select_language(self, code: str) -> None:
        self._current_language = (code or "en").strip().lower() or "en"
        self._apply_translations()
        if callable(self.on_language_change):
            self.on_language_change(self._current_language)

    def _handle_unit_changed(self, unit: str) -> None:
        self._current_unit = unit or "mm"
        if callable(self.on_unit_change):
            self.on_unit_change(self._current_unit)

    def _handle_mode_changed(self, mode: str) -> None:
        self._current_mode = mode or "diode"
        if callable(self.on_mode_change):
            self.on_mode_change(self._current_mode)


_SUPPORTED_LANGUAGES = {"en", "hu", "de", "fr", "it"}
_DEFAULT_CONFIG = {"language": "en", "unit": "mm", "mode": "diode"}


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _start_dir() -> Path:
    runtime_start = _runtime_root() / "start"
    if runtime_start.exists():
        return runtime_start
    return Path(__file__).resolve().parent


def _config_path() -> Path:
    return _start_dir() / "config.json"


def _user_config_path() -> Path:
    return appdata_dir("StartFree") / "config.json"


def _icon_path() -> Path | None:
    candidates = [
        _runtime_root() / "assets" / "app.ico",
        _start_dir() / "assets" / "app.ico",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("laserbase.start")
    except Exception:
        pass


def _load_start_config() -> dict:
    user_path = _user_config_path()
    if not user_path.exists():
        config = dict(_DEFAULT_CONFIG)
        bundled_path = _config_path()
        if bundled_path.exists():
            try:
                with bundled_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    config.update(data)
            except Exception:
                pass
        else:
            detected_language = "en"
            locale_name, _ = locale.getdefaultlocale()
            if locale_name:
                language_code = locale_name[:2].lower()
                if language_code in _SUPPORTED_LANGUAGES:
                    detected_language = language_code
            config["language"] = detected_language
        _save_start_config(config)
        return config

    try:
        with user_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            merged = dict(_DEFAULT_CONFIG)
            merged.update(data)
            return merged
    except Exception:
        pass
    return dict(_DEFAULT_CONFIG)


def _save_start_config(config: dict) -> None:
    path = _user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)


def _sync_suite_language(code: str, unit: str = "mm", mode: str = "diode") -> None:
    for app_name in ("LaserBaseFree", "SenderFree", "SketchFree"):
        cfg_path = appdata_dir(app_name) / "config.json"
        try:
            payload = {}
            if cfg_path.exists():
                with cfg_path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    payload = loaded
            payload["language"] = code
            payload["unit"] = unit
            payload["mode"] = mode
            ensure_dir(cfg_path.parent)
            with cfg_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=4)
        except Exception:
            continue


def _standalone_launch_command(app_name: str, module_name: str) -> list[str]:
    if getattr(sys, "frozen", False):
        current_exe_dir = Path(sys.executable).resolve().parent
        targets = {
            "laserbase": current_exe_dir / "LaserBaseFree" / "LaserBaseFree.exe",
            "sketch": current_exe_dir / "Sketch" / "Sketch.exe",
            "sender": current_exe_dir / "SenderFree" / "SenderFree.exe",
        }
        exe_path = targets.get(module_name)
        if exe_path and exe_path.exists():
            return [str(exe_path)]
        raise FileNotFoundError(
            f"{app_name} executable not found in sibling app folders under: {current_exe_dir}"
        )

    if module_name == "laserbase":
        return [sys.executable, "main.py"]
    return [sys.executable, "-m", module_name]


def _launch_standalone_app(app_name: str, module_name: str) -> None:
    launch_cmd = _standalone_launch_command(app_name, module_name)
    launch_cwd = (
        str(Path(launch_cmd[0]).parent)
        if getattr(sys, "frozen", False)
        else str(Path(__file__).resolve().parents[1])
    )
    subprocess.Popen(
        launch_cmd,
        cwd=launch_cwd,
        start_new_session=True,
    )


def main() -> int:
    _set_windows_app_id()
    qt_app = QApplication(sys.argv)

    icon_path = _icon_path()
    if icon_path is not None:
        icon = QIcon(str(icon_path))
        qt_app.setWindowIcon(icon)

    config = _load_start_config()
    startup_language = str(config.get("language", "en")).strip().lower()
    if startup_language not in _SUPPORTED_LANGUAGES:
        startup_language = "en"
    startup_unit = str(config.get("unit", "mm")).strip().lower() or "mm"
    if startup_unit not in {"mm", "inch"}:
        startup_unit = "mm"
    startup_mode = str(config.get("mode", "diode")).strip().lower() or "diode"
    if startup_mode not in {"diode", "fiber"}:
        startup_mode = "diode"

    overlay = StartOverlay(tr=build_start_tr(startup_language), language_code=startup_language)
    overlay._current_unit = startup_unit
    overlay._current_mode = startup_mode
    overlay.unit_selector.setCurrentText(startup_unit)
    overlay.mode_selector.setCurrentText(startup_mode)
    if icon_path is not None:
        overlay.setWindowIcon(icon)

    def _launch_and_quit(app_name: str, module_name: str) -> None:
        try:
            _launch_standalone_app(app_name, module_name)
            qt_app.quit()
        except Exception as exc:
            QMessageBox.warning(None, app_name, f"{app_name} launch failed: {exc}")

    def _change_language(language_code: str) -> None:
        code = (language_code or "en").strip().lower()
        if code not in _SUPPORTED_LANGUAGES:
            code = "en"
        updated = dict(config)
        updated["language"] = code
        updated["unit"] = overlay._current_unit
        updated["mode"] = overlay._current_mode
        _save_start_config(updated)
        _sync_suite_language(code, overlay._current_unit, overlay._current_mode)
        config.update(updated)
        overlay.update_translations(build_start_tr(code), code)

    def _change_unit(unit: str) -> None:
        value = (unit or "mm").strip().lower() or "mm"
        if value not in {"mm", "inch"}:
            value = "mm"
        overlay._current_unit = value
        updated = dict(config)
        updated["language"] = overlay._current_language
        updated["unit"] = value
        updated["mode"] = overlay._current_mode
        _save_start_config(updated)
        _sync_suite_language(overlay._current_language, value, overlay._current_mode)
        config.update(updated)

    def _change_mode(mode: str) -> None:
        value = (mode or "diode").strip().lower() or "diode"
        if value not in {"diode", "fiber"}:
            value = "diode"
        overlay._current_mode = value
        updated = dict(config)
        updated["language"] = overlay._current_language
        updated["unit"] = overlay._current_unit
        updated["mode"] = value
        _save_start_config(updated)
        _sync_suite_language(overlay._current_language, overlay._current_unit, value)
        config.update(updated)

    overlay.on_load_image = lambda: _launch_and_quit("LaserBaseFree", "laserbase")
    overlay.on_new_entry = lambda: _launch_and_quit("Sketch", "sketch")
    overlay.on_continue_without_guide = lambda: _launch_and_quit("SenderFree", "sender")
    overlay.on_language_change = _change_language
    overlay.on_unit_change = _change_unit
    overlay.on_mode_change = _change_mode

    overlay.show()
    return qt_app.exec()
