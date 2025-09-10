FROM python:3.13-alpine AS requirements-stage

WORKDIR /root

COPY ./ffmpeg_8.0_shared.sh /root/

RUN ash ffmpeg_8.0_shared.sh 

COPY ./PyAV-15.1.0 /root/PyAV

RUN pip install ./PyAV

COPY ./prepare.sh /root

RUN ash prepare.sh

FROM python:3.13-alpine

WORKDIR /app

COPY --from=requirements-stage /root/files /usr/local

RUN wget https://github.com/asoul-rec/asrec-telegram/releases/download/v0.0.1/asrec_telegram-0.0.1-py3-none-any.whl &&\
    pip install --no-cache-dir ./asrec_telegram-0.0.1-py3-none-any.whl &&\
    rm ./asrec_telegram-0.0.1-py3-none-any.whl
