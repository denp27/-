"""Simple in-process TTL cache for async callables.

Usage:
    from app.utils.cache import cached, invalidate

    result = await cached("my_key", lambda: some_async_call(), ttl=60)
    invalidate("my_key")
"""
import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

_store: Dict[str, Tuple[Any, float]] = {}
_locks: Dict[str, asyncio.Lock] = {}


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def cached(
    key: str,
    coro_factory: Callable[[], Awaitable[Any]],
    ttl: float,
) -> Any:
    """
    Return cached value for *key* if not expired, otherwise
    call *coro_factory()* to refresh and cache the result for *ttl* seconds.
    None results are NOT cached so a failing API call always retries.
    """
    now = time.monotonic()
    entry = _store.get(key)
    if entry is not None:
        value, expires_at = entry
        if now < expires_at:
            return value

    lock = _get_lock(key)
    async with lock:
        # double-check after acquiring lock
        now = time.monotonic()
        entry = _store.get(key)
        if entry is not None:
            value, expires_at = entry
            if now < expires_at:
                return value

        value = await coro_factory()
        if value is not None:
            _store[key] = (value, now + ttl)
        return value


def invalidate(key: str) -> None:
    """Remove a cache entry so the next call re-fetches."""
    _store.pop(key, None)


def invalidate_prefix(prefix: str) -> None:
    """Remove all cache entries whose key starts with *prefix*."""
    for key in list(_store):
        if key.startswith(prefix):
            del _store[key]
