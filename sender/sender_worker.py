from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional

from sender.lang import tr
from sender.protocol import GenericProtocol
from sender.transport_fake import FakeSerialTransport


class WorkerState:
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    HOLDING = "HOLDING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    ALARM = "ALARM"


class AckResult:
    ACK = "ack"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class StreamSettings:
    mode: str
    profile: str
    window_bytes: int
    window_lines: int


class StreamPolicy:
    def stream(self, worker: "SenderWorkerServer", file_path: Path) -> bool:
        raise NotImplementedError


class LineAckPolicy(StreamPolicy):
    def __init__(self, max_inflight: int = 64) -> None:
        self._max_inflight = max(1, max_inflight)

    def stream(self, worker: "SenderWorkerServer", file_path: Path) -> bool:
        inflight = 0
        pending_raw_bytes: Deque[int] = deque()

        with file_path.open("rb") as handle:
            eof = False

            while True:
                if worker.should_stop():
                    return True

                # refill window
                while not eof and not worker.should_pause() and inflight < self._max_inflight:
                    raw_line = handle.readline()
                    if raw_line == b"":
                        eof = True
                        break

                    raw_bytes = len(raw_line)
                    line = raw_line.decode("utf-8", errors="ignore").strip()

                    if not line or line.startswith(";"):
                        worker.on_line_complete(raw_bytes)
                        continue

                    worker.transport_send_line(line)
                    pending_raw_bytes.append(raw_bytes)
                    inflight += 1

                if eof and inflight == 0:
                    return True

                if inflight == 0:
                    if worker.should_pause() or worker._get_state() == WorkerState.HOLDING:
                        time.sleep(0.002)
                        continue

                ack = worker.wait_for_ack_or_error()
                if ack == AckResult.STOPPED:
                    return True
                if ack != AckResult.ACK:
                    return False

                if pending_raw_bytes:
                    raw_bytes = pending_raw_bytes.popleft()
                    worker.on_line_complete(raw_bytes)
                    inflight -= 1


class ByteWindowPolicy(StreamPolicy):
    def __init__(self, window_bytes: int, window_lines: int) -> None:
        self._window_bytes = max(1, window_bytes)
        self._window_lines = max(1, window_lines)

    def stream(self, worker: "SenderWorkerServer", file_path: Path) -> bool:
        inflight_bytes = 0
        inflight_lines = 0
        sent_costs: Deque[tuple[int, int]] = deque()
        skip_refill_once = False

        with file_path.open("rb") as handle:
            eof = False
            while True:
                if worker.should_stop():
                    inflight_bytes = 0
                    inflight_lines = 0
                    sent_costs.clear()
                    return True

                block_refill_once = skip_refill_once
                skip_refill_once = False

                while (
                    not eof
                    and not worker.should_pause()
                    and not block_refill_once
                    and inflight_bytes < self._window_bytes
                    and inflight_lines < self._window_lines
                ):
                    line_start = handle.tell()
                    raw_line = handle.readline()
                    if raw_line == b"":
                        eof = True
                        break

                    raw_bytes = len(raw_line)
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or line.startswith(";"):
                        worker.on_line_complete(raw_bytes)
                        continue

                    cost_bytes = worker.payload_cost_bytes(line)
                    if inflight_bytes + cost_bytes > self._window_bytes:
                        handle.seek(line_start)
                        break

                    worker.transport_send_line(line)
                    sent_costs.append((cost_bytes, raw_bytes))
                    inflight_bytes += cost_bytes
                    inflight_lines += 1

                if eof and inflight_lines == 0:
                    return True

                if inflight_lines == 0:
                    if worker.should_pause() or worker._get_state() == WorkerState.HOLDING:
                        time.sleep(0.002)
                    continue

                ack = worker.wait_for_ack_or_error()
                if ack == AckResult.STOPPED:
                    inflight_bytes = 0
                    inflight_lines = 0
                    sent_costs.clear()
                    return True
                if ack != AckResult.ACK:
                    return False

                if sent_costs:
                    cost_bytes, raw_bytes = sent_costs.popleft()
                    inflight_bytes = max(0, inflight_bytes - cost_bytes)
                    inflight_lines = max(0, inflight_lines - 1)
                    worker.on_line_complete(raw_bytes)
                    continue

                worker.on_fifo_empty_ack()
                skip_refill_once = True

        return True


