import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "vps" / "backup.sh"
RUN = "clashbot-retention"
FLOCK_CALL = "flock -n 9"
DUMP = "docker exec clashbot-db pg_dump -U postgres -d clashbot -Fc"
DUMP_CALL = f"timeout -k 60 1800 {DUMP}"
RETENTION = f"docker compose run --rm -T --no-deps --name {RUN} bot retention"
RETENTION_CALL = f"timeout -k 60 900 {RETENTION}"
REMOVE = f"docker rm -f {RUN}"
REMOVE_CALL = f"timeout -k 5 30 {REMOVE}"
USAGE = "uso: backup.sh [--no-retention]"
KEEP = 3
VECCHI = (
    "clashbot-20260901-030000.dump",
    "clashbot-20260902-030000.dump",
    "pre-switch-20260903-0300.dump",
    "clashbot-20260904-030000.dump",
)

FAKE_TIMEOUT = """#!/bin/sh
printf 'timeout %s\\n' "$*" >> "$CALLS"
case "$1 $2 $3" in
  "-k 60 1800"|"-k 60 900"|"-k 5 30") ;;
  *) exit 125 ;;
esac
shift 3
case " ${HANG:-} " in
  *" $2 "*) exit 124 ;;
esac
exec "$@"
"""

FAKE_DOCKER = """#!/bin/sh
printf 'docker %s\\n' "$*" >> "$CALLS"
case "$1" in
  exec)
    if [ -n "${WAIT:-}" ]; then
      printf 'dump-waiting\\n' >> "$CALLS"
      while [ ! -e "$WAIT" ]; do sleep 0.05; done
    fi
    printf 'dump-bytes'; exit 0 ;;
  rm) printf 'rm-noise\\n'; printf 'rm-noise\\n' >&2; exit 3 ;;
esac
[ -s "$KEYS/master.key" ] && printf 'key-before-retention\\n' >> "$CALLS"
printf 'righe cancellate: guerre_oltre_tetto=0\\n'
exit "${RETENTION_RC:-0}"
"""

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


def sandbox(tmp_path):
    backups = tmp_path / "backups"
    volume = tmp_path / "volume"
    app = tmp_path / "app"
    fakebin = tmp_path / "bin"
    for folder in (volume, app, fakebin):
        folder.mkdir()
    (volume / "master.key").write_bytes(b"master-key-bytes")
    text = SCRIPT.read_text()
    text = text.replace("/opt/clashbot-backups", str(backups))
    text = text.replace("/var/lib/docker/volumes/clashbot_clashbot-keys/_data/master.key", str(volume / "master.key"))
    text = text.replace("cd /opt/clashbot", f"cd {app}")
    assert "/opt/" not in text and "/var/lib/docker" not in text
    script = tmp_path / "backup.sh"
    script.write_text(text)
    for name, body in (("timeout", FAKE_TIMEOUT), ("docker", FAKE_DOCKER), ("flock", FAKE_FLOCK)):
        path = fakebin / name
        path.write_text(body)
        path.chmod(0o755)
    return script, backups, fakebin


def environment(fakebin, backups, calls, **extra):
    return dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", CALLS=str(calls), KEYS=str(backups / "keys"), **extra)


def read_log(backups):
    return [line.split("] ", 1)[1] for line in (backups / "backup.log").read_text().splitlines() if "] " in line]


def run_backup(tmp_path, args=(), prepare=None, **extra):
    script, backups, fakebin = sandbox(tmp_path)
    if prepare is not None:
        prepare(backups)
    calls = tmp_path / "calls.txt"
    subprocess.run(["sh", str(script), *args], env=environment(fakebin, backups, calls, **extra), timeout=30, check=True, capture_output=True)
    return backups, read_log(backups), calls.read_text().splitlines()


def aged(*names):
    def prepare(backups):
        (backups / "db").mkdir(parents=True, mode=0o700)
        for position, name in enumerate(names):
            path = backups / "db" / name
            path.write_bytes(b"vecchio")
            when = time.time() - (len(names) - position) * 86400
            os.utime(path, (when, when))
    return prepare


def dumps(backups):
    return sorted(path.name for path in (backups / "db").glob("*.dump"))


