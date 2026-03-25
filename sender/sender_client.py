from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


_SETTINGS_BOOTSTRAP_RETRY_DELAY_S = 0.25


class SenderClient(QObject):
    state_changed = pyqtSignal(str)
    progress_bytes = pyqtSignal(int, int)
    log_line = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)
    grbl_setting_changed = pyqtSignal(int, str)
    settings_cache_changed = pyqtSignal()
    tx_line = pyqtSignal(str)
    raw_position_changed = pyqtSignal(object)
    _settings_bootstrap_retry_schedule_requested = pyqtSignal()
    _settings_bootstrap_retry_cancel_requested = pyqtSignal()

    def __init__(self, parent=None, host: str = "127.0.0.1") -> None:
        super().__init__(parent)
        self._host = host
        self._ipc_port: Optional[int] = None
        self._process: Optional[subprocess.Popen[str]] = None
        self._socket: Optional[socket.socket] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_stop = threading.Event()
        self._reader_exit_emitted = False
        self._startup_thread: Optional[threading.Thread] = None
        self._startup_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._worker_ready = threading.Event()
        self._pending_commands: List[Dict[str, Any]] = []
        self._pending_lock = threading.Lock()
        self._max_pending_commands = 10
        self._queue_notice_emitted = False
        self._queue_drop_notice_emitted = False
        self._ipc_warn_last_emit = 0.0
        self._ipc_warn_interval_s = 1.0
        self._ipc_bad_frame_count = 0
        self._ipc_disconnect_emitted = False
        self._worker_exit_emitted = False
        self.current_feed: float = 0.0
        self._grbl_settings: Dict[int, str] = {}
        self._settings_bootstrap_requested = False
        self._settings_bootstrap_inflight = False
        self._settings_bootstrap_seen_setting = False
        self._settings_bootstrap_attempts = 0
        self._settings_bootstrap_retry_timer: Optional[QTimer] = None
        self.raw_machine_position_xyz: Optional[tuple[float, float, float]] = None
        self._settings_bootstrap_retry_schedule_requested.connect(
            self._start_settings_bootstrap_retry_timer
        )
        self._settings_bootstrap_retry_cancel_requested.connect(
            self._cancel_settings_bootstrap_retry_timer
        )

    def start_worker(self) -> None:
        with self._startup_lock:
            if self._socket:
                return
            if self._startup_thread and self._startup_thread.is_alive():
                return

            self._close_socket()
            self._stop_reader()
            self._ipc_port = self._pick_free_port()
            self._worker_ready.clear()
            self._clear_pending_commands()

            self.log_line.emit("Starting worker…")
            self._startup_thread = threading.Thread(target=self._start_worker_background, daemon=True)
            self._startup_thread.start()

    def _start_worker_background(self) -> None:
        process: Optional[subprocess.Popen[str]] = None
        try:
            if self._ipc_port is None:
                raise RuntimeError("IPC port not initialized")

            if getattr(sys, "frozen", False):
                worker_executable = (
                    Path(sys.executable).resolve().parent.parent / "SenderWorkerFree" / "SenderWorkerFree.exe"
                )
                cmd = [
                    str(worker_executable),
                    "--host",
                    self._host,
                    "--ipc-port",
                    str(self._ipc_port),
                ]
            else:
                cmd = [
                    sys.executable,
                    "-m",
                    "sender.sender_worker",
                    "--host",
                    self._host,
                    "--ipc-port",
                    str(self._ipc_port),
                ]
            if os.getenv("SENDER_MOCK", "0").strip() == "1":
                cmd.append("--mock-serial")

            env = os.environ.copy()
            env["SENDER_WORKER"] = "1"
            process = subprocess.Popen(
                cmd,
                text=True,
                env=env,
            )
            self._process = process
            self._connect_socket_with_retry()
            self._start_reader()
            self._worker_ready.set()
            self.log_line.emit("Worker IPC connected")
            self._flush_pending_commands()
        except Exception as exc:
            self._worker_ready.clear()
            dropped = self._clear_pending_commands()
            self.state_changed.emit("ERROR")
            self.log_line.emit(f"Worker start failed: {exc}")
            if dropped:
                self.log_line.emit(f"Dropped {dropped} queued command(s) due to startup failure.")
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
            self._process = None

    def connect_machine(self, port: str, baud: int) -> None:
        self._send_command({"cmd": "connect", "port": port, "baud": baud})

    def disconnect_machine(self) -> None:
        self._send_command({"cmd": "disconnect"})

    def start_stream(
        self,
        file_path: str,
        mode: str = "auto",
        profile: str = "auto",
        window_bytes: Optional[int] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "cmd": "start",
            "file": file_path,
            "mode": mode,
            "profile": profile,
        }
        if window_bytes is not None:
            payload["window_bytes"] = int(window_bytes)
        self._send_command(payload)

    def stop_stream(self) -> None:
        self._send_command({"cmd": "stop"})

    def pause_stream(self) -> None:
        self._send_command({"cmd": "pause"})

    def resume_stream(self) -> None:
        self._send_command({"cmd": "resume"})

    def send_realtime(self, value: str) -> None:
        self._send_command({"cmd": "realtime", "value": value})

    def send_line(self, value: str) -> None:
        self._send_command({"cmd": "line", "value": value})

    def request_status(self) -> None:
        self._send_command({"cmd": "status"})

    @property
    def grbl_pwm_max(self) -> Optional[float]:
        raw = self._grbl_settings.get(30)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def shutdown(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                self._send_payload({"cmd": "shutdown"})
            except Exception:
                pass

            deadline = time.monotonic() + 1.0
            while self._process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)

        self._worker_ready.clear()
        self._clear_pending_commands()
        self._clear_settings_cache()
        self._stop_reader()
        self._close_socket()

        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def _stop_reader(self) -> None:
        self._reader_stop.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None

    def _close_socket(self) -> None:
        with self._send_lock:
            if self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None

    def _pick_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((self._host, 0))
            return int(probe.getsockname()[1])

    def _connect_socket_with_retry(self) -> None:
        if self._ipc_port is None:
            raise RuntimeError("IPC port not initialized")

        deadline = time.monotonic() + 5.0
        last_exc: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection((self._host, self._ipc_port), timeout=0.5)
                sock.settimeout(0.5)
                self._socket = sock
                return
            except OSError as exc:
                last_exc = exc
                time.sleep(0.1)

        raise RuntimeError(f"Failed to connect to sender worker: {last_exc}")

    def _start_reader(self) -> None:
        self._reader_stop.clear()
        self._reader_exit_emitted = False
        self._ipc_disconnect_emitted = False
        self._worker_exit_emitted = False
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _emit_reader_exit_once(self, reason: str) -> None:
        if self._reader_exit_emitted:
            return
        self._reader_exit_emitted = True
        self.state_changed.emit("ERROR")
        self.log_line.emit(f"ERROR: Worker IPC closed: {reason}")

    def _emit_ipc_disconnect_once(self) -> None:
        if self._ipc_disconnect_emitted:
            return
        self._ipc_disconnect_emitted = True
        self.log_line.emit("ERROR: Worker disconnected (IPC closed)")
        self.state_changed.emit("ERROR")
        self.connection_changed.emit(False)

    def _emit_worker_exit_once(self) -> None:
        if self._worker_exit_emitted:
            return
        process = self._process
        if not process:
            return
        code = process.poll()
        if code is None:
            return
        self._worker_exit_emitted = True
        self.log_line.emit(f"ERROR: Worker process exited (code={code})")
        self.state_changed.emit("ERROR")

    def _reader_loop(self) -> None:
        sock = self._socket
        if not sock:
            return

        buffer = ""
        while not self._reader_stop.is_set():
            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                self._emit_worker_exit_once()
                continue
            except OSError:
                if not self._reader_stop.is_set():
                    self._emit_ipc_disconnect_once()
                break

            if not chunk:
                if not self._reader_stop.is_set():
                    self._emit_ipc_disconnect_once()
                break

            buffer += chunk.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                raw, buffer = buffer.split("\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    self._ipc_bad_frame_count += 1
                    now = time.monotonic()
                    if now - self._ipc_warn_last_emit >= self._ipc_warn_interval_s:
                        self.log_line.emit(
                            f"WARN: Invalid IPC frame (json decode). count={self._ipc_bad_frame_count}"
                        )
                        self._ipc_warn_last_emit = now
                    continue
                self._dispatch_event(payload)

        self._worker_ready.clear()
        self._close_socket()
        self._emit_worker_exit_once()

    def _dispatch_event(self, payload: Dict[str, Any]) -> None:
        event_type = payload.get("type")
        if event_type == "state":
            self.state_changed.emit(str(payload.get("state", "UNKNOWN")))
            return

        if event_type == "progress":
            sent = int(payload.get("sent_bytes", 0))
            total = int(payload.get("total_bytes", 0))
            self.progress_bytes.emit(sent, total)
            return

        if event_type == "debug":
            direction = str(payload.get("direction", ""))
            line = str(payload.get("line", ""))
            self.log_line.emit(f"{direction}: {line}")
            return

        if event_type in {"error", "alarm"}:
            message = str(payload.get("message", ""))
            self.log_line.emit(f"{event_type.upper()}: {message}")
            return

        if event_type == "log":
            message = str(payload.get("message", ""))
            self._handle_settings_bootstrap_log(message)
            self.log_line.emit(message)
            return

        if event_type == "grbl_setting":
            try:
                key = int(payload.get("key"))
            except (TypeError, ValueError):
                return
            value = str(payload.get("value", "")).strip()
            self._grbl_settings[key] = value
            self._settings_bootstrap_seen_setting = True
            self._settings_bootstrap_inflight = False
            self._cancel_settings_bootstrap_retry()
            self.grbl_setting_changed.emit(key, value)
            self.settings_cache_changed.emit()
            return

        if event_type == "connection":
            connected = bool(payload.get("connected", False))
            if connected:
                self._clear_settings_cache()
                self._request_settings_bootstrap()
            else:
                self._clear_settings_cache()
                self.raw_machine_position_xyz = None
                self.raw_position_changed.emit(None)
            self.connection_changed.emit(connected)
            return

        if event_type == "tx_line":
            line = str(payload.get("line", ""))
            self.tx_line.emit(line)
            return

        if event_type == "raw_position":
            try:
                x = float(payload.get("x"))
                y = float(payload.get("y"))
                z = float(payload.get("z"))
            except (TypeError, ValueError):
                return
            position = (x, y, z)
            self.raw_machine_position_xyz = position
            self.raw_position_changed.emit(position)

    def _send_command(self, payload: Dict[str, Any]) -> None:
        if not self._worker_ready.is_set():
            with self._pending_lock:
                queued_payload = dict(payload)
                is_critical = self._is_critical_command(queued_payload)

                if len(self._pending_commands) >= self._max_pending_commands:
                    if is_critical:
                        dropped = self._drop_oldest_non_critical_or_oldest()
                        if dropped and self._is_critical_command(dropped) and not self._queue_drop_notice_emitted:
                            self._queue_drop_notice_emitted = True
                            self.log_line.emit(
                                f"Pending queue full; dropped oldest critical command: {dropped.get('cmd', '')}"
                            )
                    else:
                        return

                if is_critical:
                    self._pending_commands.insert(0, queued_payload)
                else:
                    self._pending_commands.append(queued_payload)

                if not self._queue_notice_emitted:
                    self._queue_notice_emitted = True
                    self.log_line.emit("Queueing command until worker is ready…")
            return

        self._send_payload(payload)

    def _send_payload(self, payload: Dict[str, Any]) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self._send_lock:
            sock = self._socket
            if not sock:
                raise RuntimeError("Sender worker socket is not connected")

            try:
                sock.sendall(data)
            except socket.timeout as exc:
                raise RuntimeError(f"IPC send timeout: {exc}") from exc
            except OSError as exc:
                raise RuntimeError(f"IPC send failed: {exc}") from exc

    def _flush_pending_commands(self) -> None:
        with self._pending_lock:
            queued = list(self._pending_commands)
            self._pending_commands.clear()
            self._queue_notice_emitted = False

        sent_count = 0
        remaining: List[Dict[str, Any]] = []
        failure: Optional[Exception] = None

        for idx, payload in enumerate(queued):
            try:
                self._send_payload(payload)
                sent_count += 1
            except Exception as exc:
                failure = exc
                remaining = queued[idx:]
                break

        if failure is not None:
            with self._pending_lock:
                self._pending_commands = remaining + self._pending_commands
            self.log_line.emit(f"Failed sending queued command: {failure}")
            if remaining:
                self.log_line.emit(f"{len(remaining)} queued command(s) requeued due to send failure.")

        if sent_count:
            self.log_line.emit(f"Flushed {sent_count} queued command(s).")

    def _clear_pending_commands(self) -> int:
        with self._pending_lock:
            dropped = len(self._pending_commands)
            self._pending_commands.clear()
            self._queue_notice_emitted = False
            self._queue_drop_notice_emitted = False
            return dropped

    @staticmethod
    def _is_critical_command(payload: Dict[str, Any]) -> bool:
        return str(payload.get("cmd", "")) in {"stop", "shutdown", "realtime"}

    def _drop_oldest_non_critical_or_oldest(self) -> Optional[Dict[str, Any]]:
        for idx, queued in enumerate(self._pending_commands):
            if not self._is_critical_command(queued):
                return self._pending_commands.pop(idx)
        if self._pending_commands:
            return self._pending_commands.pop(-1)
        return None

    def _clear_settings_cache(self) -> None:
        had_settings = bool(self._grbl_settings)
        self._grbl_settings.clear()
        self._settings_bootstrap_requested = False
        self._settings_bootstrap_inflight = False
        self._settings_bootstrap_seen_setting = False
        self._settings_bootstrap_attempts = 0
        self._cancel_settings_bootstrap_retry()
        if had_settings:
            self.settings_cache_changed.emit()

    def _request_settings_bootstrap(self) -> None:
        if self._settings_bootstrap_requested or not self._worker_ready.is_set():
            return
        self._settings_bootstrap_requested = True
        self._issue_settings_bootstrap_request()

    def _issue_settings_bootstrap_request(self) -> None:
        if not self._worker_ready.is_set():
            return
        self._settings_bootstrap_attempts += 1
        self._settings_bootstrap_inflight = True
        self._cancel_settings_bootstrap_retry()
        self.send_line("$$")

    def _handle_settings_bootstrap_log(self, message: str) -> None:
        if not self._settings_bootstrap_inflight:
            return
        if message.strip().lower() != "ok":
            return
        self._settings_bootstrap_inflight = False
        if self._settings_bootstrap_seen_setting:
            return
        if self._settings_bootstrap_attempts >= 2:
            return
        self.log_line.emit("Automatic settings bootstrap returned no GRBL settings; retrying $$ once.")
        self._settings_bootstrap_retry_schedule_requested.emit()

    def _retry_settings_bootstrap_once(self) -> None:
        if self._settings_bootstrap_seen_setting or not self._settings_bootstrap_requested:
            return
        self._issue_settings_bootstrap_request()

    def _cancel_settings_bootstrap_retry(self) -> None:
        self._settings_bootstrap_retry_cancel_requested.emit()

    def _start_settings_bootstrap_retry_timer(self) -> None:
        self._cancel_settings_bootstrap_retry_timer()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(int(_SETTINGS_BOOTSTRAP_RETRY_DELAY_S * 1000))
        timer.timeout.connect(self._on_settings_bootstrap_retry_timeout)
        self._settings_bootstrap_retry_timer = timer
        timer.start()

    def _on_settings_bootstrap_retry_timeout(self) -> None:
        timer = self._settings_bootstrap_retry_timer
        self._settings_bootstrap_retry_timer = None
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._retry_settings_bootstrap_once()

    def _cancel_settings_bootstrap_retry_timer(self) -> None:
        timer = self._settings_bootstrap_retry_timer
        self._settings_bootstrap_retry_timer = None
        if timer is not None:
            timer.stop()
            timer.deleteLater()
