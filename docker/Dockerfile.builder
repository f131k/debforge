FROM debian:12.0

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH=/app/.venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
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
  && python3 -m venv /app/.venv \
  && /app/.venv/bin/pip install --no-cache-dir uv==0.12.0 \
  && rm -rf /var/lib/apt/lists/* /root/.cache

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY debforge ./debforge
RUN uv sync --locked --no-dev --inexact

COPY debforge.bookworm.yaml debforge.yaml.example ./

ENTRYPOINT ["uv", "run", "--no-sync", "debforge"]
