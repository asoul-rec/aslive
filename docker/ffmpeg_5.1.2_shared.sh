apk add --no-cache build-base openssl-dev nasm x264-dev
wget https://ffmpeg.org/releases/ffmpeg-5.1.2.tar.xz -O ffmpeg.tar.xz
tar -xf ffmpeg.tar.xz
cd ffmpeg-5.1.2
./configure --disable-w32threads --disable-os2threads --disable-alsa --disable-appkit --disable-avfoundation --disable-bzlib --disable-coreimage --disable-iconv --disable-libxcb --disable-libxcb-shm --disable-libxcb-xfixes --disable-libxcb-shape --disable-lzma --disable-sndio --disable-sdl2 --disable-xlib --disable-zlib --disable-amf --disable-audiotoolbox --disable-cuda --disable-cuvid --disable-d3d11va --disable-dxva2 --disable-nvdec --disable-nvenc --disable-v4l2-m2m --disable-vaapi --disable-vdpau --disable-videotoolbox --disable-everything --enable-demuxer=flv,mov,mpegts,live_flv --enable-muxer=flv,mov,mp4,mpegts --enable-protocol=file,rtmp,pipe,rtmps,http --enable-bsf=aac_adtstoasc,h264_mp4toannexb --enable-encoder=aac,h264 --enable-decoder=aac,h264 --disable-postproc --disable-doc --disable-runtime-cpudetect --enable-openssl --enable-pthreads --enable-version3 --enable-gpl --enable-libx264 --enable-avcodec --enable-avformat --enable-avdevice --enable-swscale --enable-swresample --enable-avfilter --disable-programs --enable-ffmpeg --enable-small --enable-shared --disable-static
make -j4
make install
