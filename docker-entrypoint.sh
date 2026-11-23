#!/bin/sh
set -e
# Gemountete Ordner gehören oft root: einmal die Rechte richten, dann als "sniper" weiter.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "${DATA_DIR:-/data}"
  chown -R sniper:sniper "${DATA_DIR:-/data}"
  exec setpriv --reuid=sniper --regid=sniper --init-groups "$@"
fi
exec "$@"
