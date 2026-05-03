FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        fonts-hosny-amiri \
        fonts-montserrat \
        fonts-noto-core \
        libglib2.0-0 \
        libgl1 \
        python3 \
        python3-pip \
    && python3 -m pip install --break-system-packages --no-cache-dir \
        mediapipe \
        opencv-python \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY docker/render/face_track.py /opt/minara/face_track.py

CMD ["ffmpeg", "-version"]
