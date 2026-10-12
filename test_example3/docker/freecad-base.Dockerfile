# Shared base image for all FreeCAD Harbor tasks.
# Build once from the repo root:
#   docker build -f docker/freecad-base.Dockerfile -t freecad-base:latest .
# Each task's environment/Dockerfile then does `FROM freecad-base:latest`.
#
# FreeCAD ships no official Docker image, so this installs the real 1.1.3
# Linux AppImage at build time (--appimage-extract, no FUSE needed) and
# exposes its headless `freecadcmd` binary on PATH. This is the same
# FreeCAD 1.1.3 that FREECAD_CMD points to on Windows/macOS dev machines.

FROM python:3.11-slim

# Runtime libs the FreeCAD AppImage needs even in headless (freecadcmd) mode.
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget ca-certificates \
        libgl1 libglu1-mesa libxext6 libxrender1 libxrandr2 libxi6 \
        libxcursor1 libxinerama1 libxkbcommon0 libfontconfig1 \
        libfreetype6 libsm6 libice6 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ARG FREECAD_VERSION=1.1.3
RUN wget -q "https://github.com/FreeCAD/FreeCAD/releases/download/${FREECAD_VERSION}/FreeCAD_${FREECAD_VERSION}-Linux-x86_64-py311.AppImage" \
        -O /opt/FreeCAD.AppImage \
    && chmod +x /opt/FreeCAD.AppImage \
    && cd /opt && ./FreeCAD.AppImage --appimage-extract \
    && rm /opt/FreeCAD.AppImage \
    && ln -s /opt/squashfs-root/usr/bin/freecadcmd /usr/local/bin/freecadcmd \
    && ln -s /opt/squashfs-root/usr/bin/FreeCAD /usr/local/bin/freecad

# Different harnesses read different env var names for this -- set both.
ENV FREECADCMD=/usr/local/bin/freecadcmd
ENV FREECAD_CMD=/usr/local/bin/freecadcmd

COPY env_requirements.txt /tmp/env_requirements.txt
RUN pip install --no-cache-dir -r /tmp/env_requirements.txt

WORKDIR /app
