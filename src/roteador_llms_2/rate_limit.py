import asyncio
import os
import time
from contextlib import asynccontextmanager

MAX_CONCURRENT = int(os.getenv("NVIDIA_MAX_CONCURRENT", "1"))
MIN_INTERVAL = float(os.getenv("NVIDIA_MIN_INTERVAL", "1.0"))
COOLDOWN_429 = float(os.getenv("NVIDIA_COOLDOWN_429", "30.0"))

nvidia_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_state_lock = asyncio.Lock()
_last_request_at = 0.0
_cooldown_until = 0.0


def register_429() -> None:
    """Pausa todas as próximas requests NVIDIA após rate limit."""
    global _cooldown_until
    _cooldown_until = max(_cooldown_until, time.monotonic() + COOLDOWN_429)


async def _wait_until_ready() -> None:
    while True:
        now = time.monotonic()
        async with _state_lock:
            wait_until = max(_cooldown_until, _last_request_at + MIN_INTERVAL)
        delay = wait_until - now
        if delay <= 0:
            return
        await asyncio.sleep(delay)


@asynccontextmanager
async def acquire_nvidia_slot():
    """Aguarda cooldown global, intervalo mínimo e slot de concorrência."""
    global _last_request_at
    await _wait_until_ready()
    await nvidia_semaphore.acquire()
    try:
        async with _state_lock:
            _last_request_at = time.monotonic()
        yield
    finally:
        nvidia_semaphore.release()
