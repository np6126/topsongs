FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY topsongs ./topsongs
COPY scripts/container-entrypoint.sh /usr/local/bin/container-entrypoint.sh

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir '.[web]' \
    && chmod +x /usr/local/bin/container-entrypoint.sh

# Web dashboard served by topsongs-web (override the port with TOPSONGS_WEB_PORT).
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/container-entrypoint.sh"]