class SenderWorkerServer:
    # Larger streaming windows significantly improve raster engraving performance.
    # Raster G-code can contain millions of short motion segments, and small
    # windows force frequent refill cycles with excessive ACK handling overhead.
    #
    # Increasing the window helps keep the GRBL planner continuously fed,
    # improving throughput while preserving protocol semantics.
    _PROFILE_WINDOWS: Dict[str, tuple[int, int]] = {
        "grbl": (256, 128),
        "grblhal": (4096, 1024),
    }
    _TERMINAL_RX_TIMEOUT_S = 0.25
    _TERMINAL_RX_MAX_LINES = 200
    _TERMINAL_RX_IDLE_GAP_LIMIT = 4
    _GRBL_SETTING_RE = re.compile(r"^\s*\$(\d+)\s*=\s*(.+?)\s*$")
    _STATUS_POLL_TIMEOUT_S = 0.15
    _STATUS_POLL_MAX_LINES = 8
    _MPOS_RE = re.compile(
        r"MPos:([-+]?\d*\.?\d+),([-+]?\d*\.?\d+),([-+]?\d*\.?\d+)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        host: str,
        ipc_port: int,
        ack_timeout_s: float = 15.0,
        debug_ok_agg: bool = False,
        transport_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._host = host
        self._ipc_port = ipc_port
        self._ack_timeout_s = ack_timeout_s

        self._state = WorkerState.IDLE
        self._state_lock = threading.Lock()
        self._protocol = GenericProtocol()
        self._transport: Optional[Any] = None
        self._transport_factory = transport_factory
        self._debug_ok_agg = debug_ok_agg

        self._stream_thread: Optional[threading.Thread] = None
        self._stop_requested = threading.Event()
        self._shutdown_requested = threading.Event()
        self._pause_requested = threading.Event()

        self._total_bytes = 0
        self._sent_bytes = 0
        self._last_progress_emit = 0.0
        self._progress_interval_s = 0.1

        self._last_debug_emit = 0.0
        self._debug_interval_s = 1.0
        self._last_fifo_empty_ack_warn = 0.0
        self._fifo_empty_ack_warn_interval_s = 1.0
        self._ok_count = 0
        self._last_ok_agg_emit = 0.0
        self._join_timeout_emitted = False
        self._set_error_latched(False)
        self._firmware_alarm = False

        self._client_lock = threading.Lock()
        self._client: Optional[socket.socket] = None

        self._detected_profile = "grbl"
        self._profile_probe_done = False
        self._grbl_validated = False
        self._connected_emitted = False
        self._connected_port: Optional[str] = None
        self._connected_baud: Optional[int] = None

    def _reset_stream_state(self, clear_transport_buffers: bool = False) -> None:
        self._sent_bytes = 0
        self._total_bytes = 0
        self._pause_requested.clear()
        self._stop_requested.clear()
        self._ok_count = 0
        self._last_ok_agg_emit = 0.0
        self._join_timeout_emitted = False
        self._set_error_latched(False)

        if clear_transport_buffers and self._transport:
            if hasattr(self._transport, "clear_tx_queue"):
                try:
                    self._transport.clear_tx_queue()
                except Exception:
                    pass
            if hasattr(self._transport, "clear_io_buffers"):
                try:
                    self._transport.clear_io_buffers()
                except Exception:
                    pass

        self._emit_progress(force=True)

    def serve_forever(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((self._host, self._ipc_port))
                server.listen(1)
                server.settimeout(0.5)

                while not self._shutdown_requested.is_set():
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        continue

                    with conn:
                        conn.settimeout(0.5)
                        with self._client_lock:
                            self._client = conn
                        self._send_event({"type": "state", "state": self._get_state()})
                        self._send_event(
                            {
                                "type": "progress",
                                "sent_bytes": self._sent_bytes,
                                "total_bytes": self._total_bytes,
                            }
                        )
                        self._handle_client(conn)
                        with self._client_lock:
                            self._client = None
        finally:
            self._cleanup_transport()

    def _handle_client(self, conn: socket.socket) -> None:
        buffer = ""
        while not self._shutdown_requested.is_set():
            try:
                chunk = conn.recv(8192)
            except socket.timeout:
                continue
            except OSError:
                break

            if not chunk:
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
                    self._send_event({"type": "error", "message": "Invalid JSON command"})
                    continue

                try:
                    self._handle_command(payload)
                except Exception as exc:
                    self._send_event({"type": "error", "message": f"Command handling failed: {exc}"})

    def _handle_command(self, payload: Dict[str, Any]) -> None:
        cmd = str(payload.get("cmd", "")).strip().lower()
        if cmd == "connect":
            self._cmd_connect(payload)
            return
        if cmd == "disconnect":
            self._cmd_disconnect()
            return
        if cmd == "start":
            self._cmd_start(payload)
            return
        if cmd == "stop":
            self._cmd_stop()
            return
        if cmd == "pause":
            self._cmd_pause()
            return
        if cmd == "resume":
            self._cmd_resume()
            return
        if cmd == "realtime":
            self._cmd_realtime(payload)
            return
        if cmd == "line":
            self._cmd_line(payload)
            return
        if cmd == "status":
            self._cmd_status()
            return
        if cmd == "shutdown":
            self._cmd_shutdown()
            return

        self._send_event({"type": "error", "message": f"Unknown command: {cmd}"})

    def _cmd_connect(self, payload: Dict[str, Any]) -> None:
        if self._get_state() == WorkerState.RUNNING:
            self._send_event({"type": "error", "message": "Cannot connect while RUNNING"})
            return

        port = str(payload.get("port", "")).strip()
        try:
            baud = int(payload.get("baud", 115200))
        except (TypeError, ValueError):
            self._send_event({"type": "error", "message": "Invalid baud value"})
            return
        if not port:
            self._send_event({"type": "error", "message": "Missing serial port"})
            return
        if self._transport_factory is None:
            self._send_event({"type": "error", "message": "Transport factory unavailable"})
            self._set_state(WorkerState.ERROR)
            return

        if (
            self._transport
            and self._transport.is_connected()
            and self._grbl_validated
            and self._connected_port == port
            and self._connected_baud == baud
            and self._get_state() in {WorkerState.IDLE, WorkerState.ALARM}
        ):
            return

        self._cleanup_transport()
        self._profile_probe_done = False
        self._detected_profile = "grbl"
        self._grbl_validated = False
        self._transport = self._transport_factory(
            port=port,
            baudrate=baud,
            timeout=0.1,
            dtr_toggle=True,
            rtscts=False,
            xonxoff=False,
            max_tx_queue=10000,
        )

        try:
            self._transport.connect()
            if not self._detect_profile_once():
                raise RuntimeError("No GRBL response detected")
            self._grbl_validated = True
        except Exception as exc:
            self._grbl_validated = False
            self._close_transport()
            self._set_state(WorkerState.ERROR)
            self._emit_connection_state(False)
            if isinstance(exc, PermissionError):
                self._emit_error_once(
                    tr("sender.error.com_port_in_use")
                )
            else:
                self._emit_error_once(tr("sender.error.connect_failed").format(error=exc))
            return

        self._connected_port = port
        self._connected_baud = baud
        self._set_state(WorkerState.IDLE)
        self._emit_connection_state(True)
        self._send_event({"type": "log", "message": f"Connected on {port} @ {baud} baud."})

    def _cmd_disconnect(self) -> None:
        if self._get_state() != WorkerState.IDLE:
            return
        if not self._transport or not self._transport.is_connected():
            return
        self._cleanup_transport()
        self._set_state(WorkerState.IDLE)

    def _cmd_start(self, payload: Dict[str, Any]) -> None:
        if self._get_state() == WorkerState.RUNNING:
            self._send_event({"type": "error", "message": "Streaming already RUNNING"})
            return

        if self._stream_thread and self._stream_thread.is_alive():
            self._send_event({"type": "error", "message": "Stream thread already active"})
            return

        if not self._transport or not self._transport.is_connected() or not self._grbl_validated:
            self._send_event({"type": "error", "message": "Not connected"})
            return

        if self._is_firmware_alarm() or self._get_state() == WorkerState.ALARM:
            self._set_state(WorkerState.ALARM)
            self._send_event({"type": "error", "message": "ALARM active; unlock ($X) required before start"})
            return

        file_raw = str(payload.get("file", payload.get("file_path", ""))).strip()
        file_path = Path(file_raw)
        if not file_path.exists():
            self._send_event({"type": "error", "message": "G-code file does not exist"})
            return

        settings = self._resolve_stream_settings(file_path=file_path, payload=payload)
        self._join_timeout_emitted = False
        self._set_error_latched(False)
        self._stop_requested.clear()
        self._pause_requested.clear()
        self._sent_bytes = 0
        self._total_bytes = file_path.stat().st_size
        self._emit_progress(force=True)

        self._stream_thread = threading.Thread(
            target=self._stream_file,
            args=(file_path, settings),
            daemon=True,
        )
        self._stream_thread.start()

    def _cmd_stop(self) -> None:
        if self._get_state() not in {WorkerState.RUNNING, WorkerState.HOLDING, WorkerState.STOPPING}:
            return

        self._set_state(WorkerState.STOPPING)
        self._stop_requested.set()
        self._send_realtime("\x18")
        self._join_stream_thread(timeout=2.0)
        self._reset_stream_state(clear_transport_buffers=True)
        if self._get_state() == WorkerState.STOPPING:
            self._set_state(WorkerState.IDLE)

    def _cmd_pause(self) -> None:
        # TODO: expose pause/resume controls in UI command flow.
        if self._get_state() != WorkerState.RUNNING:
            return
        self._pause_requested.set()
        self._set_state(WorkerState.HOLDING)
        self._send_realtime("!")

    def _cmd_resume(self) -> None:
        # TODO: expose pause/resume controls in UI command flow.
        if self._get_state() != WorkerState.HOLDING:
            return
        self._pause_requested.clear()
        self._set_state(WorkerState.RUNNING)
        self._send_realtime("~")

    def _cmd_realtime(self, payload: Dict[str, Any]) -> None:
        command = str(payload.get("value", "")).strip()
        if command:
            self._send_realtime(command)

    def _cmd_line(self, payload: Dict[str, Any]) -> None:
        state = self._get_state()
        if not self._transport or not self._transport.is_connected() or not self._grbl_validated:
            return

        line = str(payload.get("value", "")).strip()
        if not line:
            return

        normalized_line = self.normalize_payload_line(line)
        if state != WorkerState.IDLE and not (state == WorkerState.ALARM and normalized_line == "$X"):
            return
        self.transport_send_line(normalized_line)
        self._forward_idle_terminal_output()
        if normalized_line == "$X":
            self._set_firmware_alarm(False)
            if self._transport.is_connected():
                self._set_state(WorkerState.IDLE)

    def _cmd_status(self) -> None:
        state = self._get_state()
        if state not in {WorkerState.IDLE, WorkerState.ALARM}:
            return
        if not self._transport or not self._transport.is_connected() or not self._grbl_validated:
            return

        pending_error = self._consume_transport_error()
        if pending_error is not None:
            self._handle_transport_fault(f"Serial transport fault: {pending_error}")
            return

        self._send_realtime("?")
        deadline = time.monotonic() + self._STATUS_POLL_TIMEOUT_S
        lines_seen = 0
        while time.monotonic() < deadline and lines_seen < self._STATUS_POLL_MAX_LINES:
            pending_error = self._consume_transport_error()
            if pending_error is not None:
                self._handle_transport_fault(f"Serial transport fault: {pending_error}")
                return

            try:
                response = self._transport.read_line()
            except Exception as exc:
                self._handle_transport_fault(f"Serial read failed: {exc}")
                return

            if response is None:
                time.sleep(0.005)
                continue

            lines_seen += 1
            position = self._parse_mpos_status(response)
            if position is not None:
                x, y, z = position
                self._send_event({"type": "raw_position", "x": x, "y": y, "z": z})
                return

    def _forward_idle_terminal_output(self) -> None:
        if not self._transport or self._get_state() not in {WorkerState.IDLE, WorkerState.ALARM}:
            return

        deadline = time.monotonic() + self._TERMINAL_RX_TIMEOUT_S
        emitted_lines = 0
        empty_reads = 0
        while time.monotonic() < deadline and emitted_lines < self._TERMINAL_RX_MAX_LINES:
            pending_error = self._consume_transport_error()
            if pending_error is not None:
                self._handle_transport_fault(f"Serial transport fault: {pending_error}")
                return

            try:
                response = self._transport.read_line()
            except Exception as exc:
                self._handle_transport_fault(f"Serial read failed: {exc}")
                return

            if response is None:
                empty_reads += 1
                if empty_reads >= self._TERMINAL_RX_IDLE_GAP_LIMIT:
                    break
                time.sleep(0.005)
                continue

            empty_reads = 0
            emitted_lines += 1

            if self._protocol.is_ack(response):
                self._send_event({"type": "log", "message": response})
                return

            if self._protocol.is_error(response):
                if response.lstrip().upper().startswith("ALARM:"):
                    self._set_firmware_alarm(True)
                    self._set_state(WorkerState.ALARM)
                    self._send_event({"type": "alarm", "message": response})
                    return

                self._send_event({"type": "error", "message": response})
                return

            self._maybe_emit_grbl_setting(response)
            self._send_event({"type": "log", "message": response})

    def _maybe_emit_grbl_setting(self, response: str) -> None:
        match = self._GRBL_SETTING_RE.match(response)
        if not match:
            return
        self._send_event(
            {
                "type": "grbl_setting",
                "key": int(match.group(1)),
                "value": match.group(2).strip(),
            }
        )

    def _parse_mpos_status(self, response: str) -> Optional[tuple[float, float, float]]:
        match = self._MPOS_RE.search(response)
        if not match:
            return None
        try:
            return (
                float(match.group(1)),
                float(match.group(2)),
                float(match.group(3)),
            )
        except ValueError:
            return None

    def _cmd_shutdown(self) -> None:
        self._cmd_stop()
        self._shutdown_requested.set()

    def _stream_file(self, file_path: Path, settings: StreamSettings) -> None:
        self._set_state(WorkerState.RUNNING)
        try:
            policy: StreamPolicy
            if settings.mode == "byte":
                policy = ByteWindowPolicy(settings.window_bytes, settings.window_lines)
            else:
                policy = LineAckPolicy()

            ok = policy.stream(self, file_path)
            if not ok:
                stream_state = self._get_state()
                if stream_state in {WorkerState.ERROR, WorkerState.STOPPING}:
                    return
                if self._is_firmware_alarm() and self._transport and self._transport.is_connected():
                    self._set_state(WorkerState.ALARM)
                else:
                    self._set_state(WorkerState.ERROR)
                return

            stream_state = self._get_state()
            if stream_state not in {WorkerState.ERROR, WorkerState.STOPPING}:
                self._set_state(WorkerState.IDLE)
                self._emit_progress(force=True)
        except Exception as exc:
            self._set_state(WorkerState.ERROR)
            self._stop_requested.set()
            self._emit_error_once(f"Streaming failed: {exc}")

    def transport_send_line(self, line: str) -> None:
        if not self._transport:
            raise RuntimeError("Transport not available")

        pending_error = self._consume_transport_error()
        if pending_error is not None:
            self._handle_transport_fault(f"Serial transport fault: {pending_error}")
            raise pending_error

        normalized_line = self.normalize_payload_line(line)
        self._send_debug("TX", normalized_line)
        try:
            self._transport.send_line(normalized_line)
        except Exception as exc:
            self._handle_transport_fault(f"Serial write failed: {exc}")
            raise
        self._send_event({"type": "tx_line", "line": normalized_line})

    def should_stop(self) -> bool:
        return self._stop_requested.is_set() or self._shutdown_requested.is_set()

    def should_pause(self) -> bool:
        return self._pause_requested.is_set()

    def on_line_complete(self, raw_bytes: int) -> None:
        self._sent_bytes += raw_bytes
        self._emit_progress()

    @staticmethod
    def make_payload_bytes(line: str) -> bytes:
        return (line.rstrip("\n") + "\n").encode("utf-8", errors="ignore")

    @staticmethod
    def normalize_payload_line(line: str) -> str:
        return SenderWorkerServer.make_payload_bytes(line).decode("utf-8", errors="ignore").rstrip("\n")

    @staticmethod
    def payload_cost_bytes(line: str) -> int:
        return len(SenderWorkerServer.make_payload_bytes(line))

    def on_fifo_empty_ack(self) -> None:
        now = time.monotonic()
        if (now - self._last_fifo_empty_ack_warn) >= self._fifo_empty_ack_warn_interval_s:
            self._last_fifo_empty_ack_warn = now
            self._send_event(
                {
                    "type": "log",
                    "message": "ACK received while FIFO is empty; applying brief backoff",
                }
            )
        time.sleep(0.0015)

    def _maybe_emit_ok_agg(self) -> None:
        if not self._debug_ok_agg:
            return
        now = time.monotonic()
        if (now - self._last_ok_agg_emit) < 1.0:
            return
        count = self._ok_count
        self._ok_count = 0
        self._last_ok_agg_emit = now
        self._send_event({"type": "log", "message": f"ok_count={count}"})

    def wait_for_ack_or_error(self) -> str:
        if not self._transport:
            self._set_state(WorkerState.ERROR)
            self._stop_requested.set()
            self._emit_error_once("Transport not available")
            return AckResult.FAILED

        deadline = time.monotonic() + self._ack_timeout_s
        while True:
            now = time.monotonic()
            if self.should_pause() or self._get_state() == WorkerState.HOLDING:
                deadline = now + self._ack_timeout_s
            elif now >= deadline:
                break

            if self.should_stop():
                return AckResult.STOPPED

            pending_error = self._consume_transport_error()
            if pending_error is not None:
                self._handle_transport_fault(f"Serial transport fault: {pending_error}")
                return AckResult.FAILED

            try:
                response = self._transport.read_line()
            except Exception as exc:
                self._handle_transport_fault(f"Serial read failed: {exc}")
                return AckResult.FAILED
            if response is None:
                time.sleep(0.002)
                continue

            if self._protocol.is_ack(response):
                # ACK hot path must remain side-effect free by default.
                return AckResult.ACK

            if self._protocol.is_error(response):
                if response.lstrip().upper().startswith("ALARM:"):
                    self._set_firmware_alarm(True)
                    self._set_state(WorkerState.ALARM)
                    self._stop_requested.set()
                    self._send_event({"type": "alarm", "message": response})
                    return AckResult.FAILED

                self._set_state(WorkerState.ERROR)
                self._stop_requested.set()
                self._emit_error_once(response, event_type="error")
                return AckResult.FAILED

            self._send_debug("RX", response)

        self._set_state(WorkerState.ERROR)
        self._stop_requested.set()
        self._emit_error_once("ACK timeout reached")
        return AckResult.FAILED

    def _resolve_stream_settings(self, file_path: Path, payload: Dict[str, Any]) -> StreamSettings:
        requested_profile = str(payload.get("profile", "auto")).strip().lower() or "auto"
        if requested_profile not in {"auto", "grbl", "grblhal"}:
            requested_profile = "auto"
        profile = self._detected_profile if requested_profile == "auto" else requested_profile

        default_window_bytes, default_window_lines = self._PROFILE_WINDOWS.get(profile, self._PROFILE_WINDOWS["grbl"])
        override_window = payload.get("window_bytes")
        if override_window is not None:
            try:
                default_window_bytes = max(1, int(override_window))
            except (TypeError, ValueError):
                pass

        requested_mode = "line"
        if "mode" in payload:
            mode_candidate = str(payload.get("mode", "")).strip().lower()
            if mode_candidate in {"auto", "line", "byte"}:
                requested_mode = mode_candidate

        reason = "manual"
        selected_mode = requested_mode
        if requested_mode == "auto":
            selected_mode, reason = self._select_mode_from_file(file_path)

        human_mode = "byte-window" if selected_mode == "byte" else "line-ack"
        self._send_event({"type": "log", "message": f"Streaming mode selected: {human_mode} (reason={reason})"})

        return StreamSettings(
            mode=selected_mode,
            profile=profile,
            window_bytes=default_window_bytes,
            window_lines=default_window_lines,
        )

    def _select_mode_from_file(self, file_path: Path, max_lines: int = 500) -> tuple[str, str]:
        total = 0
        g1_count = 0
        s_count = 0
        short_move_count = 0
        total_len = 0

        short_move_re = re.compile(r"\b[XY]-?0\.0+\b", re.IGNORECASE)
        with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip().upper()
                if not line or line.startswith(";"):
                    continue
                total += 1
                total_len += len(line)
                if "G1" in line:
                    g1_count += 1
                if "S" in line:
                    s_count += 1
                if short_move_re.search(line):
                    short_move_count += 1
                if total >= max_lines:
                    break

        if total == 0:
            return "line", "empty-or-comment-only"

        avg_len = total_len / total
        g1_ratio = g1_count / total
        s_ratio = s_count / total
        short_ratio = short_move_count / total

        is_rasterish = avg_len <= 32 and g1_ratio >= 0.65 and s_ratio >= 0.40
        if is_rasterish:
            return "byte", f"raster-heuristic avg_len={avg_len:.1f},g1={g1_ratio:.2f},s={s_ratio:.2f},"
        return "line", f"default avg_len={avg_len:.1f},g1={g1_ratio:.2f},s={s_ratio:.2f}"

    def _detect_profile_once(self) -> bool:
        if self._profile_probe_done or not self._transport:
            return self._grbl_validated
        self._profile_probe_done = True
        detected = "grbl"
        validated = False

        def _consume_until(deadline: float) -> bool:
            nonlocal detected
            while time.monotonic() < deadline:
                line = self._transport.read_line()
                if line is None:
                    time.sleep(0.01)
                    continue
                upper = line.upper()
                if "GRBLHAL" in upper:
                    detected = "grblhal"
                    return True
                if "GRBL" in upper:
                    detected = "grbl"
                    return True
                if upper.startswith("[VER:") or upper.startswith("[OPT:"):
                    detected = "grbl"
                    return True
                if re.match(r"^\$\d+\s*=", line):
                    detected = "grbl"
                    return True
            return False

        try:
            if hasattr(self._transport, "send_realtime"):
                self._transport.send_realtime("\r\n")
                time.sleep(0.1)
            self._transport.send_line("$I")
            validated = _consume_until(time.monotonic() + 1.8)
            if not validated:
                self._transport.send_line("$$")
                validated = _consume_until(time.monotonic() + 1.2)
        except Exception:
            return False
        self._detected_profile = detected
        return validated

    def _send_realtime(self, command: str) -> None:
        if not self._transport or not self._transport.is_connected():
            return
        try:
            if hasattr(self._transport, "send_realtime"):
                self._transport.send_realtime(command)
            else:
                self._transport.send_line(command)
        except Exception as exc:
            self._handle_transport_fault(f"Realtime command failed: {exc}")

    def _cleanup_transport(self) -> None:
        self._join_stream_thread(timeout=2.0)
        self._close_transport()
        self._reset_stream_state(clear_transport_buffers=False)

    def _close_transport(self) -> None:
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
        self._transport = None
        self._connected_port = None
        self._connected_baud = None
        self._grbl_validated = False
        self._emit_connection_state(False)
        self._pause_requested.clear()

    def _handle_transport_fault(self, message: str) -> None:
        self._set_state(WorkerState.ERROR)
        self._stop_requested.set()
        self._emit_error_once(message)
        self._close_transport()

    def _emit_connection_state(self, connected: bool) -> None:
        if self._connected_emitted == connected:
            return
        self._connected_emitted = connected
        self._send_event({"type": "connection", "connected": connected})

    def _join_stream_thread(self, timeout: float) -> None:
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=timeout)
            if self._stream_thread.is_alive():
                self._set_state(WorkerState.ERROR)
                if not self._join_timeout_emitted:
                    self._join_timeout_emitted = True
                    self._emit_error_once("Stream thread join timeout")
        self._stream_thread = None


    def _consume_transport_error(self) -> Optional[Exception]:
        transport = self._transport
        if not transport or not hasattr(transport, "consume_error"):
            return None
        try:
            return transport.consume_error()
        except Exception:
            return None

    def _emit_error_once(self, message: str, event_type: str = "error") -> None:
        if not self._try_latch_error():
            return
        self._send_event({"type": event_type, "message": message})

    def _get_state(self) -> str:
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: str) -> None:
        emit_state = False
        with self._state_lock:
            if self._state != new_state:
                self._state = new_state
                emit_state = True
        if emit_state:
            self._send_event({"type": "state", "state": new_state})

    def _set_error_latched(self, value: bool) -> None:
        with self._state_lock:
            self._error_latched = value

    def _try_latch_error(self) -> bool:
        with self._state_lock:
            if self._error_latched:
                return False
            self._error_latched = True
            return True

    def _set_firmware_alarm(self, value: bool) -> None:
        with self._state_lock:
            self._firmware_alarm = value

    def _is_firmware_alarm(self) -> bool:
        with self._state_lock:
            return self._firmware_alarm

    def _emit_progress(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_progress_emit) < self._progress_interval_s:
            return
        self._last_progress_emit = now
        self._send_event(
            {
                "type": "progress",
                "sent_bytes": self._sent_bytes,
                "total_bytes": self._total_bytes,
            }
        )

    def _send_debug(self, direction: str, line: str) -> None:
        now = time.monotonic()
        if self._last_debug_emit and (now - self._last_debug_emit) < self._debug_interval_s:
            return
        self._last_debug_emit = now
        self._send_event({"type": "debug", "direction": direction, "line": line})

    def _send_event(self, payload: Dict[str, Any]) -> None:
        serialized = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self._client_lock:
            client = self._client
            if not client:
                return
            try:
                client.sendall(serialized)
            except OSError:
                return


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless GRBL sender worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--ipc-port", type=int, required=True)
    parser.add_argument("--ack-timeout", type=float, default=15.0)
    parser.add_argument("--mock-serial", action="store_true")
    parser.add_argument("--debug-ok-agg", action="store_true")
    args = parser.parse_args()

    use_mock = args.mock_serial or os.getenv("SENDER_MOCK", "0").strip() == "1"
    if use_mock:
        transport_factory = FakeSerialTransport
    else:
        from sender.transport_serial import SerialTransport

        transport_factory = SerialTransport

    server = SenderWorkerServer(
        host=args.host,
        ipc_port=args.ipc_port,
        ack_timeout_s=args.ack_timeout,
        debug_ok_agg=args.debug_ok_agg or os.getenv("SENDER_DEBUG_OK_AGG", "0").strip() == "1",
        transport_factory=transport_factory,
    )

    def _signal_handler(signum: int, _frame: Any) -> None:
        _ = signum
        try:
            server._cmd_shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
