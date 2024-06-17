import asyncio
from asyncio import PriorityQueue
import os
import traceback
from typing import Optional, TypedDict, Literal
import logging
import av

from .danmaku import Danmaku
from .utils import video_opener, Progress, iter_to_thread

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
    offset: float
    _last_ptime: AVFloat
    _last_dtime: AVFloat
    queue: PriorityQueue[tuple[float, Literal['video', 'audio'], av.Packet]]
    _offset_ts: AVInt
    __audio_buffer: list
    switching: asyncio.Event

    def __init__(self, queue):
        self.offset = 0.
        self.queue = queue
        self._offset_ts = {'video': None, 'audio': None}
        self.__audio_buffer = []
        self._last_ptime = {'video': 0., 'audio': 0.}
        self._last_dtime = {'video': 0., 'audio': 0.}
        self.switching = asyncio.Event()

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
        self.switching.clear()

    async def put(self, pkt: av.Packet):
        """
        Modify the packet timestamp and put into `self.queue`

        :param pkt: the packet to put
        :return: None
        """
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
                self.switching.set()

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
                        await self.queue.put((old_pkt_dtime, pkt_type, old_pkt))
                    self.__audio_buffer.clear()

        pkt.dts += self._offset_ts[pkt_type]
        pkt.pts += self._offset_ts[pkt_type]
        self._last_dtime[pkt_type] = dtime = float(pkt.dts) * pkt.time_base
        self._last_ptime[pkt_type] = float(pkt.pts) * pkt.time_base
        await self.queue.put((dtime, pkt_type, pkt))


