import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "vps" / "restore-test.sh"
RUN = "clashbot-restore"
TEST_DB = "clashbot_prova"
SUMMARY = "tabelle=16/16 righe=16 decifrate=16 illeggibili=0 orfani=0 ultimo_giro=2026-09-13 04:31 esito=ok"
FLOCK = "flock -n 9"
DROP = f"docker exec clashbot-db psql -U postgres -d postgres -tAc drop database if exists {TEST_DB}"
CREATE = f"docker exec clashbot-db psql -U postgres -d postgres -tAc create database {TEST_DB}"
RESTORE = f"docker exec -i clashbot-db pg_restore -U postgres -d {TEST_DB} --no-owner --single-transaction"
REMOVE = f"docker rm -f {RUN}"
CHECK = f"docker compose run --rm -T --no-deps --name {RUN} bot restore-check --database {TEST_DB}"

FAKE_TIMEOUT = """#!/bin/sh
printf 'timeout %s\\n' "$*" >> "$CALLS"
case "$1 $2 $3" in
  "-k 5 30"|"-k 60 900") ;;
  *) exit 125 ;;
esac
shift 3
exec "$@"
"""

FAKE_DOCKER = """#!/bin/sh
printf 'docker %s\\n' "$*" >> "$CALLS"
case "$*" in
  *psql*) exit "${PSQL_RC:-0}" ;;
  *pg_restore*) cat >/dev/null; exit "${RESTORE_RC:-0}" ;;
esac
case "$1" in
  rm) printf 'rm-noise\\n'; printf 'rm-noise\\n' >&2; exit 3 ;;
  compose)
    printf '%s\\n' "${CHECK_OUT:-rumore di compose}"
    printf '%s\\n' "${CHECK_LINE:-SUMMARY_PLACEHOLDER}"
    exit "${CHECK_RC:-0}" ;;
esac
exit 99
""".replace("SUMMARY_PLACEHOLDER", SUMMARY)

FAKE_FLOCK = f"""#!{sys.executable}
import fcntl, os, sys
with open(os.environ["CALLS"], "a") as calls:
    calls.write(" ".join(["flock"] + sys.argv[1:]) + "\\n")
if os.environ.get("FLOCK_RC"):
    sys.exit(int(os.environ["FLOCK_RC"]))
if sys.argv[1:] != ["-n", "9"]:
    sys.exit(64)
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(1)
"""

KEY = b"master-key-bytes"


def sandbox(tmp_path, live=True, dumps=("weekly-20260913.dump",), key=KEY, saved=KEY):
    backups = tmp_path / "clashbot-backups"
    volume = tmp_path / "volume"
    app = tmp_path / "app"
    fakebin = tmp_path / "bin"
    for folder in (backups / "db", backups / "keys", volume, app, fakebin):
        folder.mkdir(parents=True)
    for name in dumps:
        (backups / "db" / name).write_bytes(b"dump-bytes")
    if key is not None:
        (volume / "master.key").write_bytes(key)
    if saved is not None:
        (backups / "keys" / "master.key").write_bytes(saved)
    if live:
        (app / ".live").write_text("")
    text = SCRIPT.read_text()
    text = text.replace("/opt/clashbot-backups", str(backups))
    text = text.replace("/var/lib/docker/volumes/clashbot_clashbot-keys/_data/master.key", str(volume / "master.key"))
    text = text.replace("/opt/clashbot/.live", str(app / ".live"))
    text = text.replace("cd /opt/clashbot ", f"cd {app} ")
    assert "/opt/" not in text and "/var/lib/docker" not in text
    script = tmp_path / "restore-test.sh"
    script.write_text(text)
    for name, body in (("timeout", FAKE_TIMEOUT), ("docker", FAKE_DOCKER), ("flock", FAKE_FLOCK)):
        path = fakebin / name
        path.write_text(body)
        path.chmod(0o755)
    return script, backups, fakebin


def run_restore(tmp_path, **extra):
    script, backups, fakebin = sandbox(tmp_path, **{k: v for k, v in extra.items() if k in
                                                    ("live", "dumps", "key", "saved")})
    env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", CALLS=str(tmp_path / "calls.txt"),
               **{k: v for k, v in extra.items() if k not in ("live", "dumps", "key", "saved")})
    result = subprocess.run(["sh", str(script)], env=env, timeout=60, capture_output=True, text=True)
    calls = (tmp_path / "calls.txt").read_text().splitlines() if (tmp_path / "calls.txt").exists() else []
    log = []
    if (backups / "restore.log").exists():
        log = [line.split("] ", 1)[1] for line in (backups / "restore.log").read_text().splitlines() if "] " in line]
    return result, backups, log, [line for line in calls if not line.startswith("timeout ")]


def test_lo_script_e_sintatticamente_valido():
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True, timeout=30)


def test_la_prova_sta_nelle_cartelle_di_clashbot_e_non_tocca_la_produzione():
    text = SCRIPT.read_text()
    assert "ROOT=/opt/clashbot-backups\n" in text
    assert f"TEST={TEST_DB}\n" in text
    assert 'exec 9>"$ROOT/.backup.lock"' in text
    assert re.search(r"-d clashbot[\s\"]", text) is None
    assert "puntovicino" not in text.lower() and "crontab" not in text


def test_senza_live_non_fa_nulla(tmp_path):
    result, backups, log, calls = run_restore(tmp_path, live=False)
    assert result.returncode == 0 and calls == [] and log == []
    assert not (backups / "restore.log").exists()


