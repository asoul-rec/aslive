from contextlib import asynccontextmanager
from pyrogram import Client
from asyncio import TaskGroup


@asynccontextmanager
async def app_group(apps: list[Client]):
    async with TaskGroup() as group:
        for _app in apps:
            group.create_task(_app.__aenter__())
    try:
        yield apps
    finally:
        async with TaskGroup() as group:
            for _app in apps:
                group.create_task(_app.__aexit__())
