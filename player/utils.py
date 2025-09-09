import asyncio
import time
from asyncio import Queue
from contextlib import asynccontextmanager
from types import CoroutineType
from typing import Callable, Any

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


class ThrottledCall:
    func: Callable
    last_call_time: float

    def __init__(self, func, min_interval, timer=time.time):
        self.func = func
        self.min_interval = min_interval
        self.timer = timer
        self.last_call_time = 0

    def __call__(self, *args, **kwargs):
        this_call_time = self.timer()
        if this_call_time - self.last_call_time >= self.min_interval:
            self.func(*args, **kwargs)
            self.last_call_time = this_call_time


async def _run_callback(func: Callable[[], Any]):
    result = func()
    if isinstance(result, CoroutineType):
        result = await result
    return result


@asynccontextmanager
async def video_opener(file, *args, **kwargs):
    if callable(file):
        file = await _run_callback(file)
    result = await asyncio.to_thread(av.open, file, *args, **kwargs)
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
