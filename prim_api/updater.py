"""Background dataset updater using a self-rescheduling timer.

The pattern works like this:

1. ``start()`` sets a flag and calls ``_schedule()``.
2. ``_schedule()`` creates a ``threading.Timer`` that will fire ``_run()``
   after ``interval`` seconds.
3. ``_run()`` executes the callback, then calls ``_schedule()`` again —
   creating the next timer.  This loop repeats until ``stop()`` is called.

Using ``threading.Timer`` (rather than ``time.sleep`` in a loop) makes
cancellation trivial: just call ``timer.cancel()``.

See also: ``docs/developer_guide.md`` § Threading.
"""

import logging
import threading

logger = logging.getLogger(__name__)


class DatasetUpdater:
    """Periodically invokes a callback to refresh datasets.

    Args:
        callback: Callable to run on each tick (typically ``ensure_all_datasets``).
        interval: Seconds between invocations (default 3600 = 1 hour).
    """

    def __init__(self, callback, interval: int = 3600):
        self._callback = callback
        self._interval = interval
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self):
        """Begin the periodic refresh cycle (no-op if already running)."""
        if self._running:
            return
        self._running = True
        self._schedule()

    def stop(self):
        """Cancel the pending timer and stop the cycle."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule(self):
        """Create the next Timer.  Called internally after each run."""
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._run)
        # daemon=True ensures this thread won't prevent the Python process from
        # exiting.  Without it, a pending Timer would keep the program alive
        # even after the main thread finishes.
        self._timer.daemon = True
        self._timer.start()

    def _run(self):
        """Execute the callback and schedule the next invocation.

        A broad try/except ensures that a single failed refresh does not kill
        the periodic cycle — the next timer is always scheduled.
        """
        if not self._running:
            return
        try:
            self._callback()
        except Exception:
            logger.exception("Error in background dataset update")
        # Re-schedule regardless of success or failure
        self._schedule()