def fresh(backups, prepared):
    nuovi = [name for name in dumps(backups) if name not in prepared]
    assert len(nuovi) == 1
    assert (backups / "db" / nuovi[0]).read_bytes() == b"dump-bytes"
    return nuovi[0]


def events(log):
    return [line.split()[0] for line in log]


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_lo_script_e_sintatticamente_valido():
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True, timeout=30)


def test_i_backup_stanno_nella_cartella_di_clashbot():
    text = SCRIPT.read_text()
    assert "ROOT=/opt/clashbot-backups\n" in text
    assert "/opt/backups" not in text
    assert "puntovicino" not in text.lower()
    assert 'exec 9>"$ROOT/.backup.lock"' in text


def test_la_chiave_si_copia_prima_della_ritenzione_limitata_nel_tempo(tmp_path):
    backups, log, calls = run_backup(tmp_path)
    assert calls == [
        FLOCK_CALL,
        DUMP_CALL,
        DUMP,
        REMOVE_CALL,
        REMOVE,
        RETENTION_CALL,
        RETENTION,
        "key-before-retention",
    ]
    assert events(log) == ["db-ok", "key-ok", "retention-ok", "prune-ok", "done"]
    assert log[2] == "retention-ok righe cancellate: guerre_oltre_tetto=0"
    assert log[3] == "prune-ok tenuti=1 tolti=0"
    assert "rm-noise" not in (backups / "backup.log").read_text()


@pytest.mark.parametrize("extra, rc", [({"RETENTION_RC": "1"}, "1"), ({"HANG": "compose"}, "124")])
def test_una_ritenzione_fallita_o_scaduta_non_tocca_dump_e_chiave(tmp_path, extra, rc):
    backups, log, calls = run_backup(tmp_path, **extra)
    assert calls[:6] == [FLOCK_CALL, DUMP_CALL, DUMP, REMOVE_CALL, REMOVE, RETENTION_CALL]
    assert calls[-2:] == [REMOVE_CALL, REMOVE] and calls.count(REMOVE) == 2
    assert events(log) == ["db-ok", "key-ok", "retention-FAIL", "prune-ok", "done"]
    assert log[2] == f"retention-FAIL rc={rc}"
    assert "rm-noise" not in (backups / "backup.log").read_text()
    dumps = list((backups / "db").glob("clashbot-*.dump"))
    assert len(dumps) == 1 and dumps[0].read_bytes() == b"dump-bytes"
    assert (backups / "keys" / "master.key").read_bytes() == b"master-key-bytes"
    assert "master-key-bytes" not in "\n".join(log)


def test_un_dump_bloccato_scade_senza_ritenzione_e_la_chiave_si_salva(tmp_path):
    backups, log, calls = run_backup(tmp_path, HANG="exec")
    assert calls == [FLOCK_CALL, DUMP_CALL]
    assert events(log) == ["db-FAIL", "key-ok", "done"]
    assert list((backups / "db").iterdir()) == []
    assert (backups / "keys" / "master.key").read_bytes() == b"master-key-bytes"


def test_file_e_cartelle_dei_backup_sono_solo_di_root(tmp_path):
    backups, _, _ = run_backup(tmp_path)
    for folder in (backups, backups / "db", backups / "keys"):
        assert mode(folder) == 0o700
    dumps = list((backups / "db").glob("clashbot-*.dump"))
    for path in dumps + [backups / "backup.log", backups / "keys" / "master.key", backups / ".backup.lock"]:
        assert mode(path) == 0o600


def test_un_secondo_backup_non_si_sovrappone_al_primo(tmp_path):
    script, backups, fakebin = sandbox(tmp_path)
    release = tmp_path / "release"
    first_calls = tmp_path / "first.txt"
    first = subprocess.Popen(["sh", str(script)], env=environment(fakebin, backups, first_calls, WAIT=str(release)),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while not (first_calls.exists() and "dump-waiting" in first_calls.read_text()):
            assert first.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)
        second_calls = tmp_path / "second.txt"
        subprocess.run(["sh", str(script)], env=environment(fakebin, backups, second_calls), timeout=30, check=True, capture_output=True)
        assert second_calls.read_text().splitlines() == [FLOCK_CALL]
        assert events(read_log(backups)) == ["skip-busy"]
    finally:
        release.write_text("")
        first.wait(timeout=30)
    assert first.returncode == 0
    assert events(read_log(backups)) == ["skip-busy", "db-ok", "key-ok", "retention-ok", "prune-ok", "done"]
    assert len(list((backups / "db").glob("clashbot-*.dump"))) == 1


