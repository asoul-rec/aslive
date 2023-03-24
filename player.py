import asyncio
from asyncio import PriorityQueue
import logging
import av
import traceback


class Player:
    container: av.container
    streams: dict = None
    _buffer: PriorityQueue
    _demux_task: asyncio.Task = None
    _mux_task: asyncio.Task = None

    def __init__(self, flv_url, buffer_size=300):
        self.container = av.open(flv_url, mode='w', format='flv')
        self.streaming_time = 0
        self._buffer = PriorityQueue(buffer_size)
        self._mux_task = asyncio.create_task(self._muxer())
        asyncio.create_task(self._watchdog())

    async def _muxer(self):
        _loop = asyncio.get_running_loop()
        _count = 0
        offset = last_pkt_time = 0
        offset_ts = {'video': None, 'audio': None}
        while not self.streams:
            logging.debug('muxer waiting for start')
            await asyncio.sleep(0.1)
        start_time = _loop.time()
        while True:
            pkt_time, pkt_type, pkt = await self._buffer.get()
            if pkt_type == 'switch':
                logging.info('muxer switch to a new offset')
                offset += last_pkt_time
                offset_ts = {'video': None, 'audio': None}
                continue
            # if pkt is None:
            #     return
            if not offset_ts[pkt_type]:
                offset_ts[pkt_type] = offset / pkt.time_base
            pkt.dts += offset_ts[pkt_type]
            pkt.pts += offset_ts[pkt_type]
            pkt.stream = self.streams[pkt_type]

            if (wait := start_time + offset + pkt_time - _loop.time()) > 0:
                await asyncio.sleep(wait)
            else:
                if wait < -0.1:
                    logging.warning(f"muxing is too slow and out of sync for {-wait:.3f}s")
            logging.debug(f'mux {pkt_type} pkt {_count}, '
                          f'play at time {float(pkt_time + offset):.3f}s,'
                          f'wait for {wait:.3f}s, '
                          f'{pkt.dts=}, {pkt.pts=}, {pkt.time_base=}')
            self.container.mux(pkt)
            last_pkt_time = pkt_time
            _count += 1

    async def _demuxer(self, input_name):
        with av.open(input_name) as input_container:
            if not self.streams:
                self.streams = {}
                for t in ['video', 'audio']:
                    in_stream = getattr(input_container.streams, t)[0]
                    self.streams[t] = self.container.add_stream(template=in_stream)
                    logging.info(f"{t} stream added, template={in_stream}")
            for i, packet in enumerate(input_container.demux()):
                packet: av.Packet
                if packet.dts is not None:
                    if packet.dts < 0:
                        logging.warning("may have problems when processing negative dts")
                    pkt_type = packet.stream.type
                    if i == 0:  # clear when first packet arrives
                        await self._clear_queue()
                    logging.debug(f'put {pkt_type} pkt {i}, raw {packet.pts=}, raw {packet.dts=}')
                    pkt_time = packet.dts * packet.time_base
                    await self._buffer.put([pkt_time, pkt_type, packet])  # add `pkt_type` to avoid time collision
                    await asyncio.sleep(0)

    async def _clear_queue(self):
        await asyncio.sleep(0)  # let the getter wait as short as possible
        for i in range(self._buffer.qsize()):
            self._buffer.get_nowait()
        assert self._buffer.empty()
        self._buffer.put_nowait([float('-inf'), 'switch', None])
        logging.debug('queue cleared')

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
                logging.error("demux task finished unexpectedly")
                self.close()
                logging.error(self._demux_task)
                return

            await asyncio.sleep(0.5)


    def close(self):
        logging.info('Player is closing')
        self._mux_task.cancel()
        self._demux_task.cancel()
        self.container.close()

    def __del__(self):
        self.close()
