#!/usr/bin/env sh
set -u
umask 077
KEEP_DUMPS=3
RETENTION=1
for arg in "$@"; do
  case "$arg" in
    --no-retention) RETENTION=0 ;;
    *) printf 'uso: backup.sh [--no-retention]\n' >&2; exit 64 ;;
  esac
done
ROOT=/opt/clashbot-backups
DB="$ROOT/db"
KEYS="$ROOT/keys"
LOG="$ROOT/backup.log"
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DB" "$KEYS"
log() { printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG"; }
exec 9>"$ROOT/.backup.lock"
flock -n 9
[ $? -eq 1 ] && { log "skip-busy"; exit 0; }
dk() { timeout -k 5 30 docker "$@"; }

OUT="$DB/clashbot-$TS.dump"
DUMP_OK=0
if timeout -k 60 1800 docker exec clashbot-db pg_dump -U postgres -d clashbot -Fc > "$OUT" 2>>"$LOG" && [ -s "$OUT" ]; then
  DUMP_OK=1
  log "db-ok $(du -h "$OUT" | cut -f1) $OUT"
else
  log "db-FAIL"
  rm -f "$OUT"
fi

SRC=/var/lib/docker/volumes/clashbot_clashbot-keys/_data/master.key
if [ -s "$SRC" ]; then
  cp "$SRC" "$KEYS/master.key.tmp" && chmod 600 "$KEYS/master.key.tmp" && mv "$KEYS/master.key.tmp" "$KEYS/master.key" && log "key-ok"
else
  log "key-MISSING $SRC"
fi

RUN=clashbot-retention
if [ "$RETENTION" = "0" ]; then
  log "retention-skip"
elif [ "$DUMP_OK" = "1" ]; then
  dk rm -f "$RUN" >/dev/null 2>&1
  if RET=$(cd /opt/clashbot && timeout -k 60 900 docker compose run --rm -T --no-deps --name "$RUN" bot retention 2>>"$LOG"); then
    log "retention-ok $(printf '%s' "$RET" | tr '\n' ' ')"
  else
    RC=$?
    dk rm -f "$RUN" >/dev/null 2>&1
    log "retention-FAIL rc=$RC"
  fi
  KEPT=0
  GONE=0
  for path in $(ls -t "$DB"/*.dump 2>/dev/null); do
    if [ "$KEPT" -lt "$KEEP_DUMPS" ]; then
      KEPT=$((KEPT + 1))
    elif rm -f "$path" 2>>"$LOG"; then
      GONE=$((GONE + 1))
    fi
  done
  log "prune-ok tenuti=$KEPT tolti=$GONE"
fi
log "done"
