# Universal Docker container for Nazak Browser Studio.
#
# The Debian suite is pinned on purpose (audit R3): the floating tag
# `python:3.11-slim` currently resolves to trixie (checked against
# docker-library/official-images), and the previous package list used
# bookworm-only names — the build failed with "Unable to locate package".
FROM python:3.11-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Runtime libraries for Chromium/Playwright and Qt6. Debian 13 renamed several
# of them during the 64-bit time_t transition (…t64); apt versions are
# deliberately not pinned, see the hadolint ignore below.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0t64 \
    libnss3 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium --with-deps

COPY . .

EXPOSE 8899

# Inside a container the app must listen on 0.0.0.0 for `ports:` to work, so the
# local-only Host check is not a boundary here. The server therefore REFUSES to
# start on a non-loopback host unless NAZAK_API_TOKEN is set (audit R3):
#   docker run -e NAZAK_API_TOKEN=<secret> -p 127.0.0.1:8899:8899 nazak
CMD ["python", "-m", "nazak.main", "--mode", "web", "--host", "0.0.0.0", "--port", "8899"]
