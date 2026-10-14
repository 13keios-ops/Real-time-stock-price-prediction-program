"""Opt-in POSIX paper HTTP coordination; no automatic runtime installation."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time

from app.brokers.kis_auth import KisApiError


class PaperCoordinatorBusy(KisApiError):
    """The caller must defer without issuing or retrying an HTTP request."""


class PaperRequestCoordinator:
    """Same explicit folder coordinates participating processes, not all API users.

    Primary calls hold a shared priority lock while queued/in flight. Candidate
    calls require its exclusive lock nonblocking and never queue behind primary.
    Authentication and clients without explicit injection are outside this scope.
    """
    def __init__(self, folder, *, clock=None, sleep=None):
        self.folder = Path(folder).absolute()
        if self.folder.resolve() != self.folder:
            raise ValueError('Linked coordinator storage forbidden')
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep

    def _now(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('Finite coordinator clock required')
        return now

    @contextmanager
    def _lock(self, name, *, exclusive, nonblocking, deadline):
        try:
            import fcntl
        except ImportError:
            raise ValueError('POSIX shared locks required') from None
        path = self.folder/name
        if path.is_symlink():
            raise ValueError('Linked coordinator lock forbidden')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Regular unlinked coordinator lock required')
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            while True:
                try:
                    fcntl.flock(fd, operation | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if nonblocking or time.monotonic() >= deadline:
                        raise PaperCoordinatorBusy('Paper request slot unavailable') from None
                    self.sleep(min(0.05, max(0, deadline-time.monotonic())))
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _state(self):
        path = self.folder/'state.json'
        if path.is_symlink():
            raise ValueError('Linked coordinator state forbidden')
        if not path.exists():
            return 0.0
        try:
            if path.stat().st_size > 1024 or path.stat().st_nlink != 1:
                raise ValueError()
            state = json.loads(path.read_text(encoding='utf-8'))
            value = state['not_before']
            if (state.get('version') != 'paper-request-pacing-v1'
                    or type(value) not in (int,float) or not math.isfinite(value) or value < 0):
                raise ValueError()
            return value
        except (ValueError, KeyError, TypeError):
            raise ValueError('Invalid coordinator state; refusing to clear reservation') from None

    def _store(self, not_before):
        fd, name = tempfile.mkstemp(prefix='.pacing-', dir=self.folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump({'version':'paper-request-pacing-v1', 'not_before':not_before}, handle)
                handle.flush();os.fsync(handle.fileno())
            os.replace(name, self.folder/'state.json')
            directory = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @contextmanager
    def slot(self, *, timeout_seconds, low_priority=False):
        if (type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 60 or type(low_priority) is not bool):
            raise ValueError('Bounded timeout and explicit request priority required')
        deadline = time.monotonic()+15
        with self._lock('priority.lock', exclusive=low_priority, nonblocking=low_priority, deadline=deadline):
            with self._lock('request.lock', exclusive=True, nonblocking=low_priority, deadline=deadline):
                delay = self._state()-self._now()
                if delay > 0:
                    if low_priority or delay > deadline-time.monotonic():
                        raise PaperCoordinatorBusy('Paper response-completion cooldown active')
                    self.sleep(delay)
                    if self._state() > self._now():
                        raise PaperCoordinatorBusy('Paper cooldown did not expire')
                started = self._now()
                # A killed process releases flock but leaves a bounded reservation.
                self._store(started+timeout_seconds+1.1)
                try:
                    yield
                finally:
                    self._store(max(started, self._now())+1.1)
