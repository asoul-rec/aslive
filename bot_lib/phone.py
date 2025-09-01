import logging
import random
from typing import Union, Optional, Generator

from pyrogram.raw import functions, types
from pyrogram import Client


# from pyrogram.raw.functions
async def get_group_call(client: Client, chat_id: Union[int, str]) -> Optional[types.InputGroupCall]:
    channel = await client.resolve_peer(chat_id)
    full_chat = await client.invoke(functions.channels.GetFullChannel(channel=channel))
    assert isinstance(full_chat, types.messages.ChatFull)
    return full_chat.full_chat.call


async def edit_group_call_title(client: Client, chat_id: Union[int, str], title: str) -> types.GroupCall:
    call = await get_group_call(client, chat_id)
    if call is None:
        raise ValueError(f"chat does not have an active group call")
    r = await client.invoke(functions.phone.EditGroupCallTitle(call=call, title=title))
    for i in r.updates:
        if isinstance(i, types.UpdateGroupCall):
            return i.call


async def restart_group_call(client: Client, chat_id: Union[int, str]):
    call = await get_group_call(client, chat_id)
    old_title = None
    update_message_ids = []
    # discard existing call and remember the old title
    if call is not None:
        call_info: types.phone.GroupCall
        call_info = await client.invoke(functions.phone.GetGroupCall(call=call, limit=100))
        old_title = call_info.call.title
        discard = await client.invoke(functions.phone.DiscardGroupCall(call=call))
        update_message_ids += get_message_id_from_updates(discard)
    # create a new call with the old title or empty title
    create = await client.invoke(functions.phone.CreateGroupCall(
        peer=await client.resolve_peer(chat_id),
        random_id=random.randint(-1 << 31, (1 << 31) - 1),  # note: Int(random_id) is a signed 32-bit LE integer
        rtmp_stream=True,
        title=old_title
    ))
    update_message_ids += get_message_id_from_updates(create)
    # delete the messages saying "xxx started a video chat" and "xxx ended the video chat (xxx time)"
    logging.info(f"deleting update messages {update_message_ids} when restarting group call")
    await client.delete_messages(chat_id, update_message_ids)


async def get_rtmp_url(client: Client, chat_id: Union[int, str]) -> str:
    channel = await client.resolve_peer(chat_id)
    rtmp_url: types.phone.GroupCallStreamRtmpUrl
    rtmp_url = await client.invoke(functions.phone.GetGroupCallStreamRtmpUrl(peer=channel, revoke=False))
    return rtmp_url.url + rtmp_url.key


def get_message_id_from_updates(updates: types.Updates) -> Generator[int, None, None]:
    for i in updates.updates:
        if isinstance(i, types.UpdateMessageID):
            yield i.id
