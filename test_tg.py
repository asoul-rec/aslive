import asyncio
import json
import logging
import os.path

from pyrogram import Client, filters, idle
from player import Player
import time

logging.basicConfig(format='%(asctime)s [%(levelname).1s] [%(name)s] %(message)s', level=logging.INFO)

with open("config.json") as conf_f:
    config = json.load(conf_f)

app = Client("aslive", api_id=config['api_id'], api_hash=config['api_hash'],
             bot_token=config['bot_token'])

async def init():
    global player
    player = Player(config['rtmp_server'])
    async with app:
        await idle()


@app.on_message(filters.command("start"))
async def start_command(client, message):
    print("This is the /start command")


@app.on_message(filters.command("help"))
async def help_command(client, message):
    print("This is the /help command")


@app.on_message(filters.user(config['tg_uid']['me2']) & filters.private)
async def change_video(client, message):
    if os.path.exists(message.text):
        player.play_now(message.text)
        await message.reply("success")
    else:
        await message.reply(f"unknown file {message.text}")


# @app.on_message(filters.text & filters.private)
# async def echo(client, message):
#     reply = await message.reply(message)
#     # for i in range(100):
#     #     await reply.edit_text(f"{time.time()}\n" * 20)
#
#
# @app.on_message(filters.outgoing)
# async def lo(client, message):
#     logging.info(f"{message}")


app.run(init())
