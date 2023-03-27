import asyncio
from asyncio import PriorityQueue, Queue
from contextlib import asynccontextmanager
import functools
import os
# import traceback
from typing import Optional, TypedDict, Literal
from collections import deque
import logging
import av

AVFloat = TypedDict('AVFloat', {'video': Optional[float], 'audio': Optional[float]})
AVInt = TypedDict('AVInt', {'video': Optional[int], 'audio': Optional[int]})


class PacketTimeModifier:
    """
    Modify the timestamp to connect several files
    Make sure:
        1. The earliest video keyframe should follow the previous video packet as close as possible but not earlier
        2. Video/Audio offset should be the same or very close (threshold +- 0.1s)
        3. Make the gap of audio stream (if exists) as small as possible
    """
    offset: float = 0
    _last_ptime: AVFloat = {'video': 0., 'audio': 0.}
    _last_dtime: AVFloat = {'video': 0., 'audio': 0.}
    queue: PriorityQueue
    _offset_ts: AVInt
    __audio_buffer: list

    def __init__(self, queue):
        self.queue = queue
        self._offset_ts = {'video': None, 'audio': None}
        self.__audio_buffer = []

    def switch(self, flush_buffer=False):
        if flush_buffer and (queue_size := self.queue.qsize()) > 2:
            flag = 0
            for item in [self.queue.get_nowait() for _ in range(queue_size)]:
                pkt_dtime, pkt_type, pkt = item
                flag |= {'video': 1, 'audio': 2}[pkt_type]
                self._last_dtime[pkt_type] = pkt_dtime
                self._last_ptime[pkt_type] = float(pkt.pts) * pkt.time_base
                self.queue.put_nowait(item)
                if flag == 3:
                    break
            logging.info(f"Buffer flushed, previous size {queue_size}, current size {self.queue.qsize()}")

        logging.info(f'switch to a new offset, previous {self.offset:.3f}s')
        self._offset_ts = {'video': None, 'audio': None}
        # Clear the audio_buffer since it is useless if a new switching happens before the first video keyframe comes
        self.__audio_buffer.clear()

    async def put(self, pkt):
        pkt_type: Literal['video', 'audio'] = pkt.stream.type
        if pkt_type not in ['video', 'audio']:
            return
        if self._offset_ts[pkt_type] is None:
            if pkt_type == 'video':
                if not pkt.is_keyframe:  # never mux a non-keyframe as the first packet
                    return
                raw_pt = float(pkt.pts) * pkt.time_base
                raw_dt = float(pkt.dts) * pkt.time_base
                if raw_pt < 0:
                    logging.info(f"skip keyframe with negative present time t={raw_pt:.3f}s")
                    return
                if raw_pt > 5:
                    logging.warning(f"new video stream start very late at t={raw_pt:.3f}s")
                old_offset = self.offset  # debug only
                self.offset = max(self._last_dtime['video'] - raw_dt, self._last_ptime['video'] - raw_pt)
                self.offset += 1 / 60  # delay one typical frame time
                self._offset_ts[pkt_type] = int(self.offset / pkt.time_base)
                logging.debug(f"old_offset {old_offset:.3f}s, new offset {self.offset:.3f}s, "
                              f"first video packet dt={raw_dt:.3f}s, pt={raw_pt:.3f}s")

            if pkt_type == 'audio':
                if self._offset_ts['video'] is None:  # offset should be decided by video stream start time
                    self.__audio_buffer.append(pkt)
                    return
                else:
                    self._offset_ts[pkt_type] = int(self.offset / pkt.time_base)
                    for old_pkt in self.__audio_buffer:
                        old_pkt.dts += self._offset_ts[pkt_type]
                        old_pkt.pts += self._offset_ts[pkt_type]
                        old_pkt_dtime = float(old_pkt.dts) * old_pkt.time_base
                        if old_pkt_dtime < self._last_dtime[pkt_type] + 0.021:  # aac frame 1024 samples / 48000 Hz
                            continue
                        await self.queue.put([old_pkt_dtime, pkt_type, old_pkt])
                    self.__audio_buffer.clear()

        pkt.dts += self._offset_ts[pkt_type]
        pkt.pts += self._offset_ts[pkt_type]
        self._last_dtime[pkt_type] = dtime = float(pkt.dts) * pkt.time_base
        self._last_ptime[pkt_type] = float(pkt.pts) * pkt.time_base
        await self.queue.put([dtime, pkt_type, pkt])


