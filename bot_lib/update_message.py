from pyrogram import Client
from pyrogram.enums import ParseMode


def polling(apps: list[Client], chat_id, message_id):
    def _gen_func():
        if apps:
            while True:
                yield from apps

    async def edit(text: str):
        _app = next(apps_iter)
        await _app.edit_message_text(
            chat_id, message_id, text,
            parse_mode=ParseMode.DISABLED,
            disable_web_page_preview=True
        )

    apps_iter = _gen_func()
    return edit
