FROM python:3.11-alpine as requirements-stage

WORKDIR /root

COPY ./ffmpeg_5.1.2_shared.sh /root/

RUN ash ffmpeg_5.1.2_shared.sh

COPY ./PyAV /root/PyAV

RUN echo 'cython<3.0' > constraint.txt; PIP_CONSTRAINT=constraint.txt pip install ./PyAV/

RUN pip install tgcrypto

COPY ./prepare.sh /root

RUN ash prepare.sh

FROM python:3.11-alpine

WORKDIR /app

COPY --from=requirements-stage /root/files /usr/local

RUN pip install --no-cache-dir pyrogram
