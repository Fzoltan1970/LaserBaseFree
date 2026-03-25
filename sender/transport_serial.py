from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Optional
import serial


class TxQueueOverflowError(RuntimeError):
    """Raised when the TX queue reached its configured upper bound."""


class SerialTransport:
    """Minimal serial transport with line-based RX and queued TX."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 0.02,
        dtr_toggle: bool = False,
        rtscts: bool = False,
        xonxoff: bool = False,
        max_tx_queue: int = 10000,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._dtr_toggle = dtr_toggle
        self._rtscts = rtscts
        self._xonxoff = xonxoff
        self._max_tx_queue = max(1, max_tx_queue)

        self._serial: Optional[serial.Serial] = None
        self._write_lock = Lock()
        self._tx_queue: Queue[str] = Queue()
        self._stop_event = Event()
        self._tx_thread: Optional[Thread] = None
        self._error_lock = Lock()
        self._async_error: Optional[Exception] = None

    def connect(self) -> None:
        if self._serial and self._serial.is_open:
            return

        self._serial = serial.Serial(
            self._port,
            self._baudrate,
            timeout=self._timeout,
            rtscts=self._rtscts,
            xonxoff=self._xonxoff,
        )

        if self._dtr_toggle:
            self._serial.dtr = False
            self._serial.dtr = True

        self._stop_event.clear()
        self._set_async_error(None)
        self._tx_thread = Thread(target=self._tx_loop, daemon=True)
        self._tx_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._tx_thread and self._tx_thread.is_alive():
            self._tx_thread.join(timeout=1.0)
        self._tx_thread = None
        self.clear_tx_queue()

        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def clear_tx_queue(self) -> None:
        while True:
            try:
                self._tx_queue.get_nowait()
            except Empty:
                break

    def clear_io_buffers(self) -> None:
        if not self._serial or not self._serial.is_open:
            return
        with self._write_lock:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def send_line(self, line: str) -> None:
        pending_error = self.consume_error()
        if pending_error is not None:
            raise pending_error
        if self._tx_queue.qsize() >= self._max_tx_queue:
            raise TxQueueOverflowError(f"TX queue overflow (limit={self._max_tx_queue})")
        self._tx_queue.put_nowait(line)

    def send_realtime(self, command: str) -> None:
        if not self._serial or not self._serial.is_open:
            return
        payload = command.encode("utf-8", errors="ignore")
        with self._write_lock:
            self._serial.write(payload)
            self._serial.flush()

    def read_line(self) -> Optional[str]:
        pending_error = self.consume_error()
        if pending_error is not None:
            raise pending_error
        if not self._serial or not self._serial.is_open:
            return None

        try:
            raw = self._serial.readline()
        except Exception as exc:
            self._set_async_error(exc)
            raise
        if not raw:
            return None

        return raw.decode(errors="ignore").strip()

    def _tx_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                line = self._tx_queue.get(timeout=0.1)
            except Empty:
                continue

            if not self._serial or not self._serial.is_open:
                continue

            payload = (line.rstrip("\n") + "\n").encode("utf-8", errors="ignore")
            with self._write_lock:
                try:
                    self._serial.write(payload)
                except Exception as exc:
                    self._set_async_error(exc)
                    return

    def consume_error(self) -> Optional[Exception]:
        with self._error_lock:
            err = self._async_error
            self._async_error = None
            return err

    def _set_async_error(self, error: Optional[Exception]) -> None:
        with self._error_lock:
            self._async_error = error
