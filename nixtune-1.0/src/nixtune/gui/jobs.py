"""Run blocking work off the GUI thread and deliver results back on it.

Results are delivered through a signal connected to a slot on a QObject that
lives in the GUI thread, so callbacks always execute in the GUI thread even
though the work ran in a plain Python thread.
"""

from __future__ import annotations

import logging
import threading
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal, Slot

log = logging.getLogger("nixtune.jobs")


class JobRunner(QObject):
    _finished = Signal(object)
    _line = Signal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._finished.connect(self._deliver_finished, Qt.ConnectionType.QueuedConnection)
        self._line.connect(self._deliver_line, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------- submit
    def submit(
        self,
        fn: Callable[[], Any],
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._start(lambda _emit: fn(), None, on_result, on_error)

    def submit_streaming(
        self,
        fn: Callable[[Callable[[str], None]], Any],
        on_line: Optional[Callable[[str], None]] = None,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """`fn` receives an `emit(text)` callable that streams lines to `on_line`."""
        self._start(fn, on_line, on_result, on_error)

    def _start(self, fn, on_line, on_result, on_error) -> None:
        def emit(text: str) -> None:
            if on_line is not None:
                self._line.emit((on_line, text))

        def target() -> None:
            try:
                payload = (on_result, on_error, True, fn(emit))
            except BaseException as exc:  # noqa: BLE001 - report, never crash the thread silently
                log.error("job failed: %s", traceback.format_exc())
                payload = (on_result, on_error, False, f"{type(exc).__name__}: {exc}")
            self._finished.emit(payload)

        threading.Thread(target=target, name="nixtune-job", daemon=True).start()

    # ------------------------------------------------------------ deliver
    @Slot(object)
    def _deliver_line(self, payload) -> None:
        callback, text = payload
        callback(text)

    @Slot(object)
    def _deliver_finished(self, payload) -> None:
        on_result, on_error, ok, value = payload
        if ok:
            if on_result is not None:
                on_result(value)
        elif on_error is not None:
            on_error(value)
        else:
            log.error("unhandled job error: %s", value)


_runner: Optional[JobRunner] = None


def get_jobs() -> JobRunner:
    """Lazily create the single JobRunner (must first be called from the GUI thread)."""
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner
