import re
import json
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_lib import button_callback_grid

sel_date_regex = re.compile(r"^SEL(?:_Y_(\d{4})(?:_M_(\d{2})(?:_N_(\d{2}))?)?)?$")

with open('live_info.json') as f:
    live_info = json.load(f)


# TODO: create a specification for status literal

def build_reply(year=None, month=None, num=None):
    result = {'text': None, 'reply_markup': None, 'status': 0}
    if year is None:
        result['text'] = f"请选择要播放的直播所在年份"
        avail_years = list(live_info)
        width = {5: 3, 6: 3, 9: 3}.get(len(avail_years), 4)
        result['reply_markup'] = InlineKeyboardMarkup(
            button_callback_grid(avail_years, width, callback_data_prefix='SEL_Y_')
        )
        return result
    if month is None:
        avail_months = live_info.get(year)
        if avail_months is None:
            result['status'] = -1
            return result
        else:
            avail_months = list(avail_months)
        result['text'] = f"{year}年中{len(avail_months)}个月有可回放的直播\n请选择月份"
        result['reply_markup'] = InlineKeyboardMarkup([
            *button_callback_grid(avail_months, 6, callback_data_prefix=f'SEL_Y_{year}_M_'),
            [InlineKeyboardButton("返回", callback_data='SEL')]
        ])
        return result
    if num is None:
        avail_lives = live_info.get(year, {}).get(month)
        if avail_lives is None:
            result['status'] = -1
            return result
        button_text = []
        lives_str = []
        for i, live_i in enumerate(avail_lives):
            num = f'{i + 1:02d}'
            lives_str.append(num + '. ' + live_i)
            button_text.append(num)
        lives_str = '\n'.join(lives_str)
        result['text'] = f"{year}年{month}月中有{len(avail_lives)}场可回放的直播\n{lives_str}\n请选择直播编号"
        result['reply_markup'] = InlineKeyboardMarkup([
            *button_callback_grid(button_text, 6, callback_data_prefix=f'SEL_Y_{year}_M_{month}_N_'),
            [InlineKeyboardButton("返回", callback_data=f'SEL_Y_{year}')]
        ])
        return result
    try:
        result['text'] = live_info[year][month][int(num) - 1]
        result['status'] = 1
    except (IndexError, KeyError):
        result['status'] = -1
    finally:
        return result
