import asyncio
import random
from typing import Callable, Awaitable


class PurchaseQueue:
    def __init__(self):
        self._queue: asyncio.Queue = None
        self._worker_task = None
        self._processing = False
        self._size = 0

    def start(self):
        self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self):
        while True:
            coro = await self._queue.get()
            self._processing = True
            try:
                await coro()
            except Exception as e:
                print(f"[Queue] Error processing purchase: {e}")
            finally:
                self._queue.task_done()
                self._processing = False
                self._size = max(0, self._size - 1)
                if not self._queue.empty():
                    delay = random.randint(10, 15)
                    await asyncio.sleep(delay)

    async def add(self, coro: Callable[[], Awaitable]) -> int:
        self._size += 1
        position = self._size
        await self._queue.put(coro)
        return position

    def queue_size(self) -> int:
        return self._size


purchase_queue = PurchaseQueue()
