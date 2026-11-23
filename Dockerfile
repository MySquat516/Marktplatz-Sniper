FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Erst nur die Abhängigkeiten (gecacht), dann der eigene Code: uv.lock sorgt dafür,
# dass jeder Build exakt die getesteten Versionen nutzt.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 1000 --home-dir /app --shell /usr/sbin/nologin sniper \
    && mkdir -p /data && chown sniper:sniper /data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data \
    PORT=8095 \
    TZ=Europe/Berlin
VOLUME /data
EXPOSE 8095

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8095'), timeout=4)"

# Der Entrypoint läuft nur kurz als root (Rechte auf /data) und wechselt dann auf "sniper".
ENTRYPOINT ["docker-entrypoint.sh", "sniper"]
CMD ["serve"]