class Player:
    container: av.container
    streams: dict = None
    _buffer: PriorityQueue
    _demux_task: asyncio.Task = None
    _mux_task: asyncio.Task = None
    _packet_modifier: PacketTimeModifier = None

    def __init__(self, flv_url, buffer_size=600):
        self._flv_url = flv_url
        self.container = av.open(flv_url, mode='w', format='flv')
        self.streaming_time = 0
        self._buffer = PriorityQueue(buffer_size)
        self._packet_modifier = PacketTimeModifier(self._buffer)
        self._mux_task = asyncio.create_task(self._muxer())
        asyncio.create_task(self._watchdog())

    async def _muxer(self):
        _loop = asyncio.get_running_loop()
        _count = 0
        while not self.streams:
            logging.debug('muxer waiting for start')
            await asyncio.sleep(0.1)
        start_time = _loop.time()
        while True:
            pkt_time, pkt_type, pkt = await self._buffer.get()

            if (wait := start_time + pkt_time - _loop.time()) > 0:
                await asyncio.sleep(wait)
            else:
                if wait < -0.1:
                    logging.warning(f"muxing is too slow and out of sync for {-wait:.3f}s, "
                                    f"current buffer size {self._buffer.qsize()}")
            logging.debug(f'mux {pkt_type} pkt {_count}, '
                          f'play at time {pkt_time:.3f}s, wait for {wait:.3f}s, '
                          f'{pkt.dts=}, {pkt.pts=}, {pkt.time_base=}')
            try:
                self.container.mux(pkt)
            except Exception as e:
                logging.error(f"{type(e)}: {e}")
                self.container = av.open(self._flv_url, mode='w', format='flv')
                self.container.mux(pkt)
            _count += 1

    async def _demuxer(self, input_name, *,
                       flush_buffer=True, stream_loop=-1, progress_aiter,
                       start_callback=None, fail_callback=None):
        def new_video_init():
            nonlocal started, flush_buffer
            if not started:  # at the first beginning
                started = True
                self._packet_modifier.switch(flush_buffer=flush_buffer)
                if start_callback is not None:
                    start_callback()
                progress_aiter.add_message(f"开始播放", final=True)
            else:  # loop
                self._packet_modifier.switch(flush_buffer=False)  # do not flush the buffer when looping

        started = False
        try:
            # test file name first
            _loop = asyncio.get_running_loop()
            exists = await _loop.run_in_executor(None, os.path.exists, input_name)
            if exists:
                progress_aiter.add_message("已找到视频文件，正在打开...")
            else:
                progress_aiter.add_message("视频文件不存在", final=True)
                return

            # open, decode, and push the stream
            stream_loop = int(stream_loop)
            while stream_loop != 0:
                stream_loop -= 1
                async with video_opener(input_name, metadata_errors='ignore') as input_container:
                    if not self.streams:
                        self.streams = {}
                        for t in ['video', 'audio']:
                            in_stream = getattr(input_container.streams, t)[0]
                            self.streams[t] = self.container.add_stream(template=in_stream)
                            logging.info(f"{t} stream added, template={in_stream}")
                    for i, packet in enumerate(input_container.demux()):
                        packet: av.Packet
                        if packet.dts is not None:
                            pkt_type = packet.stream.type
                            if i == 0:
                                new_video_init()
                            logging.debug(f'put {pkt_type} pkt {i}, raw {packet.pts=}, raw {packet.dts=}')
                            await self._packet_modifier.put(packet)
                            await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            progress_aiter.add_message("播放失败", final=True)
            raise
        finally:
            if not started:
                progress_aiter.add_message("未播放", final=True)
                if fail_callback is not None:
                    fail_callback()

    def play_now(self, file, progress_aiter=None, danmaku=None):
        def start_callback():
            if old_demux_task is not None:
                old_demux_task.cancel()

        def fail_callback():
            self._demux_task = old_demux_task

        if progress_aiter is None:
            progress_aiter = Progress()
            progress_aiter.finished = True  # Progress placeholder

        old_demux_task = self._demux_task
        self._demux_task = asyncio.create_task(self._demuxer(
            file,
            progress_aiter=progress_aiter,
            start_callback=start_callback,
            fail_callback=fail_callback
        ))

    async def _watchdog(self):
        while True:
            if self._mux_task and self._mux_task.done():
                logging.error("mux task finished unexpectedly")
                self.close()
                logging.error(self._mux_task)
                return

            if self._demux_task and self._demux_task.done():
                logging.info("demux task finished")
                #     logging.error("demux task finished unexpectedly")
                #     self.close()
                logging.error(self._demux_task)
            #     return

            await asyncio.sleep(0.5)

    def close(self):
        logging.info('Player is closing')
        self._mux_task.cancel()
        self._demux_task.cancel()
        self.container.close()

    def __del__(self):
        self.close()


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


class Danmaku:
    data = None
    _reader_future: asyncio.Future
    _stale_buffer: deque[tuple[float, str]] = None
    _active_buffer: deque[str]
    update_callback: callable
    update_count: int
    update_time: float

    def __init__(self, file, update_callback, total_count=20, update_count=5, update_time=1, buffer_time=5):
        self._reader_future = self._reader(file)
        if buffer_time > 0:
            self._stale_buffer = deque()
        total_count = max(int(total_count), 0)
        self.update_count = min(max(int(update_count), 0), total_count)
        self._active_buffer = deque(maxlen=total_count)
        self.update_callback = update_callback
        self.update_time = max(update_time, 0)
        asyncio.create_task(self.updater())

    def _reader(self, file):
        def read():
            import json
            with open(file, encoding="utf-8") as f:
                data = json.load(f)['data']
                data = [(i[0], i[4]) for i in data]
                data.sort()
                self.data = data

        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, read)

    async def updater(self):
        def fill_from_buffer():
            nonlocal count
            if count > 0:
                logging.info(f"New danmaku is not enough. Fill {count} slots from buffer.")
                while count > 0 and self._stale_buffer:
                    self._active_buffer.append(self._stale_buffer.pop()[1])
                    count -= 1
                if count > 0:
                    logging.warning(f"Danmaku is not enough. {count} in {self.update_count} is not updated")
        loop = asyncio.get_running_loop()
        await self._reader_future
        start_time = loop.time()
        await asyncio.sleep(self.update_time)
        current_time = loop.time()
        count = self.update_count
        for data_i in self.data:
            if data_i[0] > current_time - start_time:
                fill_from_buffer()
                await self.update_callback('\n'.join(self._active_buffer))
                count = self.update_count
                await asyncio.sleep(self.update_time)
                current_time = loop.time()
            if count > 0:
                self._active_buffer.append(data_i[1])
            else:
                self._stale_buffer.append(data_i)
            count -= 1



