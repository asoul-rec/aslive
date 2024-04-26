import asyncio
from collections import deque
import logging
from typing import Optional, Any, Callable, Awaitable
from functools import partial

from pyrogram.errors import MessageNotModified


class Danmaku:
    """
    Time-based danmaku updater. This class provides

    - Reading danmaku file. Should be DPlayer format JSON file (ASCII / UTF-8 encoding for Unicode characters).
      Async loading with asyncio thread pool, start at initialization.

    - External callback function for real operation. The callback is called with a fixed time interval.

    - For synchronization, the start_time and current_time should be updated externally.
      Danmaku time falling between the old and new time will be picked and displayed.

    - The number of updated items will be kept at the `update_count` number. Extra danmaku will be discarded.
      Insufficient danmaku will be loaded from the previous discarded items (if exist).

    - The playing time should flow forward. Use `restart` to reset time and start again.
    """
    data: Optional[list] = None
    _reader_task: asyncio.Task
    _stale_buffer: Optional[deque[tuple[float, str]]]
    _active_buffer: deque[str]
    update_callback: callable
    update_count: int
    update_interval: float
    _name: Any
    updater: asyncio.Task
    start_time: Optional[float]
    current_time: Optional[float]
    _watchdog: asyncio.Task = None

    def __init__(self, file, update_callback: Callable[[str], Awaitable],
                 total_count=20,
                 update_count=5,
                 update_interval=3,
                 buffer_time=5):
        self._name = file
        self._reader_task = asyncio.create_task(self._reader(file))
        if buffer_time > 0:
            self._stale_buffer = deque()
        else:
            self._stale_buffer = None
        total_count = max(int(total_count), 0)
        self.update_count = min(max(int(update_count), 0), total_count)
        self._active_buffer = deque(maxlen=total_count)
        self.update_callback = update_callback
        self.update_interval = max(update_interval, 0)
        self.updater = asyncio.create_task(self._update_coro())
        self.start_time = self.current_time = None

    def _reader(self, file):
        def read():
            import json
            try:
                with opener() as f:
                    file_content = f.read(1)
                    if file_content[:1] != b'{':
                        logging.error("the danmaku file must be JSON format starting with '{'")
                        return
                    # 20M max length, avoid OOM if a very large file is given accidentally
                    file_content += f.read(20 << 20)
                data = json.loads(file_content.decode('utf-8'))['data']
                data = [(i[0], i[4]) for i in data if isinstance(i[4], str)]
                data.sort()
                self.data = data
            except UnicodeDecodeError:
                logging.error(f"danmaku is not a valid utf-8 encoded file")
            except Exception as e:
                logging.error(f"danmaku load failed: {e!r}")
            finally:
                if not self.data:
                    self.data = [(0, "弹幕加载失败")]

        if file.startswith("http"):
            from urllib import request, parse
            opener = partial(request.urlopen, parse.quote(file, safe=':/?&='), timeout=10)
        else:
            opener = partial(open, file, 'rb')

        return asyncio.to_thread(read)

    async def _update_coro(self):
        if self._watchdog is not None:
            self._watchdog.cancel()
        self._watchdog = asyncio.create_task(self._watchdog_coro())
        try:
            await self._reader_task
            # wait until start_time & current_time is set
            while self.start_time is None or self.current_time is None:
                logging.debug(f"danmaku {self._name} is loaded but not started")
                await asyncio.sleep(self.update_interval)
            self.start_time: float  # type hint
            self.current_time: float  # type hint
            logging.info(f"start streaming danmaku file: {self._name}")
            count = self.update_count
            for data_i in self.data:
                while data_i[0] > self.current_time - self.start_time:
                    await self._do_update(count)
                    count = self.update_count
                    await asyncio.sleep(self.update_interval)
                if count > 0:
                    self._active_buffer.append(data_i[1])
                else:
                    if self._stale_buffer is not None:
                        self._stale_buffer.append(data_i)
                count -= 1
            await self._do_update(count)
            logging.info(f"danmaku updater is finished: {self._name}")
        except asyncio.CancelledError:
            logging.info(f"danmaku updater is cancelled: {self._name}")
            raise
        except Exception as e:
            logging.error(f"danmaku updater get an exception, file: {self._name}, exception: {repr(e)}")
            raise

    async def _watchdog_coro(self):
        PROBE_NUM = 4
        curr_time_history = deque(maxlen=PROBE_NUM)
        while not self.updater.done():
            curr_time = self.current_time
            curr_time_history.append(curr_time)
            if curr_time_history.count(curr_time) == PROBE_NUM:
                logging.error("Danmaku is inactive over 60s, exiting.")
                self.updater.cancel()
            await asyncio.sleep(20)

    async def _do_update(self, count):
        if count > 0:
            logging.info(f"New danmaku is not enough. Fill {count} slots from buffer.")
            while count > 0 and self._stale_buffer:
                self._active_buffer.append(self._stale_buffer.pop()[1])
                count -= 1
            if count > 0:
                if count == self.update_count:
                    logging.warning(f"no new danmaku, skip this round")
                    return
                else:
                    logging.warning(f"Danmaku is not enough. {count} in {self.update_count} is not updated")
        new_message = '\n'.join(self._active_buffer)
        try:
            await self.update_callback(new_message)
        except MessageNotModified:
            logging.info(f"danmaku content is not modified")
        except Exception as e:
            logging.error(f"update_callback get an exception, new message: {new_message}, exception: {repr(e)}")

    def restart(self):
        self.updater.cancel()
        self._stale_buffer.clear()
        self._active_buffer.clear()
        self.start_time = self.current_time = None
        self.updater = asyncio.create_task(self._update_coro())
