# Universal Docker container for Nazak Browser Studio.
#
# P1 hardening, three goals:
#   1. two stages — the runtime image carries a prepared virtualenv and the
#      Chromium build, but no pip caches and no build tooling;
#   2. the server runs as an unprivileged user (uid/gid 10001), not root;
#   3. a HEALTHCHECK lets Docker/compose report real readiness.
#
# The Debian suite is pinned on purpose (audit R3): the floating tag
# `python:3.11-slim` currently resolves to trixie (checked against
# docker-library/official-images), and the previous package list used
# bookworm-only names — the build failed with "Unable to locate package".
# Debian 13 renamed several packages during the 64-bit time_t transition (…t64);
# apt versions are deliberately not pinned, see the hadolint ignore below.

# ---------------------------------------------------------------------------
# Stage 1 — builder: virtualenv + Chromium download.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-trixie AS builder

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .

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
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

# ---------------------------------------------------------------------------
# Stage 2 — runtime: same OS libraries, non-root user, prepared venv.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-trixie AS runtime

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    NAZAK_DATA_DIR=/app/data

WORKDIR /app

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
    && rm -rf /var/lib/apt/lists/* \
    # Unprivileged runtime user. uid/gid 10001 is fixed so a bind-mounted data
    # directory can be prepared on the host: chown -R 10001:10001 ./data
    && groupadd --gid 10001 nazak \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin nazak \
    && mkdir -p /app/data \
    && chown -R nazak:nazak /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /ms-playwright /ms-playwright
COPY . .

RUN chown -R nazak:nazak /app /ms-playwright

USER nazak

EXPOSE 8899

# Readiness probe: /api/system/info behind the same local guard as any client.
# The token is read from the environment, so the check also passes when
# NAZAK_API_TOKEN is set (it always is inside a container).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; req = urllib.request.Request('http://127.0.0.1:8899/api/system/info', headers={'X-API-Key': os.environ.get('NAZAK_API_TOKEN', '')}); urllib.request.urlopen(req, timeout=4)"]

# Inside a container the app must listen on 0.0.0.0 for `ports:` to work, so the
# local-only Host check is not a boundary here. The server therefore REFUSES to
# start on a non-loopback host unless NAZAK_API_TOKEN is set (audit R3):
#   docker run -e NAZAK_API_TOKEN=<secret> -p 127.0.0.1:8899:8899 nazak
CMD ["python", "-m", "nazak.main", "--mode", "web", "--host", "0.0.0.0", "--port", "8899"]
