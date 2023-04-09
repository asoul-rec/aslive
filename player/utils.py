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
    # def _cache_prefetch():
    #     with open(file, 'rb') as f:
    #         f.read(1048576)
    # if args:
    #     file = args[0]
    # else:
    #     file = kwargs.get('file')
    # await loop.run_in_executor(None, _cache_prefetch)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, functools.partial(av.open, *args, **kwargs))
    try:
        yield result
    finally:
        result.close()
