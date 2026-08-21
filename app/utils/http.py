import ssl
from contextlib import asynccontextmanager

import aiohttp
import certifi
_session: aiohttp.ClientSession | None = None


def _make_session() -> aiohttp.ClientSession:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(
        ssl=ssl_context,
        limit=100,
        limit_per_host=20,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )
    timeout = aiohttp.ClientTimeout(total=60)
    return aiohttp.ClientSession(connector=connector, timeout=timeout)


def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = _make_session()
    return _session


@asynccontextmanager
async def session_ctx():
    yield get_session()


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None
