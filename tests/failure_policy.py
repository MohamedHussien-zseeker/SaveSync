"""Deterministic failure injection for tests — zero production imports."""

ALL_HOOKS = (
    "before_open", "after_open",
    "before_transfer_chunk", "after_transfer_chunk",
    "before_verify", "before_commit", "before_retry", "before_close",
)


class InjectingFailureError(Exception):
    def __init__(self, wrapped, failure_id="", hook=""):
        self.wrapped = wrapped
        self.failure_id = failure_id
        self.hook = hook
        super().__init__(str(wrapped))


class InjectingFailurePolicy:
    """Configured with a dict mapping hook names to failure rules.

    Example config:
        {
            "before_open": {
                "fail_on": 1,
                "exception": PermissionError("access denied"),
                "failure_id": "perm_denied",
            },
            "after_transfer_chunk": {
                "fail_on": 5,
                "exception": OSError(28, "No space left on device"),
                "failure_id": "disk_full_chunk_5",
            },
        }
    """

    def __init__(self, config=None):
        self._config = config or {}
        self._counters = {h: 0 for h in ALL_HOOKS}
        self.last_failure_id = None
        self.last_hook = None
        self.fired = False

    def _maybe_fail(self, hook, *args):
        self._counters[hook] += 1
        rule = self._config.get(hook)
        if rule and self._counters[hook] >= rule["fail_on"]:
            self.last_failure_id = rule.get("failure_id", hook)
            self.last_hook = hook
            self.fired = True
            exc = rule.get("exception", Exception("injected failure"))
            if not isinstance(exc, BaseException):
                exc = Exception(str(exc))
            raise InjectingFailureError(
                exc,
                failure_id=self.last_failure_id,
                hook=hook,
            )

    def before_open(self):
        self._maybe_fail("before_open")

    def after_open(self):
        self._maybe_fail("after_open")

    def before_transfer_chunk(self, chunk_idx):
        self._maybe_fail("before_transfer_chunk", chunk_idx)

    def after_transfer_chunk(self, chunk_idx):
        self._maybe_fail("after_transfer_chunk", chunk_idx)

    def before_verify(self):
        self._maybe_fail("before_verify")

    def before_commit(self):
        self._maybe_fail("before_commit")

    def before_retry(self, attempt):
        self._maybe_fail("before_retry", attempt)

    def before_close(self):
        self._maybe_fail("before_close")
