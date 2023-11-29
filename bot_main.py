import asyncio
import json
import logging

from pyrogram import Client, filters, idle
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode
from player import Player, Progress, Danmaku
from bot_lib import update_message, app_group, edit_group_call_title
import selector

logging.basicConfig(format='%(asctime)s [%(levelname).1s] [%(name)s] %(message)s', level=logging.INFO)
logging.getLogger('pyrogram').setLevel(logging.WARNING)

with open("config.json") as conf_f:
    config = json.load(conf_f)

apps = [Client(bot_i['name'], api_id=config['api_id'], api_hash=config['api_hash'],
               bot_token=bot_i['token'], parse_mode=ParseMode.DISABLED) for bot_i in config['bot']]
bot0 = apps[0]
user = Client('user1', api_id=config['api_id'], api_hash=config['api_hash'],
              phone_number=config['user'][1]["phone_number"], no_updates=True)


async def init():
    global player
    logging.info("starting aslive bot v231129")
    player = Player(config['rtmp_server'])
    async with app_group([*apps, user]):
        await idle()


@bot0.on_message((filters.command("help") | filters.command("start")) & filters.chat(config['test_group']['chat_id']))
async def help_command(_, message):
    await message.reply("Usage: `/play video_name`\nAll available `video_name`s are in the group file.")


@bot0.on_message(filters.command("play") & filters.chat(config['test_group']['chat_id']))
async def change_video(_, message):
    name = message.text.split(maxsplit=1)[1:]
    if name:
        name = name[0].strip()
        await play_live(name, await message.reply("正在寻找视频文件..."))
    else:
        await message.reply("Usage: `/play video_name`")


@bot0.on_message((filters.command("select")))
async def sel_command(_, message: Message):
    reply = selector.build_reply()
    if reply.pop('status') == 0:
        await message.reply(**reply)


@bot0.on_callback_query(filters.regex(selector.sel_date_regex))
async def sel_update(_, callback_query: CallbackQuery):
    match = callback_query.matches[0]
    reply = selector.build_reply(*match.groups())
    match reply.pop('status'):
        case 0:
            await callback_query.message.edit_text(**reply)
        case 1:
            name = reply['text']
            logging.info(f"live selected: {name}")
            await callback_query.message.edit_text("正在寻找视频文件...")
            await play_live(name, callback_query.message)
        case _:
            await callback_query.message.edit_text("selector failed")


@bot0.on_callback_query()
async def report_error(_, callback_query: CallbackQuery):
    logging.error(f"cannot process this callback query, data={callback_query.data}")
    await callback_query.message.edit_text("failed")


async def play_live(name: str, reply_message: Message = None):
    channel_ids = config['test_channel']
    edit_callable = update_message.polling(apps, channel_ids['chat_id'], channel_ids['message_id']['danmaku'])
    video_path = f'/rec/{name}/transcoded/hq.mp4'
    progress_aiter = None if reply_message is None else Progress()
    try:
        player.play_now(
            video_path,
            progress_aiter=progress_aiter,
            danmaku=Danmaku(
                f'/rec/{name}/transcoded/danmaku.json', edit_callable,
                total_count=config['danmaku']['total_count'],
                update_interval=config['danmaku']['update_interval'],
                update_count=config['danmaku']['update_count'],
            )
        )
        if reply_message is not None:
            async for pg in progress_aiter:
                await reply_message.edit_text(pg)
        try:
            await edit_group_call_title(user, channel_ids['chat_id'], name[9:])
        except Exception as e:
            logging.error(f"got exception \"{e!r}\" when editing the call title, ignored")
        logging.info(f"Finished processing {name}")
    except RuntimeError:
        if reply_message is not None:
            await reply_message.edit_text(f"服务器错误，退出程序")
        asyncio.create_task(bot0.stop())
        raise


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    run = loop.run_until_complete(init())
