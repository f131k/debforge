FROM debian:12.0

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    dpkg-dev \
    devscripts \
    debhelper \
    build-essential \
    fakeroot \
    apt-utils \
    debian-archive-keyring \
    debsigs \
    debsig-verify \
    gnupg \
    cmake \
    ninja-build \
    pkg-config \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY build_packages.py /usr/local/lib/debforge/build_packages.py
COPY sign_packages.py /usr/local/lib/debforge/sign_packages.py

WORKDIR /build
