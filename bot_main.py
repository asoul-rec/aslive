import asyncio
import json
import logging
import os.path

from pyrogram import Client, filters, idle
from player import Player, Progress
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


@app.on_message((filters.command("help") | filters.command("start")) & filters.chat(config['test_group']['chat_id']))
async def help_command(client, message):
    await message.reply("Usage: `/play video_name`\nAll available `video_name`s are in the group file.")


@app.on_message(filters.command("play") & filters.chat(config['test_group']['chat_id']))
async def change_video(client, message):
    dir_name = message.text.split(maxsplit=1)[1:]
    if dir_name:
        dir_name = dir_name[0].strip()
    else:
        await message.reply("Usage: `/play video_name`")
    video_path = f'/rec/{dir_name}/transcoded/hq.mp4'
    progress_aiter = Progress()
    reply = await message.reply(f"正在寻找视频文件...")
    player.play_now(video_path, progress_aiter=progress_aiter)
    async for pg in progress_aiter:
        await reply.edit_text(pg)
    # await message.reply("debug: finished")


app.run(init())
