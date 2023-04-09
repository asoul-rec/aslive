import asyncio
import json
import logging
import os.path

from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode, ChatType
from pyrogram.types import Message, Chat
import functools

import player
from player import Player, Progress
import time

logging.basicConfig(format='%(asctime)s [%(levelname).1s] [%(name)s] %(message)s', level=logging.INFO)

with open("config.json") as conf_f:
    config = json.load(conf_f)

app = Client("aslive", api_id=config['api_id'], api_hash=config['api_hash'],
             bot_token=config['bot_token'])


async def init():
    async with app:
        channel_ids = config['test_channel']
        edit_callable = functools.partial(
            app.edit_message_text,
            channel_ids['chat_id'],
            channel_ids['message_id']['danmaku'],
            parse_mode=ParseMode.DISABLED,
            disable_web_page_preview=True
        )

        de = player.Danmaku("./test.json", edit_callable, update_time=3)
        await idle()


async def danmaku_renderer():
    pass

app.run(init())
