#!/bin/sh
set -u
umask 077
[ -f /opt/clashbot/.live ] || exit 0
ROOT=/opt/clashbot-backups
DB="$ROOT/db"
KEYS="$ROOT/keys"
LOG="$ROOT/restore.log"
MARK="$ROOT/.restore-ok"
TEST=clashbot_prova
LIVE=/var/lib/docker/volumes/clashbot_clashbot-keys/_data/master.key
RUN=clashbot-restore
mkdir -p "$DB" "$KEYS"
log() { printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG"; }
dk() { timeout -k 5 30 docker "$@"; }
sql() { dk exec clashbot-db psql -U postgres -d postgres -tAc "$1" >/dev/null 2>/dev/null; }
drop() { sql "drop database if exists $TEST"; }
trim() { tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; }
stop() { log "restore-FAIL $1"; exit 1; }
exec 9>"$ROOT/.backup.lock"
flock -n 9
[ $? -eq 1 ] && { log "skip-busy"; exit 0; }
trap 'drop; trim' EXIT
trap 'exit 1' INT TERM HUP
log "restore-start"

DUMP=$(ls -t "$DB"/weekly-*.dump "$DB"/clashbot-*.dump 2>/dev/null | head -1)
[ -n "$DUMP" ] && [ -s "$DUMP" ] || stop "nessun dump"
cmp -s "$KEYS/master.key" "$LIVE" || stop "chiave master salvata diversa da quella in uso"
drop
sql "create database $TEST" || stop "database di prova non creato"
timeout -k 60 900 docker exec -i clashbot-db pg_restore -U postgres -d "$TEST" \
  --no-owner --single-transaction < "$DUMP" 2>/dev/null || stop "ripristino di $(basename "$DUMP")"
dk rm -f "$RUN" >/dev/null 2>&1
OUT=$(cd /opt/clashbot && timeout -k 60 900 docker compose run --rm -T --no-deps --name "$RUN" \
  bot restore-check --database "$TEST" 2>&1)
RC=$?
dk rm -f "$RUN" >/dev/null 2>&1
LINE=$(printf '%s' "$OUT" | tail -n 1)
[ "$RC" -eq 0 ] || stop "controllo rc=$RC $LINE"
log "restore-ok $(basename "$DUMP") $LINE"
printf '%s\n' "$(basename "$DUMP")" > "$MARK"
