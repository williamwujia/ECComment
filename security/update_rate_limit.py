from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass
class UpdateRateLimiter:
    """Process-wide guard for expensive, state-changing import runs."""

    max_runs: int = 6
    window_seconds: int = 3600
    min_interval_seconds: int = 30
    clock: Callable[[], float] = time.monotonic
    _started_at: deque[float] = field(default_factory=deque, init=False)
    _in_progress: bool = field(default=False, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @classmethod
    def from_environment(cls) -> "UpdateRateLimiter":
        return cls(
            max_runs=_positive_int_env("TMC_MAX_UPDATE_RUNS_PER_HOUR", 6),
            window_seconds=3600,
            min_interval_seconds=_positive_int_env(
                "TMC_MIN_SECONDS_BETWEEN_UPDATES", 30
            ),
        )

    def try_begin(self) -> str | None:
        """Reserve one update slot, or return a user-facing rejection reason."""
        now = self.clock()
        with self._lock:
            while self._started_at and now - self._started_at[0] >= self.window_seconds:
                self._started_at.popleft()
            if self._in_progress:
                return "已有更新正在执行，请等待它结束后再试。"
            if self._started_at and now - self._started_at[-1] < self.min_interval_seconds:
                remaining = int(self.min_interval_seconds - (now - self._started_at[-1])) + 1
                return f"为保护服务，请在 {remaining} 秒后再提交更新。"
            if len(self._started_at) >= self.max_runs:
                return "本服务最近一小时的更新次数已达上限，请稍后再试。"
            self._started_at.append(now)
            self._in_progress = True
        return None

    def finish(self) -> None:
        with self._lock:
            self._in_progress = False


PUBLIC_UPDATE_LIMITER = UpdateRateLimiter.from_environment()
