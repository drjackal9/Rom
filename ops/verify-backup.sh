#!/bin/sh
set -eu
DUMP="${1:?uso: verify-backup.sh DUMP MASTER_KEY}"
KEY="${2:?uso: verify-backup.sh DUMP MASTER_KEY}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=55432
PY="$ROOT/.venv/bin/python"
[ -s "$DUMP" ] || { echo "dump vuoto o assente: $DUMP" >&2; exit 65; }
[ -s "$KEY" ] || { echo "chiave assente: $KEY" >&2; exit 65; }

cleanup() {
  docker rm -f clashbot-verify-db >/dev/null 2>&1 || true
  [ -n "${KEYDIR:-}" ] && rm -rf "$KEYDIR"
}
trap cleanup EXIT INT TERM

docker rm -f clashbot-verify-db >/dev/null 2>&1 || true
docker run -d --name clashbot-verify-db -e POSTGRES_DB=clashbot -e POSTGRES_HOST_AUTH_METHOD=trust \
  -p "127.0.0.1:$PORT:5432" postgres:16-alpine >/dev/null
for i in $(seq 1 60); do
  docker exec clashbot-verify-db pg_isready -U postgres -d clashbot >/dev/null 2>&1 && break
  sleep 1
done
docker cp "$DUMP" clashbot-verify-db:/tmp/clashbot.dump
docker exec clashbot-verify-db pg_restore -U postgres -d clashbot --no-owner --no-privileges /tmp/clashbot.dump
echo "tabelle ripristinate:"
docker exec clashbot-verify-db psql -U postgres -d clashbot -Atc \
  "select relname || ': ' || n_live_tup from pg_stat_user_tables order by relname"

KEYDIR=$(mktemp -d)
cp "$KEY" "$KEYDIR/master.key"
chmod 600 "$KEYDIR/master.key"
"$PY" "$ROOT/ops/verify_backup.py" "$KEYDIR" "$PORT"
echo "ripristino verificato"
