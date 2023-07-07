# Telegram video bot for A-SOUL live records

Welcome to my broadcast channel https://t.me/asoul_live at Telegram!
The bot is written in Python using Pyrogram and asyncio.
It also uses PyAV (based on FFmpeg) to demux the video file encoded with AVC and AAC and mux as an RTMP stream to push to Telegram live server.

The docker folder contains scripts to build a minimal python environment with essential libraries to run the bot.

Video files are not included in this repo and I will release them soon.