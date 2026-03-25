from __future__ import annotations

from collections import deque
import time
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDoubleSpinBox
from PyQt6.QtWidgets import QGridLayout
from PyQt6.QtWidgets import QGroupBox
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QPlainTextEdit
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QProgressBar
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget

from sender.lang import tr


class SenderPanel(QWidget):
    def __init__(
        self,
        parent=None,
        max_log_lines: int = 5000,
        log_update_hz: float = 8.0,
    ) -> None:
        super().__init__(parent)

        self._log_buffer: deque[str] = deque(maxlen=max(1, max_log_lines))
        self._log_dirty = False
        self._last_log_line = ""
        self._last_log_ts = 0.0
        self._duplicate_log_window_s = 0.25

        self.progress_widget = QWidget()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar {border: 1px solid #888; border-radius: 4px; background: #1f1f1f;}"
            "QProgressBar::chunk {background-color: #2dbb55;}"
        )

        self.percent_label = QLabel("0.0%")

        progress_row = QHBoxLayout(self.progress_widget)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.percent_label)

        self.jog_box = QGroupBox()
        jog_box = self.jog_box
        jog_layout = QGridLayout(jog_box)

        self.jog_step = QDoubleSpinBox()
        self.jog_step.setDecimals(1)
        self.jog_step.setRange(0.1, 1000.0)
        self.jog_step.setSingleStep(0.1)
        self.jog_step.setValue(10.0)
        self.jog_step.setSuffix(" mm")

        self.marker_power = QDoubleSpinBox()
        self.marker_power.setDecimals(2)
        self.marker_power.setRange(0.0, 2.0)
        self.marker_power.setSingleStep(0.25)
        self.marker_power.setValue(0.25)
        self.marker_power.setSuffix(" %")

        self.btn_marker_on = QPushButton()
        self.btn_marker_off = QPushButton()

        self._marker_label = QLabel()
        jog_layout.addWidget(self._marker_label, 0, 0)
        jog_layout.addWidget(self.marker_power, 0, 1)
        jog_layout.addWidget(self.btn_marker_on, 0, 2)
        jog_layout.addWidget(self.btn_marker_off, 0, 3)

        self._step_label = QLabel()
        jog_layout.addWidget(self._step_label, 1, 0)
        jog_layout.addWidget(self.jog_step, 1, 1, 1, 3)

        self.btn_x_minus = QPushButton("X-")
        self.btn_x_plus = QPushButton("X+")
        self.btn_y_minus = QPushButton("Y-")
        self.btn_y_plus = QPushButton("Y+")
        self.btn_z_minus = QPushButton("Z-")
        self.btn_z_plus = QPushButton("Z+")
        self.btn_home = QPushButton()

        jog_layout.addWidget(self.btn_y_plus, 2, 1)
        jog_layout.addWidget(self.btn_x_minus, 3, 0)
        jog_layout.addWidget(self.btn_home, 3, 1)
        jog_layout.addWidget(self.btn_x_plus, 3, 2)
        jog_layout.addWidget(self.btn_y_minus, 4, 1)
        jog_layout.addWidget(self.btn_z_plus, 2, 3)
        jog_layout.addWidget(self.btn_z_minus, 4, 3)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("")

        self.terminal_box = QGroupBox()
        terminal_box = self.terminal_box
        terminal_layout = QHBoxLayout(terminal_box)
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("")
        self.terminal_send_btn = QPushButton()
        self.terminal_read_settings_btn = QPushButton()

        terminal_layout.addWidget(self.terminal_input, 1)
        terminal_layout.addWidget(self.terminal_send_btn)
        terminal_layout.addWidget(self.terminal_read_settings_btn)

        self.position_box = QGroupBox()
        position_box = self.position_box
        position_layout = QGridLayout(position_box)
        self._current_position_title = QLabel()
        self._current_position_value = QLabel()
        self._machine_start_title = QLabel()
        self._machine_start_value = QLabel()
        self._work_start_title = QLabel()
        self._work_start_value = QLabel()
        self.btn_set_machine_start = QPushButton()
        self.btn_move_to_machine_start = QPushButton()
        self.btn_clear_machine_start = QPushButton()
        self.btn_set_work_start = QPushButton()
        self.btn_move_to_work_start = QPushButton()
        self.btn_clear_work_start = QPushButton()

        self._current_position_value.setStyleSheet("font-family: monospace;")
        self._machine_start_value.setStyleSheet("font-family: monospace;")
        self._work_start_value.setStyleSheet("font-family: monospace;")

        position_layout.addWidget(self._current_position_title, 0, 0)
        position_layout.addWidget(self._current_position_value, 0, 1)
        position_layout.addWidget(self._machine_start_title, 1, 0)
        position_layout.addWidget(self._machine_start_value, 1, 1)
        position_layout.addWidget(self.btn_set_machine_start, 2, 0, 1, 2)
        position_layout.addWidget(self.btn_move_to_machine_start, 3, 0, 1, 2)
        position_layout.addWidget(self.btn_clear_machine_start, 4, 0, 1, 2)
        position_layout.addWidget(self._work_start_title, 5, 0)
        position_layout.addWidget(self._work_start_value, 5, 1)
        position_layout.addWidget(self.btn_set_work_start, 6, 0, 1, 2)
        position_layout.addWidget(self.btn_move_to_work_start, 7, 0, 1, 2)
        position_layout.addWidget(self.btn_clear_work_start, 8, 0, 1, 2)

        self.frame_box = QGroupBox()
        frame_box = self.frame_box
        frame_layout = QGridLayout(frame_box)
        self._frame_width_label = QLabel()
        self.frame_width = QDoubleSpinBox()
        self.frame_width.setDecimals(2)
        self.frame_width.setRange(0.0, 1000.0)
        self.frame_width.setSingleStep(0.1)
        self.frame_width.setValue(0.0)
        self.frame_width.setSuffix(" mm")
        self._frame_height_label = QLabel()
        self.frame_height = QDoubleSpinBox()
        self.frame_height.setDecimals(2)
        self.frame_height.setRange(0.0, 1000.0)
        self.frame_height.setSingleStep(0.1)
        self.frame_height.setValue(0.0)
        self.frame_height.setSuffix(" mm")
        self._frame_speed_label = QLabel()
        self.frame_speed = QDoubleSpinBox()
        self.frame_speed.setDecimals(1)
        self.frame_speed.setRange(0.0, 1_000_000.0)
        self.frame_speed.setSingleStep(10.0)
        self.frame_speed.setValue(0.0)
        self.frame_speed.setSuffix(" mm/min")
        self._frame_power_label = QLabel()
        self.frame_power = QDoubleSpinBox()
        self.frame_power.setDecimals(2)
        self.frame_power.setRange(0.0, 2.0)
        self.frame_power.setSingleStep(0.1)
        self.frame_power.setValue(0.0)
        self.frame_power.setSuffix(" %")
        self._frame_helper_label = QLabel()
        self._frame_helper_label.setWordWrap(True)
        self.btn_run_frame = QPushButton()

        frame_layout.addWidget(self._frame_width_label, 0, 0)
        frame_layout.addWidget(self.frame_width, 0, 1)
        frame_layout.addWidget(self._frame_height_label, 1, 0)
        frame_layout.addWidget(self.frame_height, 1, 1)
        frame_layout.addWidget(self._frame_speed_label, 2, 0)
        frame_layout.addWidget(self.frame_speed, 2, 1)
        frame_layout.addWidget(self._frame_power_label, 3, 0)
        frame_layout.addWidget(self.frame_power, 3, 1)
        frame_layout.addWidget(self._frame_helper_label, 4, 0, 1, 2)
        frame_layout.addWidget(self.btn_run_frame, 5, 0, 1, 2)

        self._log_update_timer = QTimer(self)
        self._log_update_timer.timeout.connect(self._flush_log_buffer)
        interval_ms = max(100, int(1000.0 / max(log_update_hz, 0.1)))
        self._log_update_timer.start(interval_ms)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.jog_box.setTitle(tr("JOG_GROUP"))
        self._marker_label.setText(tr("MARKER_PERCENT"))
        self._step_label.setText(tr("STEP"))
        self.btn_marker_on.setText(tr("LASER_ON"))
        self.btn_marker_off.setText(tr("LASER_OFF"))
        self.btn_home.setText(tr("HOME"))
        self.btn_home.setToolTip(tr("HOME_TOOLTIP"))
        self.log_view.setPlaceholderText(tr("LOG_PLACEHOLDER"))
        self.terminal_box.setTitle(tr("TERMINAL_GROUP"))
        self.terminal_input.setPlaceholderText(tr("TERMINAL_PLACEHOLDER"))
        self.terminal_send_btn.setText(tr("SEND"))
        self.terminal_read_settings_btn.setText(tr("READ_SETTINGS"))
        self.frame_box.setTitle(tr("FRAME_GROUP"))
        self._frame_width_label.setText(tr("FRAME_WIDTH"))
        self._frame_height_label.setText(tr("FRAME_HEIGHT"))
        self._frame_speed_label.setText(tr("FRAME_SPEED"))
        self._frame_power_label.setText(tr("FRAME_MARKER_POWER"))
        self._frame_helper_label.setText(tr("FRAME_HELPER"))
        self.btn_run_frame.setText(tr("RUN_FRAME"))
        self.position_box.setTitle(tr("POSITION_GROUP"))
        self._current_position_title.setText(tr("CURRENT_POSITION"))
        self._machine_start_title.setText(tr("MACHINE_START"))
        self.btn_set_machine_start.setText(tr("SET_MACHINE_START"))
        self.btn_move_to_machine_start.setText(tr("MOVE_TO_MACHINE_START"))
        self.btn_clear_machine_start.setText(tr("CLEAR_MACHINE_START"))
        self._work_start_title.setText(tr("WORK_START"))
        self.btn_set_work_start.setText(tr("SET_WORK_START"))
        self.btn_move_to_work_start.setText(tr("MOVE_TO_WORK_START"))
        self.btn_clear_work_start.setText(tr("CLEAR_WORK_START"))

    def set_progress_bytes(self, sent: int, total: int) -> None:
        safe_total = max(total, 1)
        ratio = max(0.0, min(1.0, sent / safe_total))
        self.progress.setValue(int(ratio * 1000))
        self.percent_label.setText(f"{ratio * 100:.1f}%")

    def update_position_block(
        self,
        current_position_text: str,
        machine_start_text: str,
        work_start_text: str,
    ) -> None:
        self._current_position_value.setText(current_position_text)
        self._machine_start_value.setText(machine_start_text)
        self._work_start_value.setText(work_start_text)

    def append_log_line(self, text: str) -> None:
        if text == "RX: ok":
            return

        self._append_to_log_buffer(text)

    def _append_to_log_buffer(self, text: str) -> None:
        now = time.monotonic()
        if text == self._last_log_line and (now - self._last_log_ts) < self._duplicate_log_window_s:
            return
        self._last_log_line = text
        self._last_log_ts = now
        self._log_buffer.append(text)
        self._log_dirty = True

    def _flush_log_buffer(self) -> None:
        if not self._log_dirty:
            return
        self.log_view.setPlainText("\n".join(self._log_buffer))
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)
        self._log_dirty = False
