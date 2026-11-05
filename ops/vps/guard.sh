#!/bin/bash
set -u
[ -n "${LC_ALL:-}" ] && export LANG="$LC_ALL"
unset LC_ALL
export LC_NUMERIC=C
umask 077
[ -f /opt/clashbot/.live ] || exit 0
BACKUPS=/opt/clashbot-backups
LOG="$BACKUPS/guard.log"
METRICS="$BACKUPS/metrics"
SAMPLES="$METRICS/samples.jsonl"
LEVEL="$METRICS/db_gb.level"
LIMIT_MB=2048
LIMIT_PERC=200
KEEP=$((7 * 86400))
mkdir -p "$BACKUPS"
exec 9>"$BACKUPS/.guard.lock"
flock -n 9
[ $? -eq 1 ] && exit 0
NOW=$(date +%s)
ALERTS=""
add() { ALERTS="${ALERTS}${ALERTS:+
}$1"; }
dk() { timeout -k 5 30 docker "$@"; }

for c in clashbot clashbot-db; do
  st=$(dk inspect -f '{{.State.Status}}|{{.State.Health.Status}}|{{.State.OOMKilled}}' "$c" 2>/dev/null)
  case $? in
    0) ;;
    124|137) add "$c: docker non risponde"; continue ;;
    *) add "$c: container assente"; continue ;;
  esac
  IFS='|' read -r status health oom <<< "$st"
  [ "$status" != "running" ] && add "$c: $status"
  [ "$health" != "healthy" ] && add "$c: $health"
  [ "$oom" = "true" ] && add "$c: ucciso per memoria"
done

st=$(dk inspect -f '{{.State.Status}}|{{.State.OOMKilled}}' clashbot-tunnel 2>/dev/null)
case $? in
  0)
    IFS='|' read -r status oom <<< "$st"
    [ "$status" != "running" ] && add "clashbot-tunnel: $status"
    [ "$oom" = "true" ] && add "clashbot-tunnel: ucciso per memoria" ;;
  124|137) add "clashbot-tunnel: docker non risponde" ;;
esac

LAST=$(ls -t "$BACKUPS"/db/clashbot-*.dump 2>/dev/null | head -1)
AGE_H=null
if [ -z "$LAST" ]; then
  add "backup: nessun dump"
else
  ELAPSED=$(( NOW - $(stat -c %Y "$LAST") ))
  AGE_H=$(( ELAPSED / 3600 ))
  AGE=$(( ELAPSED / 86400 ))
  [ "$AGE" -gt 2 ] && add "backup: ultimo dump di ${AGE}gg fa"
fi
[ -s "$BACKUPS/keys/master.key" ] || add "backup: chiave master non salvata"
RETENTION=null
case "$(tail -n 200 "$BACKUPS/backup.log" 2>/dev/null | grep -oE 'retention-(ok|FAIL)' | tail -1)" in
  retention-FAIL) add "ritenzione: ultima pulizia fallita"; RETENTION='"fail"' ;;
  retention-ok) RETENTION='"ok"' ;;
esac

if [ -f "$BACKUPS/restore.log" ]; then
  case "$(tail -n 200 "$BACKUPS/restore.log" | grep -oE 'restore-(ok|FAIL)' | tail -1)" in
    restore-FAIL) add "ripristino: ultima prova fallita" ;;
  esac
  if [ -s "$BACKUPS/.restore-ok" ]; then
    RESTORE_AGE=$(( (NOW - $(stat -c %Y "$BACKUPS/.restore-ok")) / 86400 ))
    [ "$RESTORE_AGE" -gt 8 ] && add "ripristino: ultima prova riuscita di ${RESTORE_AGE}gg fa"
  else
    add "ripristino: nessuna prova riuscita"
  fi
fi

DB_BYTES=$(dk exec clashbot-db psql -U postgres -d clashbot -tAc "select pg_database_size('clashbot')" 2>/dev/null | tr -d '[:space:]')
if [[ "$DB_BYTES" =~ ^[0-9]+$ ]] && [ "$DB_BYTES" -gt $((2 * 1024 * 1024 * 1024)) ]; then
  add "database su disco: $((DB_BYTES / 1024 / 1024)) MB, oltre 2 GB"
fi

