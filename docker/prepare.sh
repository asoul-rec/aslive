mkdir -p /root/files/lib/python3.13/site-packages/
mkdir -p /root/files/bin/
cp /usr/local/bin/ffmpeg /usr/local/bin/ffprobe /root/files/bin/
cd /usr/local/lib
cp -a libavcodec* libavdevice* libavfilter* libavformat* libavutil* libswresample* libswscale* /root/files/lib
cd python3.13/site-packages
cp -a av* /root/files/lib/python3.13/site-packages/
