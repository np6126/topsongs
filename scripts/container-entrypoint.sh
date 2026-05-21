#!/bin/sh
set -eu

CRON_FILE=/etc/cron.d/topsongs
CRON_ENV=/app/cron-env.sh

python - <<'PY' > "$CRON_ENV"
import os
import shlex

from topsongs.config import Settings

# Export exactly the variables topsongs reads, derived from the settings model
# so this never goes stale when a new setting is added.
for name, field in Settings.model_fields.items():
    key = field.alias or name.upper()
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
