import logging
import threading

logger = logging.getLogger(__name__)


class DatasetUpdater:
    """Background updater that periodically checks for dataset freshness."""

    def __init__(self, callback, interval: int = 3600):
        self._callback = callback
        self._interval = interval
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._schedule()

    def stop(self):
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule(self):
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._run)
        self._timer.daemon = True
        self._timer.start()

    def _run(self):
        if not self._running:
            return
        try:
            self._callback()
        except Exception:
            logger.exception("Error in background dataset update")
        self._schedule()
