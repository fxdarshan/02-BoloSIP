#!/bin/sh
# Container entrypoint (Doc/deployment-plan.md §5): make the data folders writable for the
# unprivileged `app` user, then run the command as that user. Railway mounts volumes owned
# by root, so this runs as root and drops privileges with setpriv (part of util-linux).
set -e

DB_DIR=$(dirname "${BOLOSIP_DB:-/data/bolosip.sqlite3}")
CHROMA_DIR=${BOLOSIP_CHROMA_DIR:-/data/chroma}
mkdir -p "$DB_DIR" "$CHROMA_DIR"

if [ "$(id -u)" = "0" ]; then
    chown -R app:app "$DB_DIR" "$CHROMA_DIR"
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"