@pytest.mark.parametrize("flock_rc", ["65", "127"])
def test_se_il_lucchetto_non_funziona_il_backup_si_fa_lo_stesso(tmp_path, flock_rc):
    _, log, calls = run_backup(tmp_path, FLOCK_RC=flock_rc)
    assert calls[:3] == [FLOCK_CALL, DUMP_CALL, DUMP]
    assert events(log) == ["db-ok", "key-ok", "retention-ok", "prune-ok", "done"]


def test_senza_pulizia_restano_solo_dump_e_chiave(tmp_path):
    backups, log, calls = run_backup(tmp_path, args=["--no-retention"])
    assert calls == [FLOCK_CALL, DUMP_CALL, DUMP]
    assert events(log) == ["db-ok", "key-ok", "retention-skip", "done"]
    dumps = list((backups / "db").glob("clashbot-*.dump"))
    assert len(dumps) == 1 and dumps[0].read_bytes() == b"dump-bytes"
    assert (backups / "keys" / "master.key").read_bytes() == b"master-key-bytes"


def test_lo_script_tiene_un_numero_fisso_di_dump_e_non_fa_piu_il_settimanale():
    text = SCRIPT.read_text()
    assert f"KEEP_DUMPS={KEEP}\n" in text
    assert "weekly" not in text
    assert "-mtime" not in text


def test_la_pulizia_vera_lascia_solo_i_tre_dump_piu_recenti(tmp_path):
    backups, log, _ = run_backup(tmp_path, prepare=aged(*VECCHI))
    assert events(log) == ["db-ok", "key-ok", "retention-ok", "prune-ok", "done"]
    assert log[3] == f"prune-ok tenuti={KEEP} tolti=2"
    rimasti = dumps(backups)
    assert len(rimasti) == KEEP
    assert rimasti == sorted([fresh(backups, VECCHI), VECCHI[2], VECCHI[3]])
    assert not list((backups / "db").glob("weekly-*"))


def test_la_pulizia_toglie_anche_un_pre_switch_fra_i_piu_vecchi(tmp_path):
    prepared = ("pre-switch-20260901-0300.dump", "clashbot-20260902-030000.dump", "clashbot-20260903-030000.dump")
    backups, log, _ = run_backup(tmp_path, prepare=aged(*prepared))
    assert log[3] == f"prune-ok tenuti={KEEP} tolti=1"
    assert dumps(backups) == sorted([fresh(backups, prepared), prepared[1], prepared[2]])


def test_senza_pulizia_i_dump_vecchi_restano_tutti(tmp_path):
    backups, log, _ = run_backup(tmp_path, args=["--no-retention"], prepare=aged(*VECCHI))
    assert events(log) == ["db-ok", "key-ok", "retention-skip", "done"]
    assert dumps(backups) == sorted([fresh(backups, VECCHI), *VECCHI])


def test_se_il_dump_fallisce_i_dump_vecchi_non_si_toccano(tmp_path):
    backups, log, _ = run_backup(tmp_path, prepare=aged(*VECCHI), HANG="exec")
    assert events(log) == ["db-FAIL", "key-ok", "done"]
    assert dumps(backups) == sorted(VECCHI)


def test_un_argomento_sconosciuto_ferma_il_backup(tmp_path):
    script, backups, fakebin = sandbox(tmp_path)
    calls = tmp_path / "calls.txt"
    result = subprocess.run(["sh", str(script), "--pulisci-tutto"], env=environment(fakebin, backups, calls),
                            timeout=30, capture_output=True, text=True)
    assert result.returncode == 64
    assert result.stderr.strip() == USAGE
    assert not calls.exists() and not backups.exists()
