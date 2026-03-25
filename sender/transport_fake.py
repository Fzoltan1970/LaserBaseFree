from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event
from typing import Optional


class MockSerialException(RuntimeError):
    """SerialException-compatible mock transport failure."""


@dataclass
class FakeSerialConfig:
    ack_delay_s: float = 0.0005
    ack_jitter_s: float = 0.0005
    status_interval_s: float = 0.2
    error_probability: float = 0.0
    alarm_probability: float = 0.0
    disconnect_probability: float = 0.0
    disconnect_after_writes: int = 0
    error_pattern: Optional[re.Pattern[str]] = None

    @classmethod
    def from_env(cls) -> "FakeSerialConfig":
        pattern = os.getenv("SENDER_MOCK_ERROR_PATTERN", "").strip()
        return cls(
            ack_delay_s=max(0.0, float(os.getenv("SENDER_MOCK_ACK_DELAY_S", "0.0005"))),
            ack_jitter_s=max(0.0, float(os.getenv("SENDER_MOCK_ACK_JITTER_S", "0.0005"))),
            status_interval_s=max(0.0, float(os.getenv("SENDER_MOCK_STATUS_INTERVAL_S", "0.2"))),
            error_probability=min(1.0, max(0.0, float(os.getenv("SENDER_MOCK_ERROR_PROB", "0")))),
            alarm_probability=min(1.0, max(0.0, float(os.getenv("SENDER_MOCK_ALARM_PROB", "0")))),
            disconnect_probability=min(
                1.0,
                max(0.0, float(os.getenv("SENDER_MOCK_DISCONNECT_PROB", "0"))),
            ),
            disconnect_after_writes=max(
                0,
                int(os.getenv("SENDER_MOCK_DISCONNECT_AFTER_WRITES", "0")),
            ),
            error_pattern=re.compile(pattern, re.IGNORECASE) if pattern else None,
        )


class FakeSerialTransport:
    """A deterministic serial-like transport for long-run sender tests."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 0.02,
        config: Optional[FakeSerialConfig] = None,
        **_: object,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._config = config or FakeSerialConfig.from_env()
        self._connected = False
        self._rx_queue: Queue[str] = Queue()
        self._pending_acks: list[tuple[float, str]] = []
        self._last_status_emit = time.monotonic()
        self._write_count = 0
        self._writes: list[str] = []
        self._stop_event = Event()

    def connect(self) -> None:
        if self._connected:
            return
        self._connected = True
        self._stop_event.clear()
        self._last_status_emit = time.monotonic()

    def close(self) -> None:
        self._stop_event.set()
        self._connected = False
        self._pending_acks.clear()
        self.clear_io_buffers()

    def is_connected(self) -> bool:
        return self._connected

    def send_line(self, line: str) -> None:
        self._assert_connected()
        self._write_count += 1
        clean = line.rstrip("\n")
        self._writes.append(clean)
        self._maybe_disconnect()
        self._assert_connected()

        if clean == "\x18":
            self._schedule_response("ok")
            return

        if self._config.error_pattern and self._config.error_pattern.search(clean):
            self._schedule_response("error: mocked pattern failure")
            return

        roll = random.random()
        if roll < self._config.error_probability:
            self._schedule_response("error: mocked random failure")
            return

        if roll < (self._config.error_probability + self._config.alarm_probability):
            self._schedule_response("alarm: mocked random alarm")
            return

        self._schedule_response("ok")

    def send_realtime(self, command: str) -> None:
        self._assert_connected()
        clean = command.strip()
        self._writes.append(clean)
        if clean == "\x18":
            self._schedule_response("ok")

    def read_line(self) -> Optional[str]:
        self._assert_connected()
        self._maybe_disconnect()
        self._assert_connected()
        self._emit_ready_acks()
        self._emit_status_if_due()

        try:
            return self._rx_queue.get_nowait()
        except Empty:
            return None

    def consume_error(self) -> Optional[Exception]:
        return None

    def clear_tx_queue(self) -> None:
        self._pending_acks.clear()

    def clear_io_buffers(self) -> None:
        self._pending_acks.clear()
        while True:
            try:
                self._rx_queue.get_nowait()
            except Empty:
                break

    def _schedule_response(self, line: str) -> None:
        delay = self._config.ack_delay_s
        if self._config.ack_jitter_s:
            delay += random.random() * self._config.ack_jitter_s
        self._pending_acks.append((time.monotonic() + delay, line))

    def _emit_ready_acks(self) -> None:
        now = time.monotonic()
        ready = [item for item in self._pending_acks if item[0] <= now]
        if not ready:
            return
        self._pending_acks = [item for item in self._pending_acks if item[0] > now]
        for _, line in ready:
            self._rx_queue.put_nowait(line)

    def _emit_status_if_due(self) -> None:
        if self._config.status_interval_s <= 0:
            return
        now = time.monotonic()
        if now - self._last_status_emit < self._config.status_interval_s:
            return
        self._last_status_emit = now
        self._rx_queue.put_nowait("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")

    def _maybe_disconnect(self) -> None:
        if not self._connected:
            return
        if self._config.disconnect_after_writes > 0 and self._write_count >= self._config.disconnect_after_writes:
            self._connected = False
            raise MockSerialException("Mocked disconnect (write threshold)")
        if self._config.disconnect_probability > 0.0 and random.random() < self._config.disconnect_probability:
            self._connected = False
            raise MockSerialException("Mocked disconnect (random)")

    def _assert_connected(self) -> None:
        if not self._connected:
            raise MockSerialException("Mock serial disconnected")
