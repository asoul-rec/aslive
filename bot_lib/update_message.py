import logging
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
import asyncio

def polling(clients: list[Client], chat_id, message_id):
    def _gen_func():
        if clients:
            while True:
                yield from clients

    async def edit(text: str):
        client = next(clients_iter)
        try:
            await client.edit_message_text(
                chat_id, message_id, text,
                parse_mode=ParseMode.DISABLED,
                disable_web_page_preview=True
            )
        except FloodWait as e:
            logging.error(f"client '{client.name}' got FloodWait for {e.value} seconds")
            # await asyncio.sleep(e.value)

    clients_iter = _gen_func()
    return edit