def test_un_giro_riuscito_ripristina_controlla_e_cancella(tmp_path):
    result, backups, log, calls = run_restore(tmp_path)
    assert result.returncode == 0
    assert calls == [FLOCK, DROP, CREATE, RESTORE, REMOVE, CHECK, REMOVE, DROP]
    assert log == ["restore-start", f"restore-ok weekly-20260913.dump {SUMMARY}"]
    assert (backups / ".restore-ok").read_text().strip() == "weekly-20260913.dump"
    assert stat.S_IMODE((backups / ".restore-ok").stat().st_mode) == 0o600
    assert "rm-noise" not in (backups / "restore.log").read_text()


def test_prende_il_dump_piu_recente(tmp_path):
    dumps = ("weekly-20260906.dump", "clashbot-20260913-043000.dump")
    script, backups, fakebin = sandbox(tmp_path, dumps=dumps)
    vecchio = backups / "db" / "weekly-20260906.dump"
    stamp = time.time() - 7 * 86400
    os.utime(vecchio, (stamp, stamp))
    env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", CALLS=str(tmp_path / "calls.txt"))
    subprocess.run(["sh", str(script)], env=env, timeout=60, check=True, capture_output=True)
    assert (backups / ".restore-ok").read_text().strip() == "clashbot-20260913-043000.dump"


def test_senza_dump_non_si_apre_nemmeno_il_database(tmp_path):
    result, backups, log, calls = run_restore(tmp_path, dumps=())
    assert result.returncode == 1
    assert calls == [FLOCK, DROP]
    assert log == ["restore-start", "restore-FAIL nessun dump"]
    assert not (backups / ".restore-ok").exists()


@pytest.mark.parametrize("saved", [b"altra-chiave", None])
def test_una_chiave_salvata_diversa_ferma_la_prova(tmp_path, saved):
    result, backups, log, calls = run_restore(tmp_path, saved=saved)
    assert result.returncode == 1
    assert calls == [FLOCK, DROP]
    assert log == ["restore-start",
                   "restore-FAIL chiave master salvata diversa da quella in uso"]
    testo = (backups / "restore.log").read_text()
    assert "master-key-bytes" not in testo and "altra-chiave" not in testo


def test_un_ripristino_fallito_cancella_il_database_di_prova(tmp_path):
    result, backups, log, calls = run_restore(tmp_path, RESTORE_RC="1")
    assert result.returncode == 1
    assert calls == [FLOCK, DROP, CREATE, RESTORE, DROP]
    assert log == ["restore-start", "restore-FAIL ripristino di weekly-20260913.dump"]
    assert not (backups / ".restore-ok").exists()


def test_un_database_di_prova_non_creato_ferma_tutto(tmp_path):
    result, _, log, calls = run_restore(tmp_path, PSQL_RC="1")
    assert result.returncode == 1
    assert calls == [FLOCK, DROP, CREATE, DROP]
    assert log == ["restore-start", "restore-FAIL database di prova non creato"]


def test_un_controllo_fallito_registra_solo_l_ultima_riga(tmp_path):
    result, backups, log, calls = run_restore(
        tmp_path, CHECK_RC="1", CHECK_OUT="Traceback (most recent call last):",
        CHECK_LINE="tabelle=15/16 righe=16 decifrate=15 illeggibili=1 orfani=0 ultimo_giro=mai esito=FALLITA")
    assert result.returncode == 1
    assert calls == [FLOCK, DROP, CREATE, RESTORE, REMOVE, CHECK, REMOVE, DROP]
    assert log == ["restore-start",
                   "restore-FAIL controllo rc=1 tabelle=15/16 righe=16 decifrate=15"
                   " illeggibili=1 orfani=0 ultimo_giro=mai esito=FALLITA"]
    assert "Traceback" not in (backups / "restore.log").read_text()
    assert not (backups / ".restore-ok").exists()


def test_la_pulizia_sta_in_una_trappola_sola():
    text = SCRIPT.read_text()
    assert "trap 'drop; trim' EXIT\n" in text
    assert "trap 'exit 1' INT TERM HUP\n" in text
    assert 'stop() { log "restore-FAIL $1"; exit 1; }\n' in text
    assert text.rstrip().splitlines()[-1].startswith("printf ")


def test_ogni_uscita_imprevista_cancella_il_database_di_prova(tmp_path):
    script, backups, fakebin = sandbox(tmp_path)
    text = script.read_text().replace('dk rm -f "$RUN" >/dev/null 2>&1\n', "exit 7\n", 1)
    assert "exit 7" in text
    script.write_text(text)
    env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", CALLS=str(tmp_path / "calls.txt"))
    result = subprocess.run(["sh", str(script)], env=env, timeout=60, capture_output=True, text=True)
    calls = [line for line in (tmp_path / "calls.txt").read_text().splitlines()
             if not line.startswith("timeout ")]
    assert result.returncode == 7
    assert calls == [FLOCK, DROP, CREATE, RESTORE, DROP]
    assert not (backups / ".restore-ok").exists()


def test_una_seconda_copia_non_si_sovrappone_al_backup(tmp_path):
    result, backups, log, calls = run_restore(tmp_path, FLOCK_RC="1")
    assert result.returncode == 0
    assert calls == [FLOCK]
    assert log == ["skip-busy"]


def test_il_log_resta_corto(tmp_path):
    script, backups, fakebin = sandbox(tmp_path)
    (backups / "restore.log").write_text("".join(f"[2026-09-01 00:00:00] vecchia {n}\n" for n in range(600)))
    env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", CALLS=str(tmp_path / "calls.txt"))
    subprocess.run(["sh", str(script)], env=env, timeout=60, check=True, capture_output=True)
    righe = (backups / "restore.log").read_text().splitlines()
    assert len(righe) == 500 and "restore-ok" in righe[-1]