mkdir -p "$METRICS"
IDS=$(dk ps --filter name=clashbot -q 2>/dev/null)
USAGE=""
[ -n "$IDS" ] && USAGE=$(dk stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' $IDS 2>/dev/null)
ROWS=$(printf '%s\n' "$USAGE" | awk 'NF >= 3 {
  size = $2 + 0
  unit = $2
  sub(/^[0-9.]+/, "", unit)
  if (unit == "GiB" || unit == "GB") size *= 1024
  else if (unit == "KiB" || unit == "kB") size /= 1024
  else if (unit == "B") size /= 1048576
  perc = $NF + 0
  printf "%s %d %.2f %d\n", $1, size + 0.5, perc / 100, perc + 0.5
}')
BOT=""
BOT_MB=0
BOT_CPU=0
BOT_PERC=0
DB_MB=0
CONTAINERS=""
while read -r name mb cpu perc; do
  [ -z "$name" ] && continue
  CONTAINERS="${CONTAINERS}${CONTAINERS:+,}\"$name\":{\"mem_mb\":$mb,\"cpu\":$cpu}"
  case "$name" in
    clashbot) BOT=$name; BOT_MB=$mb; BOT_CPU=$cpu; BOT_PERC=$perc ;;
    clashbot-db) DB_MB=$mb ;;
  esac
done <<< "$ROWS"

PREV_MB=0
PREV_PERC=0
if [ -n "$BOT" ] && [ -f "$SAMPLES" ]; then
  PREV=$(awk -v key="\"$BOT\":{\"mem_mb\":" '
    index($0, key) { ultimo = substr($0, index($0, key) + length(key)) }
    END {
      if (ultimo == "") exit
      sub(/}.*$/, "", ultimo)
      if (split(ultimo, parti, /[^0-9.]+/) < 2) exit
      printf "%d %d\n", parti[1] + 0.5, parti[2] * 100 + 0.5
    }' "$SAMPLES")
  [ -n "$PREV" ] && read -r PREV_MB PREV_PERC <<< "$PREV"
fi
[ "$BOT_MB" -gt "$LIMIT_MB" ] && [ "$PREV_MB" -le "$LIMIT_MB" ] && add "$BOT: $BOT_MB MB, oltre 2 GB"
[ "$BOT_PERC" -gt "$LIMIT_PERC" ] && [ "$PREV_PERC" -le "$LIMIT_PERC" ] && add "$BOT: $BOT_CPU core, oltre 2"
DB_GB=$(( DB_MB / 1024 ))
SEEN=$(cat "$LEVEL" 2>/dev/null)
[[ "$SEEN" =~ ^[0-9]+$ ]] || SEEN=0
if [ "$DB_GB" -gt "$SEEN" ]; then
  add "database in memoria: $DB_MB MB, oltre $DB_GB GB"
  printf '%s\n' "$DB_GB" > "$LEVEL"
fi
if [ -f "$SAMPLES" ]; then
  awk -v cut=$((NOW - KEEP)) '{ t = $0; sub(/^.*"ts":[ ]*/, "", t); sub(/[^0-9].*$/, "", t); if (t != "" && t + 0 >= cut) print }' "$SAMPLES" > "$SAMPLES.tmp" && mv "$SAMPLES.tmp" "$SAMPLES"
fi
printf '{"ts":%s,"containers":{%s},"backup_age_h":%s,"retention":%s}\n' "$NOW" "$CONTAINERS" "$AGE_H" "$RETENTION" >> "$SAMPLES"
chmod 644 "$SAMPLES"

ERRS=$(dk logs clashbot --since 30m 2>&1 | grep -ciE 'traceback| ERROR ')
[ "${ERRS:-0}" -gt 0 ] && add "log: ${ERRS} errori in 30 min"

if [ -n "$ALERTS" ]; then
  dk rm -f clashbot-guard >/dev/null 2>&1
  OUT=$(cd /opt/clashbot && timeout -k 30 120 docker compose run --rm -T --no-deps --name clashbot-guard bot notify "ClanBoard guardiano
$ALERTS" 2>&1)
  RC=$?
  if [ "$RC" -ne 0 ]; then
    dk rm -f clashbot-guard >/dev/null 2>&1
    TS=$(date +'%Y-%m-%d %H:%M:%S')
    {
      printf '[%s] notify-FAIL rc=%s\n' "$TS" "$RC"
      printf '%s\n' "$OUT" | grep -E '^(manca (console_token|owner_id)|avviso non inviato: )' | tail -n 3 | sed "s/^/[$TS] notify: /"
      printf '%s\n' "$ALERTS" | sed "s/^/[$TS] /"
    } >> "$LOG"
    tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  fi
  while IFS= read -r riga; do
    printf '{"ts":%s,"alert":"%s"}\n' "$NOW" "$(printf '%s' "$riga" | sed 's/[\\"]/\\&/g')" >> "$SAMPLES"
  done <<< "$ALERTS"
fi
