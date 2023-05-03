from collections.abc import Sequence
from pyrogram.types import InlineKeyboardButton


def button_callback_grid(texts: Sequence, width: int = 8, *, callback_data_prefix: str) -> \
        list[list[InlineKeyboardButton]]:
    grid = []
    avail_slot = 0
    if not 1 <= width <= 8:
        raise ValueError("width must be in range [1, 8]")
    width = int(width)
    for i, t_i in enumerate(texts):
        if not avail_slot:
            grid.append([])
            avail_slot = width
        grid[-1].append(InlineKeyboardButton(t_i, callback_data=str(callback_data_prefix) + str(t_i)))
        avail_slot -= 1
    return grid