class Player:
    container: av.container = None
    streams: Optional[dict]
    _buffer: PriorityQueue
    _demux_task: Optional[asyncio.Task] = None
    _mux_task: Optional[asyncio.Task] = None
    _packet_modifier: PacketTimeModifier = None
    _danmaku: Optional[Danmaku]

    def __init__(self, flv_url, buffer_size=600):
        self._flv_url = flv_url
        self._open_container()
        self._buffer = PriorityQueue(buffer_size)
        self._packet_modifier = PacketTimeModifier(self._buffer)
        self._mux_task = asyncio.create_task(self._muxer())
        self._danmaku = None
        asyncio.create_task(self._watchdog())

    def _open_container(self):
        if self.container is not None:
            try:
                self.container.close()
            except Exception as e:
                logging.warning(f"Ignoring the exception {repr(e)} during closing the old container.")
                traceback.print_exc()
        self.container = av.open(self._flv_url, mode='w', format='flv')
        self.streams = {}

    async def _muxer(self):
        _loop = asyncio.get_running_loop()
        _count = 0
        while not self.streams:
            logging.debug('muxer waiting for start')
            await asyncio.sleep(0.1)
        start_time = None
        while True:
            pkt_time, pkt_type, pkt = await self._buffer.get()
            if start_time is None:  # set start_time when the first packet arrives or after restarting
                start_time = _loop.time() - pkt_time
            wait = start_time + pkt_time - _loop.time()
            logging.debug(f'mux {pkt_type} pkt {_count}, '
                          f'play at time {pkt_time:.3f}s, wait for {wait:.3f}s, '
                          f'{pkt.dts=}, {pkt.pts=}, {pkt.time_base=}')
            if wait > 0:
                await asyncio.sleep(wait)
            elif wait < -0.1:
                if wait > -5:
                    logging.warning(f"muxing is too slow and out of sync for {-wait:.3f}s, "
                                    f"current buffer size {self._buffer.qsize()}")
                else:
                    logging.error(f"out of sync for too long ({-wait:.3f}s). resetting the start time.")
                    start_time = None

            if self._danmaku is not None:
                self._danmaku.current_time = pkt_time
            _count += 1

            # Any exception during muxing will be ignored.
            # The exception should be caused by a broken container, so the `self.container` will be reset.
            # Note that CancelledError is a BaseException but NOT an Exception
            try:
                self.container.mux(pkt)
            except Exception:
                logging.error(f"Get an exception during muxing. Restarting.")
                traceback.print_exc()
                old_streams = self.streams
                self._open_container()
                for t in ['video', 'audio']:
                    self.streams[t] = self.container.add_stream(template=old_streams[t])
                start_time = None
                _count = 0

    async def _demuxer(self, input_name, *,
                       flush_buffer=True, stream_loop=-1, progress_aiter,
                       start_callback=None, fail_callback=None):
        async def _set_danmaku_start():
            await self._packet_modifier.switching.wait()
            self._danmaku.start_time = self._packet_modifier.offset

        def new_video_init(input_container):
            nonlocal started, flush_buffer
            if not started:  # at the first beginning
                started = True
                self._packet_modifier.switch(flush_buffer=flush_buffer)
                if start_callback is not None:
                    start_callback()
                progress_aiter.add_message(f"开始播放", final=True)

                # streams compatibility test
                if self.streams:
                    out_astream = self.streams['audio']
                    out_vstream = self.streams['video']
                    in_astream = input_container.streams.audio[0]
                    in_vstream = input_container.streams.video[0]
                    compatible = (
                        in_astream.sample_rate == out_astream.sample_rate and
                        in_vstream.width == out_vstream.width and
                        in_vstream.height == out_vstream.height
                    )
                    if not compatible:
                        logging.info("Audio/Video format changed. Reopen the container")
                        self._open_container()
                # add streams to the container
                if not self.streams:
                    self.streams = {}
                    for t in ['video', 'audio']:
                        in_stream = getattr(input_container.streams, t)[0]
                        self.streams[t] = self.container.add_stream(template=in_stream)
                        logging.info(f"{t} stream added, template={in_stream}")

            else:  # loop
                self._packet_modifier.switch(flush_buffer=False)  # do not flush the buffer when looping
                if self._danmaku is not None:
                    self._danmaku.restart()
            if self._danmaku is not None:
                _loop.create_task(_set_danmaku_start())

        async def demux_with_retry():
            fail = 0
            while True:
                i = 0
                try:
                    async with video_opener(input_name, metadata_errors='ignore', timeout=(10, 3)) as input_container:
                        new_video_init(input_container)
                        async for i, packet in iter_to_thread(enumerate(input_container.demux())):
                            packet: av.Packet
                            if packet.dts is not None:
                                logging.debug(f'put {packet.stream.type} pkt {i}, raw {packet.pts=}, raw {packet.dts=}')
                                await self._packet_modifier.put(packet)
                    return  # do NOT retry if finish successfully
                except av.AVError as e:
                    fail += 1
                    # retry if the stream has already been played for a while and at most 3 times
                    if i > 60 and fail <= 3:
                        logging.warning(f"An exception occurred during demuxing: {e!r}, retrying {fail} ...")
                        await asyncio.sleep(5)
                    else:
                        raise

        started = False
        _loop = asyncio.get_running_loop()
        try:
            # test file name first
            if input_name.startswith("http"):
                from urllib import request, parse, error
                try:
                    await asyncio.to_thread(
                        request.urlopen, parse.quote(input_name, safe=':/?&='), timeout=10)
                except error.URLError as e:
                    logging.warning(f"cannot open URL {input_name}: {e!r}")
                    exists = False
                except Exception as e:
                    logging.error(f"Unexpected error during url testing: {e!r}")
                    exists = False
                else:
                    exists = True
            else:
                exists = await asyncio.to_thread(os.path.exists, input_name)
            if exists:
                progress_aiter.add_message("已找到视频文件，正在打开...")
                logging.debug(f"{input_name} exists, opening...")
            else:
                progress_aiter.add_message("视频文件不存在", final=True)
                logging.warning(f"{input_name} does not exist")
                return

            # open, decode, and push the stream
            stream_loop = int(stream_loop)
            while stream_loop != 0:
                stream_loop -= 1
                await demux_with_retry()
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
            if self._danmaku is not None:
                self._danmaku.updater.cancel()
            self._danmaku = danmaku

        def fail_callback():  # continue to demux the old video if the new one is invalid
            self._demux_task = old_demux_task

        # refuse to play if muxer is already dead
        if self._mux_task is None or self._mux_task.done():
            raise RuntimeError(f"cannot play since the muxer of the player is dead")
        # expose the TypeError as early as possible
        if not (danmaku is None or isinstance(danmaku, Danmaku)):
            raise TypeError(f"danmaku must be a Danmaku object, not a {type(danmaku)}")

        if progress_aiter is None:
            # create a placeholder
            progress_aiter = Progress()
            progress_aiter.finished = True
        elif not isinstance(progress_aiter, Progress):
            raise TypeError(f"progress_aiter must be a Progress object, not a {type(progress_aiter)}")

        old_demux_task = self._demux_task
        self._demux_task = asyncio.create_task(self._demuxer(
            file,
            progress_aiter=progress_aiter,
            start_callback=start_callback,
            fail_callback=fail_callback
        ))

    async def _watchdog(self):
        while self._mux_task is not None:  # otherwise self is already closed
            if self._mux_task.done():
                try:
                    await self._mux_task
                except BaseException:
                    logging.error("mux task got an exception and is exited")
                    traceback.print_exc()
                else:
                    logging.error("mux task finished unexpectedly")
                finally:
                    self.close()
                return
            if self._demux_task and self._demux_task.done():
                try:
                    await self._demux_task
                except BaseException:
                    logging.error("demux task got an exception and is exited")
                    traceback.print_exc()
                else:
                    logging.debug("demux task is finished")
                finally:
                    self._demux_task = None  # only report the error once
            await asyncio.sleep(1)

    def close(self):
        logging.info('Player is closing')
        self._mux_task.cancel()
        self._demux_task.cancel()
        self._mux_task = self._demux_task = None
        if self._danmaku is not None:
            self._danmaku.updater.cancel()
        self.container.close()

    def __del__(self):
        self.close()
