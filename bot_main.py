import asyncio
import json
import logging

from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from player import Player, Progress, Danmaku
from bot_lib import update_message, app_group

logging.basicConfig(format='%(asctime)s [%(levelname).1s] [%(name)s] %(message)s', level=logging.INFO)
logging.getLogger('pyrogram').setLevel(logging.WARNING)

with open("config.json") as conf_f:
    config = json.load(conf_f)

apps = [Client(bot_i['name'], api_id=config['api_id'], api_hash=config['api_hash'],
               bot_token=bot_i['token']) for bot_i in config['bot']]
app = apps[0]


async def init():
    global player
    logging.info("starting aslive bot v230429")
    player = Player(config['rtmp_server'])
    async with app_group(apps):
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
    channel_ids = config['test_channel']
    edit_callable = update_message.polling(apps, channel_ids['chat_id'], channel_ids['message_id']['danmaku'])
    video_path = f'/rec/{dir_name}/transcoded/hq.mp4'
    progress_aiter = Progress()
    reply = await message.reply(f"正在寻找视频文件...")
    try:
        player.play_now(
            video_path,
            progress_aiter=progress_aiter,
            danmaku=Danmaku(
                f'/rec/{dir_name}/transcoded/danmaku.json', edit_callable,
                update_time=3 / len(apps),
                update_count=2
            )
        )
        async for pg in progress_aiter:
            await reply.edit_text(pg)
        logging.info(f"Finished processing {message.text}")
    except RuntimeError:
        await reply.edit_text(f"服务器错误，退出程序")
        asyncio.create_task(app.stop())
        raise


if __name__ == '__main__':
    app.run(init())
