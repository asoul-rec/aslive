mkdir -p /root/files/lib/python3.11/site-packages/
mkdir -p /root/files/bin/
cp /usr/local/bin/ffmpeg /root/files/bin/
cd /usr/local/lib
cp -a libavcodec* libavdevice* libavfilter* libavformat* libavutil* libswresample* libswscale* /root/files/lib
cd python3.11/site-packages
cp -a av* tgcrypto* TgCrypto* /root/files/lib/python3.11/site-packages/
