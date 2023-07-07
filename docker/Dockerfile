FROM python:3.11-alpine as requirements-stage

WORKDIR /root

COPY ./ffmpeg_5.1.2_shared.sh /root/

RUN ash ffmpeg_5.1.2_shared.sh 

COPY ./PyAV /root/PyAV

RUN pip install cython && pip install ./PyAV/

COPY ./prepare.sh /root

RUN ash prepare.sh

FROM python:3.11-alpine

WORKDIR /app

COPY --from=requirements-stage /root/files /usr/local

RUN pip install --no-cache-dir pyrogram tgcrypto
