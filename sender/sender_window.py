from __future__ import annotations

import time
import re
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QMenuBar,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from sender import lang
from sender.lang import tr
from sender.sender_client import SenderClient
from sender.sender_panel import SenderPanel


class SenderWindow(QMainWindow):
    _DEFAULT_BAUDRATES = ("115200", "250000", "921600")
    _MARKER_FEED_MM_MIN = 100.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("APP_TITLE"))
        self.resize(900, 650)

        self._sender_client: Optional[SenderClient] = None
        self._selected_path: Optional[str] = None
        self._is_connected = False
        self._suppress_port_change = False
        self._current_state = "IDLE"
        self._estimated_time_s: Optional[int] = None
        self._elapsed_start_monotonic: Optional[float] = None
        self._elapsed_accum_s: float = 0.0
        self._distance_mode: str = "G90"
        self._laser_stopped: bool = False
        self._laser_firing: bool = False
        self._firing_pulse_on: bool = False
        self._pending_stream_start: Optional[
            tuple[str, str, tuple[float, float, float]]
        ] = None
        self.raw_machine_position_xyz: Optional[tuple[float, float, float]] = None
        self.machine_start_raw_xyz: Optional[tuple[float, float, float]] = None
        self.work_start_raw_xyz: Optional[tuple[float, float, float]] = None

        self._status_label = QLabel()
        self._estimated_time_label = QLabel()
        self._time_label = QLabel()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)
        self._marker_auto_off_timer = QTimer(self)
        self._marker_auto_off_timer.setSingleShot(True)
        self._marker_auto_off_timer.setInterval(10000)
        self._marker_auto_off_timer.timeout.connect(self._marker_laser_off)
        self._status_poll_timer = QTimer(self)
        self._status_poll_timer.setInterval(300)
        self._status_poll_timer.timeout.connect(self._poll_raw_machine_position)
        self._firing_timer = QTimer(self)
        self._firing_timer.setInterval(300)
        self._firing_timer.timeout.connect(self._update_estop_button_style)
        self._marker_pwm_max: Optional[float] = None
        self._marker_active: bool = False
        self._frame_running: bool = False
        self._frame_timer = QTimer(self)
        self._frame_timer.setSingleShot(True)
        self._frame_timer.timeout.connect(self._finish_frame_run)

        self._port_combo = QComboBox()
        self._refresh_ports_btn = QPushButton()

        self._baud_combo = QComboBox()
        self._baud_combo.addItems(self._DEFAULT_BAUDRATES)
        self._baud_combo.setCurrentText(self._DEFAULT_BAUDRATES[0])

        self._connect_btn = QPushButton()
        self._load_file_btn = QPushButton()
        self._path_label = QLabel()
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._start_btn = QPushButton()
        self._stop_btn = QPushButton()
        self._stop_btn.setStyleSheet("font-weight: bold; color: #d11;")
        self._e_stop_btn = QPushButton()
        self._e_stop_btn.setFixedSize(74, 74)
        self._laser_status_label = QLabel()
        self._speed_label = QLabel()
        self._tx_rate_label = QLabel()
        self._data_rate_label = QLabel()
        for lbl in (self._speed_label, self._tx_rate_label, self._data_rate_label):
            lbl.setStyleSheet("font-family: monospace;")
        self._pause_btn = QPushButton()
        self._resume_btn = QPushButton()
        self._unlock_btn = QPushButton()
        self._stream_mode_combo = QComboBox()
        self._stream_mode_combo.addItem("", "auto")
        self._stream_mode_combo.addItem("", "line")
        self._stream_mode_combo.addItem("", "byte")
        self._stream_mode_combo.setCurrentIndex(0)

        self.sender_panel = SenderPanel(self)

        self._language_actions: dict[str, QAction] = {}

        self._build_ui()
        self._build_menu()
        self._bind_events()
        self._refresh_serial_ports()
        self._update_controls_for_state("IDLE")
        self._update_laser_status_label()
        self._update_estop_button_style()
        self.retranslate_ui()
        self._refresh_position_block()

        self._telemetry_lines = 0
        self._telemetry_bytes = 0
        self._telemetry_distance_mm = 0.0
        self._telemetry_last_x_mm: Optional[float] = None
        self._telemetry_start = time.monotonic()

        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(500)
        self._telemetry_timer.timeout.connect(self._update_telemetry)
        self._telemetry_timer.start()

    def _build_menu(self) -> None:
        menu_bar = QMenuBar(self)
        self._app_menu = menu_bar.addMenu("")
        self._language_menu = menu_bar.addMenu("")

        for label, code in (
            ("Magyar", "hu"),
            ("English", "en"),
            ("Deutsch", "de"),
            ("Français", "fr"),
            ("Italiano", "it"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, c=code: self._set_language(c))
            self._language_menu.addAction(action)
            self._language_actions[code] = action

        self._exit_action = QAction("", self)
        self._exit_action.triggered.connect(self.close)
        self._app_menu.addAction(self._exit_action)

        self._about_action = QAction("", self)
        self._about_action.triggered.connect(self.show_about)
        menu_bar.addAction(self._about_action)
        self.setMenuBar(menu_bar)

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._connection_box = QGroupBox()
        connection_box = self._connection_box
        connection_layout = QGridLayout(connection_box)
        self._port_label = QLabel()
        connection_layout.addWidget(self._port_label, 0, 0)
        connection_layout.addWidget(self._port_combo, 0, 1)
        connection_layout.addWidget(self._refresh_ports_btn, 0, 2)
        self._baudrate_label = QLabel()
        connection_layout.addWidget(self._baudrate_label, 1, 0)
        connection_layout.addWidget(self._baud_combo, 1, 1)
        connection_layout.addWidget(self._connect_btn, 1, 2)

        self._file_box = QGroupBox()
        file_box = self._file_box
        file_layout = QHBoxLayout(file_box)
        file_layout.addWidget(self._load_file_btn)
        file_layout.addWidget(self._path_label, 1)

        self._control_box = QGroupBox()
        control_box = self._control_box
        control_root_layout = QVBoxLayout(control_box)

        estop_row = QHBoxLayout()
        estop_row.addStretch(1)
        e_stop_container = QWidget(self)
        e_stop_layout = QVBoxLayout(e_stop_container)
        e_stop_layout.setContentsMargins(0, 0, 0, 0)
        e_stop_layout.setSpacing(4)
        e_stop_layout.addWidget(self._e_stop_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        e_stop_layout.addWidget(self._laser_status_label, 0, Qt.AlignmentFlag.AlignHCenter)

        telemetry_widget = QWidget(self)
        telemetry_box = QVBoxLayout(telemetry_widget)
        telemetry_box.setContentsMargins(0, 0, 0, 0)
        telemetry_box.setSpacing(2)
        telemetry_box.addWidget(self._speed_label)
        telemetry_box.addWidget(self._tx_rate_label)
        telemetry_box.addWidget(self._data_rate_label)

        telemetry_width = telemetry_widget.sizeHint().width()
        left_placeholder = QWidget(self)
        left_placeholder.setFixedWidth(telemetry_width + 12)

        estop_row.addWidget(left_placeholder)
        estop_row.addWidget(e_stop_container)
        estop_row.addSpacing(12)
        estop_row.addWidget(telemetry_widget)
        estop_row.addStretch(1)

        controls_row = QHBoxLayout()
        controls_row.addWidget(self._start_btn)
        controls_row.addWidget(self._stop_btn)
        controls_row.addWidget(self._pause_btn)
        controls_row.addWidget(self._resume_btn)
        controls_row.addWidget(self._unlock_btn)
        self._mode_label = QLabel()
        controls_row.addWidget(self._mode_label)
        controls_row.addWidget(self._stream_mode_combo)
        controls_row.addWidget(self._estimated_time_label)
        controls_row.addWidget(self._time_label)
        controls_row.addStretch(1)
        self._state_label = QLabel()
        controls_row.addWidget(self._state_label)
        controls_row.addWidget(self._status_label)

        control_root_layout.addLayout(estop_row)
        control_root_layout.addLayout(controls_row)

        lower_layout = QHBoxLayout()
        lower_layout.setSpacing(10)

        left_column = QVBoxLayout()
        left_column.addWidget(connection_box)
        left_column.addWidget(file_box)
        left_column.addWidget(control_box)
        left_column.addWidget(self.sender_panel.progress_widget)
        left_column.addWidget(self.sender_panel.jog_box, 1)

        right_column = QVBoxLayout()
        right_column.addWidget(self.sender_panel.terminal_box)
        right_column.addWidget(self.sender_panel.log_view, 1)
        right_column.addWidget(self.sender_panel.frame_box)
        right_column.addWidget(self.sender_panel.position_box)

        lower_layout.addLayout(left_column, 1)
        lower_layout.addLayout(right_column, 1)

        root.addLayout(lower_layout, 1)

        self.setCentralWidget(central)

    def _set_language(self, lang_code: str) -> None:
        if not lang_code or lang_code == lang.LANG:
            return
        lang.set_language(lang_code)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("APP_TITLE"))
        self._app_menu.setTitle(tr("MENU_SENDER"))
        self._language_menu.setTitle(tr("MENU_LANGUAGE"))
        self._exit_action.setText(tr("EXIT"))
        self._about_action.setText(tr("sender.about.title"))

        self._connection_box.setTitle(tr("CONNECTION"))
        self._port_label.setText(tr("PORT"))
        self._baudrate_label.setText(tr("BAUDRATE"))
        self._refresh_ports_btn.setText(tr("REFRESH"))
        self._refresh_connect_button_text()

        self._file_box.setTitle(tr("FILE"))
        self._load_file_btn.setText(tr("LOAD_GCODE"))
        if not self._selected_path:
            self._path_label.setText(tr("NO_FILE_SELECTED"))

        self._control_box.setTitle(tr("CONTROL"))
        self._start_btn.setText(tr("START_SEND"))
        self._stop_btn.setText(tr("STOP"))
        self._e_stop_btn.setText(tr("E_STOP"))
        self._pause_btn.setText(tr("PAUSE"))
        self._resume_btn.setText(tr("RESUME"))
        self._unlock_btn.setText(tr("UNLOCK"))
        self._mode_label.setText(tr("MODE"))
        self._state_label.setText(tr("STATE"))

        self._stream_mode_combo.setItemText(0, tr("MODE_AUTO"))
        self._stream_mode_combo.setItemText(1, tr("MODE_LINE"))
        self._stream_mode_combo.setItemText(2, tr("MODE_BYTE"))

        self._status_label.setText(tr("IDLE") if self._current_state == "IDLE" else self._current_state)
        self._estimated_time_label.setText(f"{tr('EST')}: {self._format_estimated_time(self._estimated_time_s)}")
        self._update_elapsed_time()
        self._update_laser_status_label()
        self._update_telemetry_labels(0.0, 0.0, 0.0)

        for code, action in self._language_actions.items():
            action.setChecked(code == lang.LANG)

        self.sender_panel.retranslate_ui()
        self._refresh_position_block()

    def show_about(self) -> None:
        def _sender_tr(key: str, fallback: str) -> str:
            value = tr(key)
            if value == key:
                return fallback
            return value

        msg = QMessageBox(self)
        msg.setWindowTitle(_sender_tr("sender.about.title", "Névjegy"))
        msg.setText(
            "<br>".join(
                (
                    f"<b>{_sender_tr('sender.about.name', 'LaserBase Sender')}</b>",
                    _sender_tr("sender.about.description", "LaserBase G-code sender"),
                    "",
                    _sender_tr("sender.about.author", "Author: LaserBase"),
                    _sender_tr("sender.about.year", "2026"),
                    "",
                    _sender_tr("sender.about.support_text", "Support the project:"),
                )
            )
        )
        msg.setInformativeText(
            f'<a href="https://paypal.me/ZoltanFitos?locale.x=hu_HU&country.x=HU">{_sender_tr("sender.about.support_link", "Support (PayPal)")}</a>'
        )
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _bind_events(self) -> None:
        self._refresh_ports_btn.clicked.connect(self._refresh_serial_ports)
        self._connect_btn.clicked.connect(self._connect_only)
        self._port_combo.currentIndexChanged.connect(self._on_port_selection_changed)
        self._load_file_btn.clicked.connect(self._load_file)
        self._start_btn.clicked.connect(self._start_send)
        self._stop_btn.clicked.connect(self._stop_send)
        self._pause_btn.clicked.connect(self._pause_send)
        self._resume_btn.clicked.connect(self._resume_send)
        self._unlock_btn.clicked.connect(self._unlock_alarm)
        self._e_stop_btn.clicked.connect(self._toggle_e_stop)
        self.sender_panel.btn_marker_on.clicked.connect(self._marker_laser_on)
        self.sender_panel.btn_marker_off.clicked.connect(self._marker_laser_off)
        self.sender_panel.terminal_send_btn.clicked.connect(self._send_terminal_command)
        self.sender_panel.btn_home.clicked.connect(self._send_home_command)
        self.sender_panel.btn_run_frame.clicked.connect(self._run_frame)
        self.sender_panel.terminal_read_settings_btn.clicked.connect(
            self._send_read_settings_command
        )
        self.sender_panel.terminal_input.returnPressed.connect(self._send_terminal_command)
        self.sender_panel.btn_set_machine_start.clicked.connect(
            self._set_machine_start_from_current_position
        )
        self.sender_panel.btn_move_to_machine_start.clicked.connect(
            self._move_to_machine_start
        )
        self.sender_panel.btn_clear_machine_start.clicked.connect(self._clear_machine_start)
        self.sender_panel.btn_set_work_start.clicked.connect(self._set_work_start_from_current_position)
        self.sender_panel.btn_move_to_work_start.clicked.connect(self._move_to_work_start)
        self.sender_panel.btn_clear_work_start.clicked.connect(self._clear_work_start)

        step = self.sender_panel.jog_step
        self.sender_panel.btn_x_plus.clicked.connect(lambda: self._jog(dx=step.value()))
        self.sender_panel.btn_x_minus.clicked.connect(
            lambda: self._jog(dx=-step.value())
        )
        self.sender_panel.btn_y_plus.clicked.connect(lambda: self._jog(dy=step.value()))
        self.sender_panel.btn_y_minus.clicked.connect(
            lambda: self._jog(dy=-step.value())
        )
        self.sender_panel.btn_z_plus.clicked.connect(lambda: self._jog(dz=step.value()))
        self.sender_panel.btn_z_minus.clicked.connect(
            lambda: self._jog(dz=-step.value())
        )
        self.sender_panel.frame_width.valueChanged.connect(self._update_frame_ui_state)
        self.sender_panel.frame_height.valueChanged.connect(self._update_frame_ui_state)
        self.sender_panel.frame_speed.valueChanged.connect(self._update_frame_ui_state)
        self.sender_panel.frame_power.valueChanged.connect(self._update_frame_ui_state)
        self.sender_panel.marker_power.valueChanged.connect(self._update_marker_ui_state)

    def _refresh_serial_ports(self) -> None:
        current = self._port_combo.currentData() or self._port_combo.currentText()
        self._suppress_port_change = True
        self._port_combo.clear()

        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        for port in ports:
            label = f"{port.device}"
            if port.description:
                label += f" — {port.description}"
            self._port_combo.addItem(label, port.device)

        if self._port_combo.count() == 0:
            self._port_combo.addItem(tr("NO_PORTS_FOUND"), "")

        if current:
            for idx in range(self._port_combo.count()):
                if self._port_combo.itemData(idx) == current:
                    self._port_combo.setCurrentIndex(idx)
                    break
        self._suppress_port_change = False

    def _on_port_selection_changed(self, _index: int) -> None:
        if self._suppress_port_change:
            return
        if self._current_state in {"RUNNING", "HOLDING", "STOPPING"}:
            return
        if not self._sender_client:
            return

        port = self._selected_port()
        self._on_connection_changed(False)
        if not port:
            return

        try:
            self._sender_client.connect_machine(port=port, baud=self._selected_baudrate())
        except Exception as exc:
            self._log(self._format_connect_error(exc))

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("LOAD_GCODE"),
            "",
            f"{tr('GCODE_FILTER')};;{tr('ALL_FILES_FILTER')}",
        )
        if not path:
            return

        self._selected_path = path
        self._path_label.setText(path)
        metadata = self._parse_loaded_file_metadata(path)
        self._estimated_time_s = metadata.get("estimated_time_s")
        self.sender_panel.frame_width.setValue(0.0)
        self.sender_panel.frame_height.setValue(0.0)
        self.sender_panel.frame_speed.setValue(0.0)
        self.sender_panel.frame_power.setValue(0.0)
        self._apply_frame_metadata(metadata)
        self._estimated_time_label.setText(
            f"{tr('EST')}: {self._format_estimated_time(self._estimated_time_s)}"
        )
        self._marker_active = False
        self._update_marker_ui_state()
        self._update_estop_button_style()
        self._reset_elapsed_time()
        self._update_frame_ui_state()

    def _parse_loaded_file_metadata(self, path: str) -> dict[str, Optional[float | int]]:
        metadata: dict[str, Optional[float | int]] = {
            "estimated_time_s": None,
            "frame_width_mm": None,
            "frame_height_mm": None,
            "frame_speed_mm_min": None,
            "frame_power_percent": None,
        }
        int_patterns = {
            "estimated_time_s": re.compile(r"^;ESTIMATED_TIME_S=(\d+)\s*$"),
        }
        float_patterns = {
            "frame_width_mm": re.compile(r"^;FRAME_WIDTH_MM=([-+]?\d*\.?\d+)\s*$"),
            "frame_height_mm": re.compile(r"^;FRAME_HEIGHT_MM=([-+]?\d*\.?\d+)\s*$"),
            "frame_speed_mm_min": re.compile(r"^;FRAME_SPEED_MM_MIN=([-+]?\d*\.?\d+)\s*$"),
            "frame_power_percent": re.compile(r"^;FRAME_POWER_PERCENT=([-+]?\d*\.?\d+)\s*$"),
        }
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as gcode_file:
                for line in gcode_file:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if not stripped.startswith(";"):
                        break
                    for key, pattern in int_patterns.items():
                        if metadata.get(key) is not None:
                            continue
                        match = pattern.match(stripped)
                        if match:
                            metadata[key] = int(match.group(1))
                    for key, pattern in float_patterns.items():
                        if metadata.get(key) is not None:
                            continue
                        match = pattern.match(stripped)
                        if not match:
                            continue
                        try:
                            metadata[key] = float(match.group(1))
                        except ValueError:
                            metadata[key] = None
        except OSError as exc:
            self._log(f"Failed to read estimated time: {exc}")
        return metadata

    def _apply_frame_metadata(self, metadata: dict[str, Optional[float | int]]) -> None:
        width_mm = metadata.get("frame_width_mm")
        if isinstance(width_mm, (int, float)) and width_mm > 0:
            self.sender_panel.frame_width.setValue(float(width_mm))

        height_mm = metadata.get("frame_height_mm")
        if isinstance(height_mm, (int, float)) and height_mm > 0:
            self.sender_panel.frame_height.setValue(float(height_mm))

        speed_mm_min = metadata.get("frame_speed_mm_min")
        if isinstance(speed_mm_min, (int, float)) and speed_mm_min > 0:
            self.sender_panel.frame_speed.setValue(float(speed_mm_min))

        power_percent = metadata.get("frame_power_percent")
        if isinstance(power_percent, (int, float)) and power_percent > 0:
            self.sender_panel.frame_power.setValue(min(float(power_percent), 2.0))

    def _format_estimated_time(self, seconds: Optional[int]) -> str:
        if seconds is None or seconds < 0:
            return "--:--"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remainder_seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{remainder_seconds:02d}"

    def _selected_port(self) -> str:
        return (self._port_combo.currentData() or "").strip()

    def _selected_baudrate(self) -> int:
        try:
            return int(self._baud_combo.currentText().strip())
        except ValueError:
            return 115200

    def _connect_only(self) -> None:
        if self._is_connected:
            if self._current_state != "IDLE" or self._frame_running:
                return
            if not self._sender_client:
                return
            try:
                self._sender_client.disconnect_machine()
            except Exception as exc:
                self._log(f"Disconnect failed: {exc}")
            return

        port = self._selected_port()
        if not port:
            QMessageBox.warning(self, tr("APP_TITLE"), tr("SELECT_PORT_FIRST"))
            return

        client = self._ensure_sender_client()
        try:
            client.connect_machine(port=port, baud=self._selected_baudrate())
        except Exception as exc:
            self._on_connection_changed(False)
            self._log(self._format_connect_error(exc))

    def _start_send(self) -> None:
        if self._current_state == "ALARM":
            self._log("ALARM active; unlock with $X before Start Send.")
            return

        if not self._selected_path:
            QMessageBox.warning(self, tr("APP_TITLE"), tr("LOAD_GCODE_FIRST"))
            return

        client = self._sender_client
        if not self._is_connected or client is None:
            self._log("Start blocked: no active machine connection.")
            return

        try:
            if self.work_start_raw_xyz is not None:
                if self.raw_machine_position_xyz is None:
                    self._log("Start blocked: current raw machine position is unknown.")
                    return
            mode = str(self._stream_mode_combo.currentData() or "auto")
            if self._move_to_saved_raw_point(self.work_start_raw_xyz):
                self._pending_stream_start = (
                    self._selected_path,
                    mode,
                    self.work_start_raw_xyz,
                )
                self._update_controls_for_state(self._current_state)
                return
            self._start_stream_now(self._selected_path, mode)
        except Exception as exc:
            self._log(
                self._format_connect_error(exc)
                if isinstance(exc, PermissionError)
                else f"Start failed: {exc}"
            )

    def _stop_send(self) -> None:
        self._stop_elapsed_tracking()
        if self._sender_client:
            try:
                if self._frame_running:
                    self._sender_client.send_realtime("\x18")
                    self._finish_frame_run()
                else:
                    self._sender_client.stop_stream()
            except Exception as exc:
                self._log(f"Stop failed: {exc}")

    def _reset_elapsed_time(self) -> None:
        self._elapsed_accum_s = 0.0
        self._elapsed_start_monotonic = None
        self._elapsed_timer.stop()
        self._time_label.setText(f"{tr('TIME')}: 00:00:00")

    def _pause_elapsed_tracking(self) -> None:
        if self._elapsed_start_monotonic is None:
            return
        self._elapsed_accum_s += time.monotonic() - self._elapsed_start_monotonic
        self._elapsed_start_monotonic = None
        self._elapsed_timer.stop()
        self._update_elapsed_time()

    def _resume_elapsed_tracking(self) -> None:
        if self._elapsed_start_monotonic is not None:
            return
        self._elapsed_start_monotonic = time.monotonic()
        self._elapsed_timer.start()

    def _stop_elapsed_tracking(self) -> None:
        if self._elapsed_start_monotonic is not None:
            self._elapsed_accum_s += time.monotonic() - self._elapsed_start_monotonic
        self._elapsed_start_monotonic = None
        self._elapsed_timer.stop()
        self._update_elapsed_time()

    def _update_elapsed_time(self) -> None:
        elapsed_seconds = int(self._elapsed_accum_s)
        if self._elapsed_start_monotonic is not None:
            elapsed_seconds += int(time.monotonic() - self._elapsed_start_monotonic)
        self._time_label.setText(
            f"{tr('TIME')}: {self._format_estimated_time(elapsed_seconds)}"
        )

    def _unlock_alarm(self) -> None:
        if self._sender_client:
            try:
                self._sender_client.send_line("$X")
            except Exception as exc:
                self._log(f"Unlock failed: {exc}")

    def _pause_send(self) -> None:
        if not self._sender_client:
            return
        self._pause_elapsed_tracking()
        self._log("> Pause")
        try:
            self._sender_client.pause_stream()
        except Exception as exc:
            self._log(f"Pause failed: {exc}")

    def _resume_send(self) -> None:
        if not self._sender_client:
            return
        self._resume_elapsed_tracking()
        self._log("> Resume")
        try:
            self._sender_client.resume_stream()
        except Exception as exc:
            self._log(f"Resume failed: {exc}")

    def _track_distance_mode(self, line: str) -> None:
        normalized = line.strip().upper()
        if normalized.startswith("G90"):
            self._distance_mode = "G90"
        elif normalized.startswith("G91"):
            self._distance_mode = "G91"

    @staticmethod
    def _extract_axis_value(line: str, axis: str) -> Optional[float]:
        match = re.search(rf"\b{axis}([-+]?\d*\.?\d+)", line, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _extract_feed_value(line: str) -> Optional[float]:
        match = re.search(r"\bF([-+]?\d*\.?\d+)", line, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _on_tx_line(self, line: str) -> None:
        self._telemetry_lines += 1
        self._telemetry_bytes += len(line)
        self._track_distance_mode(line)

        if self._sender_client:
            feed = self._extract_feed_value(line)
            if feed is not None:
                self._sender_client.current_feed = feed

        x_value = self._extract_axis_value(line, "X")
        if x_value is None:
            return

        if self._distance_mode == "G91":
            self._telemetry_distance_mm += abs(x_value)
        else:
            if self._telemetry_last_x_mm is not None:
                self._telemetry_distance_mm += abs(x_value - self._telemetry_last_x_mm)
            self._telemetry_last_x_mm = x_value

    def _jog(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> None:
        self._marker_laser_off()
        if self._current_state != "IDLE":
            return

        if not self._sender_client:
            return

        rounded_axes = {
            "X": round(dx, 1),
            "Y": round(dy, 1),
            "Z": round(dz, 1),
        }
        move_parts = [f"{axis}{value:.1f}" for axis, value in rounded_axes.items() if value != 0.0]
        if not move_parts:
            return

        self._sender_client.send_line("G91")
        self._track_distance_mode("G91")
        self._sender_client.send_line("G0 " + " ".join(move_parts))
        self._sender_client.send_line("G90")
        self._track_distance_mode("G90")

    def _send_terminal_command(self, _checked: bool = False) -> None:
        if self._current_state != "IDLE" or not self._sender_client:
            return

        terminal_command = self.sender_panel.terminal_input.text().strip()
        if not terminal_command:
            return

        self._log(f"> {terminal_command}")
        try:
            self._sender_client.send_line(terminal_command)
            self._track_distance_mode(terminal_command)
            self.sender_panel.terminal_input.clear()
        except Exception as exc:
            self._log(f"Terminal send failed: {exc}")

    def _send_read_settings_command(self, _checked: bool = False) -> None:
        self.sender_panel.terminal_input.setText("$$")
        self._send_terminal_command()

    def _send_home_command(self) -> None:
        self._marker_laser_off()
        self._update_estop_button_style()
        if self._current_state != "IDLE" or not self._sender_client:
            return
        self._log("> $H")
        try:
            self._sender_client.send_line("$H")
        except Exception as exc:
            self._log(f"Terminal send failed: {exc}")

    @staticmethod
    def _format_gcode_number(value: float, decimals: int = 3) -> str:
        formatted = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
        if formatted in {"", "-0"}:
            return "0"
        return formatted

    def _frame_values_ready(self) -> bool:
        return (
            self.sender_panel.frame_width.value() > 0.0
            and self.sender_panel.frame_height.value() > 0.0
            and self.sender_panel.frame_speed.value() > 0.0
            and 0.0 < self.sender_panel.frame_power.value() <= 2.0
        )

    def _frame_runtime_s_value(self) -> Optional[int]:
        if not self._sender_client:
            return None
        pwm_max = self._sender_client.grbl_pwm_max
        if pwm_max is None:
            return None
        runtime_percent = min(max(self.sender_panel.frame_power.value(), 0.0), 2.0)
        return int(round(pwm_max * runtime_percent / 100.0))

    def _finish_frame_run(self) -> None:
        if not self._frame_running:
            return
        self._frame_timer.stop()
        self._frame_running = False
        self._update_controls_for_state(self._current_state)

    def _update_frame_ui_state(self, _value: float = 0.0) -> None:
        inputs_enabled = self._current_state == "IDLE" and not self._frame_running
        self.sender_panel.frame_width.setEnabled(inputs_enabled)
        self.sender_panel.frame_height.setEnabled(inputs_enabled)
        self.sender_panel.frame_speed.setEnabled(inputs_enabled)
        self.sender_panel.frame_power.setEnabled(inputs_enabled)
        can_run = (
            self._is_connected
            and self._current_state == "IDLE"
            and not self._frame_running
            and not self._laser_stopped
            and self._frame_values_ready()
            and self._frame_runtime_s_value() is not None
        )
        self.sender_panel.btn_run_frame.setEnabled(can_run)

    def _run_frame(self) -> None:
        if self._frame_running:
            return
        if self._laser_stopped:
            self._log("Laser is STOPPED (E-STOP).")
            return
        if self._current_state != "IDLE":
            self._log("Frame is only available while IDLE.")
            return
        if not self._sender_client or not self._is_connected:
            return
        if not self._frame_values_ready():
            self._log("Frame requires width, height, speed, and marker power > 0.")
            return

        s_value = self._frame_runtime_s_value()
        if s_value is None:
            self._log("Frame PWM max ($30) unavailable; read GRBL settings first.")
            self._update_frame_ui_state()
            return

        width = self.sender_panel.frame_width.value()
        height = self.sender_panel.frame_height.value()
        speed = self.sender_panel.frame_speed.value()

        self._marker_laser_off()
        frame_duration_ms = max(
            1000,
            int(round((((2.0 * (width + height)) / speed) * 60.0 + 0.5) * 1000.0)),
        )
        self._frame_running = True
        self._frame_timer.start(frame_duration_ms)
        self._update_controls_for_state(self._current_state)
        sequence = [
            "G91",
            "M4",
            f"S{s_value}",
            f"F{self._format_gcode_number(speed, decimals=3)}",
            f"G1 X{self._format_gcode_number(width)}",
            f"G1 Y{self._format_gcode_number(height)}",
            f"G1 X-{self._format_gcode_number(width)}",
            f"G1 Y-{self._format_gcode_number(height)}",
            "M5",
            "G90",
        ]
        started = False
        try:
            for line in sequence:
                started = True
                self._sender_client.send_line(line)
                self._track_distance_mode(line)
        except Exception as exc:
            if started:
                for cleanup_line in ("M5", "G90"):
                    try:
                        self._sender_client.send_line(cleanup_line)
                        self._track_distance_mode(cleanup_line)
                    except Exception:
                        pass
            self._finish_frame_run()
            self._log(f"Run frame failed: {exc}")

    def _clear_marker_ui_active(self) -> None:
        self._marker_auto_off_timer.stop()
        if self._marker_active:
            self._marker_active = False
        self._update_marker_ui_state()
        self._update_estop_button_style()

    def _marker_percent_ready(self) -> bool:
        runtime_percent = min(max(self.sender_panel.marker_power.value(), 0.0), 2.0)
        return runtime_percent > 0.0

    def _marker_runtime_s_value(self) -> Optional[int]:
        pwm_max = self._marker_pwm_max
        if pwm_max is None:
            return None
        runtime_percent = min(max(self.sender_panel.marker_power.value(), 0.0), 2.0)
        if runtime_percent <= 0.0:
            return None
        return int(round(pwm_max * runtime_percent / 100.0))

    def _can_marker_turn_on(self) -> bool:
        return (
            self._is_connected
            and self._current_state == "IDLE"
            and not self._laser_stopped
            and self._marker_percent_ready()
            and self._marker_runtime_s_value() is not None
        )

    def _can_marker_turn_off(self) -> bool:
        return (
            self._is_connected
            and self._current_state == "IDLE"
            and self._sender_client is not None
        )

    def _update_marker_ui_state(self, _value: float = 0.0) -> None:
        self.sender_panel.marker_power.setEnabled(self._current_state == "IDLE")
        self.sender_panel.btn_marker_on.setEnabled(self._can_marker_turn_on())
        self.sender_panel.btn_marker_off.setEnabled(self._can_marker_turn_off())
        if self._marker_active:
            self.sender_panel.btn_marker_on.setStyleSheet("background-color: #dff3df;")
        else:
            self.sender_panel.btn_marker_on.setStyleSheet("")
        self._update_estop_button_style()

    def _marker_laser_on(self) -> None:
        if self._laser_stopped:
            self._log("Laser is STOPPED (E-STOP).")
            return
        if self._current_state != "IDLE":
            self._log("Marker laser is only available while IDLE.")
            return
        if not self._sender_client:
            return

        s_value = self._marker_runtime_s_value()
        if s_value is None:
            if not self._marker_percent_ready():
                self._log("Marker laser requires marker power > 0.")
            else:
                self._log("Marker PWM max ($30) unavailable; read GRBL settings first.")
            self._update_marker_ui_state()
            return

        started = False
        try:
            started = True
            self._sender_client.send_line(
                f"M3 G1 F{self._format_gcode_number(self._MARKER_FEED_MM_MIN, decimals=3)} S{s_value}"
            )
        except Exception as exc:
            if started:
                for cleanup_line in ("S0", "G0", "M5"):
                    try:
                        self._sender_client.send_line(cleanup_line)
                    except Exception:
                        pass
            self._marker_active = False
            self._update_marker_ui_state()
            self._log(f"Marker laser start failed: {exc}")
            return

        self._marker_auto_off_timer.start()
        self._marker_active = True
        self._update_marker_ui_state()

    def _marker_laser_off(self) -> None:
        self._marker_auto_off_timer.stop()
        if self._can_marker_turn_off():
            try:
                for line in ("S0", "G0", "M5"):
                    self._sender_client.send_line(line)
            except Exception as exc:
                self._log(f"Marker laser stop failed: {exc}")
        self._marker_active = False
        self._update_marker_ui_state()

    def _toggle_e_stop(self) -> None:
        if self._laser_stopped:
            self._laser_stopped = False
            self._update_laser_status_label()
            self._update_estop_button_style()
            self._log("E-STOP reset. Laser can be activated.")
            return

        self._stop_elapsed_tracking()
        if self._sender_client:
            try:
                self._sender_client.stop_stream()
            except Exception as exc:
                self._log(f"Stop failed: {exc}")
            if hasattr(self._sender_client, "send_realtime"):
                try:
                    self._sender_client.send_realtime("!")
                    self._sender_client.send_realtime("\x9e")
                except Exception:
                    pass
            try:
                self._sender_client.send_line("M5")
            except Exception as exc:
                self._log(f"Laser stop failed: {exc}")
        self._finish_frame_run()
        self._marker_laser_off()
        self._laser_stopped = True
        self._update_laser_status_label()
        self._update_estop_button_style()
        self._log("E-STOP engaged. Laser is not active.")

    def _update_laser_status_label(self) -> None:
        if self._laser_stopped:
            self._laser_status_label.setText(tr("LASER_DISABLED"))
            self._laser_status_label.setStyleSheet(
                "background-color: #eee; padding: 4px 8px; border-radius: 6px; font-weight: 600;"
            )
            return
        self._laser_status_label.setText(tr("LASER_ENABLED"))
        self._laser_status_label.setStyleSheet(
            "background-color: #dff3df; padding: 4px 8px; border-radius: 6px; font-weight: 600;"
        )

    def _compute_laser_firing(self) -> bool:
        if self._laser_stopped:
            return False
        return self._marker_active or self._current_state == "RUNNING"

    def _update_estop_button_style(self) -> None:
        if self._laser_stopped:
            self._laser_firing = False
            self._firing_pulse_on = False
            if self._firing_timer.isActive():
                self._firing_timer.stop()
            self._e_stop_btn.setStyleSheet(
                "QPushButton {"
                "background-color:#c00;"
                "border:6px solid #c00;"
                "border-radius:37px;"
                "color:white;"
                "font-weight:bold;"
                "}"
            )
            return

        self._laser_firing = self._compute_laser_firing()

        if self._laser_firing:
            self._firing_pulse_on = not self._firing_pulse_on
            core_alpha = "0.55" if self._firing_pulse_on else "0.33"
            core_stop = "50%" if self._firing_pulse_on else "42%"
            center_core = (
                "background-color: qradialgradient("
                "cx:0.5, cy:0.5, radius:0.5, "
                f"stop:0 rgba(0,120,255,{core_alpha}), "
                f"stop:{core_stop} rgba(0,120,255,{core_alpha}), "
                "stop:1 rgba(0,120,255,0));"
            )
        else:
            self._firing_pulse_on = False
            center_core = "background-color: transparent;"

        self._e_stop_btn.setStyleSheet(
            "QPushButton {"
            "background-color: transparent;"
            "color: white;"
            "font-weight: bold;"
            "border: 6px solid #c00;"
            "border-radius: 37px;"
            f"{center_core}"
            "}"
        )

        if self._laser_firing and not self._firing_timer.isActive():
            self._firing_timer.start()
        if not self._laser_firing and self._firing_timer.isActive():
            self._firing_timer.stop()

    def _update_telemetry(self) -> None:
        elapsed = time.monotonic() - self._telemetry_start
        if elapsed <= 0:
            return

        speed = (self._telemetry_distance_mm / elapsed) * 60
        lines_per_s = self._telemetry_lines / elapsed
        kb_per_s = (self._telemetry_bytes / elapsed) / 1024

        self._update_telemetry_labels(speed, lines_per_s, kb_per_s)

        now = time.monotonic()
        self._telemetry_lines = 0
        self._telemetry_bytes = 0
        self._telemetry_distance_mm = 0.0
        self._telemetry_start = now


    def _update_telemetry_labels(self, speed: float, lines_per_s: float, kb_per_s: float) -> None:
        feed = 0.0
        if self._sender_client:
            feed = self._sender_client.current_feed
        self._speed_label.setText(f"{tr('SPEED')}: {speed:.0f} / {feed:.0f} mm/min")
        self._tx_rate_label.setText(f"{tr('TX')}: {lines_per_s:.0f} {tr('LINES_PER_S')}")
        self._data_rate_label.setText(f"{tr('DATA')}: {kb_per_s:.1f} kB/s")

    def _ensure_sender_client(self) -> SenderClient:
        if self._sender_client:
            return self._sender_client

        client = SenderClient(self)
        client.progress_bytes.connect(self.sender_panel.set_progress_bytes)
        client.log_line.connect(self.sender_panel.append_log_line)
        client.state_changed.connect(self._update_controls_for_state)
        client.connection_changed.connect(self._on_connection_changed)
        client.grbl_setting_changed.connect(self._on_grbl_setting_changed)
        client.settings_cache_changed.connect(self._on_settings_cache_changed)
        client.tx_line.connect(self._on_tx_line)
        client.raw_position_changed.connect(self._on_raw_position_changed)
        client.start_worker()
        self._sender_client = client
        return client

    def _log(self, message: str) -> None:
        self.sender_panel.append_log_line(message)

    def _on_connection_changed(self, connected: bool) -> None:
        self._is_connected = connected
        if connected:
            self._refresh_connect_button_text()
            self._connect_btn.setStyleSheet("background-color: #dff3df;")
            self._status_poll_timer.start()
            if self._sender_client:
                try:
                    self._sender_client.request_status()
                except Exception:
                    pass
            self._update_marker_ui_state()
            self._update_frame_ui_state()
            return

        self._status_poll_timer.stop()
        self._finish_frame_run()
        self._pending_stream_start = None
        self.raw_machine_position_xyz = None
        self.machine_start_raw_xyz = None
        self.work_start_raw_xyz = None
        self._marker_pwm_max = None
        self._clear_marker_ui_active()
        self._refresh_connect_button_text()
        self._connect_btn.setStyleSheet("")
        self._refresh_position_block()
        self._update_marker_ui_state()
        self._update_frame_ui_state()

    def _format_connect_error(self, exc: Exception) -> str:
        if isinstance(exc, PermissionError):
            return tr("sender.error.com_port_in_use")
        return tr("sender.error.connect_failed").format(error=exc)

    def _update_controls_for_state(self, state: str) -> None:
        prev_state = self._current_state
        if prev_state == "IDLE" and state != "IDLE" and self._marker_active:
            self._marker_laser_off()
        self._current_state = state
        if state in {"ALARM", "ERROR"}:
            self._pending_stream_start = None
        self._status_label.setText(tr(state) if state in {"IDLE", "RUNNING", "HOLDING", "STOPPING", "ALARM", "ERROR"} else state)

        if state == "RUNNING":
            self._resume_elapsed_tracking()
        elif state == "HOLDING":
            self._pause_elapsed_tracking()
        else:
            self._stop_elapsed_tracking()

        if state == "ERROR":
            self._status_poll_timer.stop()
            self._clear_marker_ui_active()
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            self._pause_btn.setEnabled(False)
            self._resume_btn.setEnabled(False)
            self._connect_btn.setEnabled(True)
            self._refresh_connect_button_text()
            self._connect_btn.setStyleSheet("")
            self._load_file_btn.setEnabled(True)
            self._unlock_btn.setEnabled(False)
            self._unlock_btn.setStyleSheet("")
            self.sender_panel.jog_step.setEnabled(False)
            self.sender_panel.btn_x_plus.setEnabled(False)
            self.sender_panel.btn_x_minus.setEnabled(False)
            self.sender_panel.btn_y_plus.setEnabled(False)
            self.sender_panel.btn_y_minus.setEnabled(False)
            self.sender_panel.btn_z_plus.setEnabled(False)
            self.sender_panel.btn_z_minus.setEnabled(False)
            self.sender_panel.terminal_input.setEnabled(False)
            self.sender_panel.terminal_send_btn.setEnabled(False)
            self.sender_panel.btn_home.setEnabled(False)
            self.sender_panel.terminal_read_settings_btn.setEnabled(False)
            self.sender_panel.btn_set_machine_start.setEnabled(False)
            self.sender_panel.btn_move_to_machine_start.setEnabled(False)
            self.sender_panel.btn_clear_machine_start.setEnabled(
                self.machine_start_raw_xyz is not None
            )
            self.sender_panel.btn_set_work_start.setEnabled(False)
            self.sender_panel.btn_move_to_work_start.setEnabled(False)
            self.sender_panel.btn_clear_work_start.setEnabled(self.work_start_raw_xyz is not None)
            self._refresh_position_block()
            self._update_marker_ui_state()
            self._update_frame_ui_state()
            return

        running = state in {"RUNNING", "HOLDING", "STOPPING"}
        controls_running = running or self._frame_running
        if state in {"RUNNING", "HOLDING", "STOPPING"} and self._marker_active:
            self._clear_marker_ui_active()
        self._start_btn.setEnabled(
            not controls_running and state != "ALARM" and self._pending_stream_start is None
        )
        self._stop_btn.setEnabled(controls_running)
        self._pause_btn.setEnabled(state == "RUNNING")
        self._resume_btn.setEnabled(state == "HOLDING")
        self._connect_btn.setEnabled(not controls_running)
        self._load_file_btn.setEnabled(not controls_running)
        self._refresh_connect_button_text()

        self._unlock_btn.setEnabled(state in {"IDLE", "ALARM"})
        self._unlock_btn.setStyleSheet(
            "background-color: #fff3cd;" if state == "ALARM" else ""
        )

        if state == "ALARM" and prev_state != "ALARM":
            self._log("Controller is in ALARM. Click $X Unlock to continue.")

        jog_enabled = state == "IDLE" and not self._frame_running
        self.sender_panel.jog_step.setEnabled(jog_enabled)
        self.sender_panel.btn_x_plus.setEnabled(jog_enabled)
        self.sender_panel.btn_x_minus.setEnabled(jog_enabled)
        self.sender_panel.btn_y_plus.setEnabled(jog_enabled)
        self.sender_panel.btn_y_minus.setEnabled(jog_enabled)
        self.sender_panel.btn_z_plus.setEnabled(jog_enabled)
        self.sender_panel.btn_z_minus.setEnabled(jog_enabled)
        self.sender_panel.terminal_input.setEnabled(jog_enabled)
        self.sender_panel.terminal_send_btn.setEnabled(jog_enabled)
        self.sender_panel.btn_home.setEnabled(jog_enabled)
        self.sender_panel.terminal_read_settings_btn.setEnabled(jog_enabled)
        self.sender_panel.btn_set_machine_start.setEnabled(
            jog_enabled and self.raw_machine_position_xyz is not None
        )
        self.sender_panel.btn_move_to_machine_start.setEnabled(
            jog_enabled
            and self.raw_machine_position_xyz is not None
            and self.machine_start_raw_xyz is not None
        )
        self.sender_panel.btn_clear_machine_start.setEnabled(
            jog_enabled and self.machine_start_raw_xyz is not None
        )
        self.sender_panel.btn_set_work_start.setEnabled(
            jog_enabled and self.raw_machine_position_xyz is not None
        )
        self.sender_panel.btn_move_to_work_start.setEnabled(
            jog_enabled
            and self.raw_machine_position_xyz is not None
            and self.work_start_raw_xyz is not None
        )
        self.sender_panel.btn_clear_work_start.setEnabled(
            jog_enabled and self.work_start_raw_xyz is not None
        )
        self.sender_panel.btn_set_machine_start.setStyleSheet(
            "background-color: #dff3df;" if self.sender_panel.btn_set_machine_start.isEnabled() else ""
        )
        self.sender_panel.btn_set_work_start.setStyleSheet(
            "background-color: #dff3df;" if self.sender_panel.btn_set_work_start.isEnabled() else ""
        )
        if self._is_connected and state in {"IDLE", "ALARM"}:
            if not self._status_poll_timer.isActive():
                self._status_poll_timer.start()
        else:
            self._status_poll_timer.stop()
        self._refresh_position_block()
        self._update_marker_ui_state()
        self._update_estop_button_style()
        self._update_frame_ui_state()

    def _refresh_connect_button_text(self) -> None:
        if not self._is_connected:
            self._connect_btn.setText(tr("CONNECT_ACTION"))
            return
        if self._current_state == "IDLE" and not self._frame_running:
            self._connect_btn.setText(tr("DISCONNECT_ACTION"))
            return
        self._connect_btn.setText(tr("CONNECTED"))

    def _poll_raw_machine_position(self) -> None:
        if not self._is_connected or self._current_state not in {"IDLE", "ALARM"}:
            return
        if not self._sender_client:
            return
        try:
            self._sender_client.request_status()
        except Exception:
            pass

    def _on_raw_position_changed(
        self, position: Optional[tuple[float, float, float]]
    ) -> None:
        self.raw_machine_position_xyz = position
        self._refresh_position_block()
        self._maybe_start_pending_stream()

    def _on_grbl_setting_changed(self, key: int, _value: str) -> None:
        _ = key

    def _on_settings_cache_changed(self) -> None:
        if self._sender_client:
            self._marker_pwm_max = self._sender_client.grbl_pwm_max
        else:
            self._marker_pwm_max = None
        self._update_marker_ui_state()
        self._update_frame_ui_state()

    def _set_machine_start_from_current_position(self) -> None:
        if self.raw_machine_position_xyz is None:
            return
        self.machine_start_raw_xyz = self.raw_machine_position_xyz
        self._refresh_position_block()

    def _clear_machine_start(self) -> None:
        self.machine_start_raw_xyz = None
        self._refresh_position_block()

    def _set_work_start_from_current_position(self) -> None:
        if self.raw_machine_position_xyz is None:
            return
        self.work_start_raw_xyz = self.raw_machine_position_xyz
        self._refresh_position_block()

    def _clear_work_start(self) -> None:
        self.work_start_raw_xyz = None
        self._refresh_position_block()

    def _displayed_current_position(self) -> Optional[tuple[float, float, float]]:
        return self.raw_machine_position_xyz

    def _displayed_machine_start(self) -> Optional[tuple[float, float, float]]:
        return self.machine_start_raw_xyz

    def _displayed_work_start(self) -> Optional[tuple[float, float, float]]:
        return self.work_start_raw_xyz

    def _move_to_saved_raw_point(
        self, saved_point: Optional[tuple[float, float, float]]
    ) -> bool:
        if self._current_state != "IDLE" or not self._sender_client:
            return False
        if self.raw_machine_position_xyz is None or saved_point is None:
            return False

        deltas = tuple(
            saved - current
            for saved, current in zip(saved_point, self.raw_machine_position_xyz)
        )
        axis_names = ("X", "Y", "Z")
        move_parts = [
            f"{axis}{self._format_gcode_number(delta)}"
            for axis, delta in zip(axis_names, deltas)
            if abs(delta) >= 0.0005
        ]
        if not move_parts:
            return False

        self._marker_laser_off()
        self._sender_client.send_line("G91")
        self._track_distance_mode("G91")
        self._sender_client.send_line("G0 " + " ".join(move_parts))
        self._sender_client.send_line("G90")
        self._track_distance_mode("G90")
        return True

    def _maybe_start_pending_stream(self) -> None:
        pending = self._pending_stream_start
        if pending is None or self.raw_machine_position_xyz is None:
            return

        file_path, mode, target = pending
        if any(
            abs(target_axis - current_axis) >= 0.0005
            for target_axis, current_axis in zip(target, self.raw_machine_position_xyz)
        ):
            return

        self._pending_stream_start = None
        self._update_controls_for_state(self._current_state)
        try:
            self._start_stream_now(file_path, mode)
        except Exception as exc:
            self._log(
                self._format_connect_error(exc)
                if isinstance(exc, PermissionError)
                else f"Start failed: {exc}"
            )

    def _start_stream_now(self, file_path: str, mode: str) -> None:
        if not self._sender_client:
            return
        self._marker_laser_off()
        self._update_estop_button_style()
        self._sender_client.start_stream(file_path, mode=mode)
        self._elapsed_accum_s = 0.0
        self._elapsed_start_monotonic = time.monotonic()
        self._elapsed_timer.start()
        self._update_elapsed_time()
        self._update_estop_button_style()

    def _move_to_machine_start(self) -> None:
        self._move_to_saved_raw_point(self.machine_start_raw_xyz)

    def _move_to_work_start(self) -> None:
        self._move_to_saved_raw_point(self.work_start_raw_xyz)

    @staticmethod
    def _format_position_xyz(position: Optional[tuple[float, float, float]]) -> str:
        if position is None:
            return tr("POSITION_UNKNOWN")
        x, y, z = position
        return f"X{x:.2f} Y{y:.2f} Z{z:.2f}"

    def _refresh_position_block(self) -> None:
        current_display = self._displayed_current_position()
        machine_start_display = self._displayed_machine_start()
        work_start_display = self._displayed_work_start()
        self.sender_panel.update_position_block(
            self._format_position_xyz(current_display),
            tr("WORK_START_UNSET")
            if machine_start_display is None
            else self._format_position_xyz(machine_start_display),
            tr("WORK_START_UNSET")
            if work_start_display is None
            else self._format_position_xyz(work_start_display)
        )
        can_edit = self._current_state == "IDLE"
        self.sender_panel.btn_set_machine_start.setEnabled(
            can_edit and self.raw_machine_position_xyz is not None
        )
        self.sender_panel.btn_move_to_machine_start.setEnabled(
            can_edit
            and self.raw_machine_position_xyz is not None
            and self.machine_start_raw_xyz is not None
        )
        self.sender_panel.btn_clear_machine_start.setEnabled(
            can_edit and self.machine_start_raw_xyz is not None
        )
        self.sender_panel.btn_set_work_start.setEnabled(
            can_edit and self.raw_machine_position_xyz is not None
        )
        self.sender_panel.btn_move_to_work_start.setEnabled(
            can_edit
            and self.raw_machine_position_xyz is not None
            and self.work_start_raw_xyz is not None
        )
        self.sender_panel.btn_clear_work_start.setEnabled(
            can_edit and self.work_start_raw_xyz is not None
        )
        self.sender_panel.btn_set_machine_start.setStyleSheet(
            "background-color: #dff3df;" if self.sender_panel.btn_set_machine_start.isEnabled() else ""
        )
        self.sender_panel.btn_set_work_start.setStyleSheet(
            "background-color: #dff3df;" if self.sender_panel.btn_set_work_start.isEnabled() else ""
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._current_state in {"RUNNING", "HOLDING", "STOPPING"}:
            event.ignore()
            self.raise_()
            self.activateWindow()
            QMessageBox.warning(self, tr("APP_TITLE"), tr("CLOSE_WHILE_SENDING"))
            return

        try:
            self._stop_send()
            if self._firing_timer.isActive():
                self._firing_timer.stop()
            if self._sender_client:
                self._sender_client.shutdown()
        finally:
            self._sender_client = None
        super().closeEvent(event)
