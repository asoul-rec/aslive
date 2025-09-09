import asyncio
import argparse
import contextlib
import functools
import json
import logging

from pyrogram import Client, filters, idle
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode
import asrec_telegram
from asrec_telegram import open_telegram

from bot_lib import update_message, app_group, edit_group_call_title, get_rtmp_url, restart_group_call
from player import Player, Progress, Danmaku
import selector

logging.basicConfig(format='%(asctime)s [%(levelname).1s] [%(name)s] %(message)s', level=logging.INFO)
logging.getLogger('pyrogram').setLevel(logging.WARNING)

with open("config.json") as conf_f:
    config = json.load(conf_f)

bots = [Client(bot_i['name'], api_id=config['api_id'], api_hash=config['api_hash'],
               bot_token=bot_i['token'], parse_mode=ParseMode.DISABLED, max_concurrent_transmissions=2)
        for bot_i in config['bot']]
bot0 = bots[0]
user = Client('user1', api_id=config['api_id'], api_hash=config['api_hash'],
              phone_number=config['user'][1]["phone_number"], no_updates=True)

filter_me = filters.user([user_i['chat_id'] for user_i in config['user']]) & filters.private
filter_my_group_or_me = filters.chat(config['test_group']['chat_id']) | filter_me


async def init():
    global player, version
    connect_database = str(cli_args.prefix).startswith('tg://')
    db_context = asrec_telegram.database.connect() if connect_database else contextlib.nullcontext()
    async with app_group([*bots]), user, db_context:
        await bot0.send_message(config['test_group']['chat_id'], f"机器人已启动 [{version}]")
        player = Player(await get_rtmp_url(user, config['test_channel']['chat_id']))
        await idle()


@bot0.on_message((filters.command("help") | filters.command("start")) & filter_my_group_or_me)
async def help_command(_, message):
    await message.reply(
        """
        Usage:
        `/play video_name` - All available `video_name`s are in the group file;
        `/select` - select a live from the menu;
        `/restart` - restart telegram group call (continue playing the current video);
        """
    )


@bot0.on_message(filters.command("play") & filter_my_group_or_me)
async def change_video(_, message):
    name = message.text.split(maxsplit=1)[1:]
    if name:
        name = name[0].strip()
        await play_live(name, await message.reply("正在寻找视频文件..."))
    else:
        await message.reply("Usage: `/play video_name`")


@bot0.on_message(filters.command("select") & filter_my_group_or_me)
async def sel_command(_, message: Message):
    reply = selector.build_reply()
    if reply.pop('status') == 0:
        await message.reply(**reply)


@bot0.on_message(filters.command("restart") & filter_my_group_or_me)
async def restart_command(_, message):
    await restart_group_call(user, config['test_channel']['chat_id'])
    await message.reply("频道直播已重置")


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
    edit_callable = update_message.polling(bots, channel_ids['chat_id'], channel_ids['message_id']['danmaku'])
    base_dir = f'{cli_args.prefix}/{name}/transcoded'
    video_path = f'{base_dir}/hq.mp4'
    if video_path.startswith('tg://'):
        video_path = functools.partial(open_telegram, bot0, video_path[6:])

    progress_aiter = None if reply_message is None else Progress()
    try:
        danmaku_path = f'{base_dir}/danmaku.json'
        if danmaku_path.startswith('tg://'):
            dm_app = bots[1] if len(bots) > 1 else bot0
            danmaku_path = functools.partial(open_telegram, dm_app, danmaku_path[6:])
        player.play_now(
            video_path,
            progress_aiter=progress_aiter,
            danmaku=Danmaku(
                danmaku_path, edit_callable,
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
        logging.info(f"Finish starting procedure of {name}")
    except RuntimeError:
        if reply_message is not None:
            await reply_message.edit_text(f"服务器错误，退出程序")
        await bot0.stop()
        raise


if __name__ == '__main__':
    version = "v250831"
    logging.info(f"starting aslive bot {version}")
    parser = argparse.ArgumentParser(
        description=f"stream h264 mp4 A-SOUL record video to telegram livestream [{version}]")
    parser.add_argument('-p', '--prefix', help="base location of the video files")
    cli_args = parser.parse_args()
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    run = loop.run_until_complete(init())
