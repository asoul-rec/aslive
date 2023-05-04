from pyrogram.raw import functions, base, types
from pyrogram import Client
from typing import Union


# from pyrogram.raw.functions
async def edit_group_call_title(client: Client, chat_id: Union[int, str], title: str) -> types.GroupCall:
    channel = await client.resolve_peer(chat_id)
    full_chat = await client.invoke(functions.channels.GetFullChannel(channel=channel))
    assert isinstance(full_chat, types.messages.ChatFull)
    call = full_chat.full_chat.call
    if not call:
        raise ValueError(f"chat does not have an active group call")
    r = await client.invoke(functions.phone.EditGroupCallTitle(call=call, title=title))
    for i in r.updates:
        if isinstance(i, types.UpdateGroupCall):
            return i.call
