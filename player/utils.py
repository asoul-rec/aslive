import asyncio
from asyncio import Queue
from contextlib import asynccontextmanager
import functools
import av


class Progress:
    """
    A callback async iter to report progress
    """
    message_queue: Queue
    finished: bool

    def __init__(self):
        self.message_queue = Queue()
        self.finished = False

    async def __aiter__(self):
        if self.finished:
            return
        while True:
            yield await self.message_queue.get()
            if self.finished:
                return

    def add_message(self, message, final=False):
        if self.finished:
            return
        self.message_queue.put_nowait(message)
        if final:
            self.finished = True


@asynccontextmanager
async def video_opener(*args, **kwargs):
    result = await asyncio.to_thread(av.open, *args, **kwargs)
    try:
        yield result
    finally:
        await asyncio.to_thread(result.close)


async def iter_to_thread(iterator):
    stop_iter = object()
    while True:
        item = await asyncio.to_thread(next, iterator, stop_iter)
        if item is stop_iter:
            break
        yield item
