import asyncio
from collections import deque
import logging
from typing import Optional, Any


class Danmaku:
    data: Optional[list] = None
    _reader_future: asyncio.Future
    _stale_buffer: Optional[deque[tuple[float, str]]]
    _active_buffer: deque[str]
    update_callback: callable
    update_count: int
    update_time: float
    _name: Any
    updater: asyncio.Task
    start_time: Optional[float]
    current_time: Optional[float]

    def __init__(self, file, update_callback,
                 total_count=20,
                 update_count=5,
                 update_time=1,
                 buffer_time=5):
        self._name = file
        self._reader_future = self._reader(file)
        if buffer_time > 0:
            self._stale_buffer = deque()
        else:
            self._stale_buffer = None
        total_count = max(int(total_count), 0)
        self.update_count = min(max(int(update_count), 0), total_count)
        self._active_buffer = deque(maxlen=total_count)
        self.update_callback = update_callback
        self.update_time = max(update_time, 0)
        self.updater = asyncio.create_task(self._update_coro())
        self.start_time = self.current_time = None

    def _reader(self, file):
        def read():
            import json
            try:
                with open(file, encoding="utf-8") as f:
                    file_content = f.read(1024)
                    if file_content[0] != '{':
                        logging.error("the danmaku file must be JSON format starting with '{'")
                        return
                    file_content += f.read(20 << 20)  # avoid OOM if a very large text file is wrongly fed
                data = json.loads(file_content)['data']
                data = [(i[0], i[4]) for i in data]
                data.sort()
                self.data = data
            except UnicodeDecodeError:
                logging.error(f"danmaku is not a valid utf-8 encoded file")
            except Exception as e:
                logging.error(f"danmaku load failed: {repr(e)}")
            finally:
                if not self.data:
                    self.data = [(0, "弹幕加载失败")]

        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, read)

    async def _update_coro(self):
        try:
            await self._reader_future
            # wait until start_time & current_time is set
            while self.start_time is None or self.current_time is None:
                logging.debug(f"danmaku {self._name} is loaded but not started")
                await asyncio.sleep(0.5)
            self.start_time: float  # type hint
            self.current_time: float  # type hint
            logging.info(f"start streaming danmaku file: {self._name}")
            count = self.update_count
            for data_i in self.data:
                while data_i[0] > self.current_time - self.start_time:
                    await self._do_update(count)
                    count = self.update_count
                    await asyncio.sleep(self.update_time)
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

    async def _do_update(self, count):
        if count > 0:
            logging.info(f"New danmaku is not enough. Fill {count} slots from buffer.")
            while count > 0 and self._stale_buffer:
                self._active_buffer.append(self._stale_buffer.pop()[1])
                count -= 1
            if count > 0:
                logging.warning(f"Danmaku is not enough. {count} in {self.update_count} is not updated")
        await self.update_callback('\n'.join(self._active_buffer))
