import asyncio

import av
import json
import time
from asyncio import PriorityQueue
import logging

import player

logging.basicConfig(format='%(asctime)s [%(levelname).1s] [%(name)s] %(message)s', level=logging.DEBUG)
logging.getLogger('libav').setLevel(logging.INFO)


async def real_print(x):
    print(x)


async def test_print(x):
    while True:
        await real_print(x)


async def clear(q):
    await asyncio.sleep(0)
    for i in range(q.qsize()):
        q.get_nowait()
    assert q.empty()
    q.put_nowait([-1000])


async def putter(q):
    for i in range(10):
        if i == 0:
            await clear(q)
        await q.put([None])
        print(i)


async def main():
    with open("config.json") as conf_f:
        config = json.load(conf_f)
    p = player.Player(config['rtmp_server'])
    # p = player.Player("test_out.flv")

    while True:
        p.play_now("op1.mp4")
        await asyncio.sleep(10)
        # p.play_now("op2.mp4")
        # await asyncio.sleep(5)
        p.play_now("op3.mp4")
        await asyncio.sleep(10)
        p.play_now("ed4.mp4")
        await asyncio.sleep(10)


if __name__ == '__main__':
    asyncio.run(main())
