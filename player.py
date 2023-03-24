import asyncio
from asyncio import PriorityQueue
# from contextlib import asynccontextmanager
# import traceback
from typing import Optional, TypedDict, Literal
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
    _offset: float = 0
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

        logging.info(f'switch to a new offset, previous {self._offset:.3f}s')
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
                old_offset = self._offset  # debug only
                self._offset = max(self._last_dtime['video'] - raw_dt, self._last_ptime['video'] - raw_pt)
                self._offset += 1 / 60  # delay one typical frame time
                self._offset_ts[pkt_type] = int(self._offset / pkt.time_base)
                logging.debug(f"old_offset {old_offset:.3f}s, new offset {self._offset:.3f}s, "
                              f"first video packet dt={raw_dt:.3f}s, pt={raw_pt:.3f}s")

            if pkt_type == 'audio':
                if self._offset_ts['video'] is None:  # offset should be decided by video stream start time
                    self.__audio_buffer.append(pkt)
                    return
                else:
                    self._offset_ts[pkt_type] = int(self._offset / pkt.time_base)
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
            # if pkt_type == 'switch':
            #     logging.info('muxer switch to a new offset')
            #     offset += last_pkt_time
            #     offset_ts = {'video': None, 'audio': None}
            #     continue
            # if pkt is None:
            #     return
            # if not offset_ts[pkt_type]:
            #     offset_ts[pkt_type] = offset / pkt.time_base
            # pkt.dts += offset_ts[pkt_type]
            # pkt.pts += offset_ts[pkt_type]
            # pkt.stream = self.streams[pkt_type]

            if (wait := start_time + pkt_time - _loop.time()) > 0:
                await asyncio.sleep(wait)
            else:
                if wait < -0.1:
                    logging.warning(f"muxing is too slow and out of sync for {-wait:.3f}s")
            logging.debug(f'mux {pkt_type} pkt {_count}, '
                          f'play at time {pkt_time:.3f}s, wait for {wait:.3f}s, '
                          f'{pkt.dts=}, {pkt.pts=}, {pkt.time_base=}')
            self.container.mux(pkt)
            _count += 1

    async def _demuxer(self, input_name, flush_buffer=True, loop=-1):
        loop = int(loop)
        while loop != 0:
            loop -= 1
            with av.open(input_name, metadata_errors='ignore') as input_container:
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
                        if i == 0:  # clear when first packet arrives
                            self._packet_modifier.switch(flush_buffer)
                            flush_buffer = False  # do not flush the buffer when looping
                        logging.debug(f'put {pkt_type} pkt {i}, raw {packet.pts=}, raw {packet.dts=}')
                        await self._packet_modifier.put(packet)
                        await asyncio.sleep(0)

    # async def _switch(self, flush_buffer):
    # switch_item = [float('-inf'), 'switch', None]
    # if flush_buffer:
    #     await asyncio.sleep(0)
    #     for i in range(self._buffer.qsize()):
    #         self._buffer.get_nowait()
    #     assert self._buffer.empty()
    #     self._buffer.put_nowait(switch_item)
    # else:
    #     await self._buffer.put(switch_item)
    #
    # logging.debug('queue cleared')

    def play_now(self, file):
        if self._demux_task is not None:
            self._demux_task.cancel()
        self._demux_task = asyncio.create_task(self._demuxer(file))

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
