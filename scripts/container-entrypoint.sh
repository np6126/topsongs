#!/bin/sh
set -eu

CRON_FILE=/etc/cron.d/topsongs
CRON_ENV=/app/cron-env.sh

python - <<'PY' > "$CRON_ENV"
import os
import shlex

keys = [
    "JELLYFIN_URL",
    "JELLYFIN_API_KEY",
    "LASTFM_API_KEY",
    "MIN_TRACKS_PER_ARTIST",
    "STATE_DIR",
    "LOG_LEVEL",
    "REQUEST_TIMEOUT_SECONDS",
    "REQUEST_MAX_RETRIES",
    "RETRY_BACKOFF_SECONDS",
    "ARTIST_ALLOWLIST",
    "ARTIST_DENYLIST",
    "USER_ALLOWLIST",
    "USER_DENYLIST",
    "LIBRARY_PATH_ALLOWLIST",
    "LIBRARY_PATH_DENYLIST",
]

for key in keys:
    if key in os.environ:
        print(f"export {key}={shlex.quote(os.environ[key])}")
PY

chmod 600 "$CRON_ENV"

cat > "$CRON_FILE" <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_SCHEDULE:-0 3 * * *} root . $CRON_ENV && run-topsongs >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF

chmod 0644 "$CRON_FILE"

if [ "${RUN_ON_STARTUP:-false}" = "true" ]; then
  echo "Running initial playlist refresh on startup"
  . "$CRON_ENV"
  run-topsongs
fi

echo "Starting cron with schedule: ${CRON_SCHEDULE:-0 3 * * *}"
exec cron -f
