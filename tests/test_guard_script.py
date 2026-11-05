import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "vps" / "guard.sh"
RUN = "clashbot-guard"
TITLE = "ClanBoard guardiano"
FLOCK = ["flock", "-n", "9"]
REMOVE = ["docker", "rm", "-f", RUN]
NOTIFY = ["docker", "compose", "run", "--rm", "-T", "--no-deps", "--name", RUN, "bot", "notify"]
SHORT = ["timeout", "-k", "5", "30"]
LONG = ["timeout", "-k", "30", "120"]
FORMAT = "{{.Name}} {{.MemUsage}} {{.CPUPerc}}"
SANE_STATS = ("clashbot 61MiB / 3GiB 1.00%", "clashbot-db 44MiB / 11.68GiB 1.00%")
IDS = ["id-clashbot", "id-clashbot-db"]
CHECKS = [
    ["docker", "inspect", "-f", "{{.State.Status}}|{{.State.Health.Status}}|{{.State.OOMKilled}}", "clashbot"],
    ["docker", "inspect", "-f", "{{.State.Status}}|{{.State.Health.Status}}|{{.State.OOMKilled}}", "clashbot-db"],
    ["docker", "inspect", "-f", "{{.State.Status}}|{{.State.OOMKilled}}", "clashbot-tunnel"],
    ["docker", "exec", "clashbot-db", "psql", "-U", "postgres", "-d", "clashbot", "-tAc",
     "select pg_database_size('clashbot')"],
    ["docker", "ps", "--filter", "name=clashbot", "-q"],
    ["docker", "stats", "--no-stream", "--format", FORMAT] + IDS,
    ["docker", "logs", "clashbot", "--since", "30m"],
]
TS = r"\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\]"

RECORD = """{ printf '%s' "$(basename "$0")"; for a in "$@"; do printf '\\037%s' "$a"; done; printf '\\036'; } >> "$CALLS"
"""

FAKE_TIMEOUT = "#!/bin/sh\n" + RECORD + """case "$1 $2 $3" in
  "-k 5 30"|"-k 30 120") ;;
  *) exit 125 ;;
esac
shift 3
case " ${HANG:-} " in
  *" $2 "*) exit "${HANG_RC:-124}" ;;
esac
exec "$@"
"""

FAKE_DOCKER = "#!/bin/sh\n" + RECORD + """case "$1" in
  inspect)
    for name in "$@"; do :; done
    case "$name" in
      clashbot) state=${STATE_BOT:-running|healthy|false} ;;
      clashbot-db) state=${STATE_DB:-running|healthy|false} ;;
      clashbot-tunnel) state=${STATE_TUNNEL:-missing} ;;
      *) exit 1 ;;
    esac
    [ "$state" = missing ] && exit 1
    printf '%s\\n' "$state"; exit 0 ;;
  exec) printf '%s\\n' "${DB_BYTES:-0}"; exit 0 ;;
  ps)
    [ -n "${STATS:-}" ] && printf '%s' "$STATS" | sed 's/ .*//; s/^/id-/'
    exit 0 ;;
  stats) printf '%s\\n' "${STATS:-}"; exit 0 ;;
  logs) printf '%s' "${LOGS:-}"; exit 0 ;;
  rm) printf 'rm-noise\\n'; printf 'rm-noise\\n' >&2; exit 3 ;;
  compose)
    pwd > "$CWD"
    if [ -n "${WAIT:-}" ]; then
      while [ ! -e "$WAIT" ]; do sleep 0.05; done
    fi
    [ -n "${NOTIFY_OUT:-}" ] && printf '%s\\n' "$NOTIFY_OUT" >&2
    exit "${NOTIFY_RC:-0}" ;;
esac
exit 99
"""

FAKE_STAT = f"""#!/bin/sh
printf 'stat\\036' >> "$CALLS"
[ "$1" = -c ] && [ "$2" = %Y ] || exit 2
exec {sys.executable} -c 'import os, sys; print(int(os.stat(sys.argv[1]).st_mtime))' "$3"
"""

FAKE_FLOCK = f"""#!{sys.executable}
import fcntl, os, sys
with open(os.environ["CALLS"], "ab") as calls:
    calls.write(("\\x1f".join(["flock"] + sys.argv[1:]) + "\\x1e").encode())
if os.environ.get("FLOCK_RC"):
    sys.exit(int(os.environ["FLOCK_RC"]))
if sys.argv[1:] != ["-n", "9"]:
    sys.exit(64)
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(1)
"""

FAKE_CURL = "#!/bin/sh\n" + RECORD + "exit 0\n"


def sandbox(tmp_path, live=True):
    backups = tmp_path / "clashbot-backups"
    app = tmp_path / "app"
    fakebin = tmp_path / "bin"
    for folder in (backups / "db", backups / "keys", app, fakebin):
        folder.mkdir(parents=True)
    if live:
        (app / ".live").write_text("")
    text = SCRIPT.read_text()
    text = text.replace("/opt/clashbot-backups", str(backups))
    text = text.replace("/opt/clashbot/.live", str(app / ".live"))
    text = text.replace("cd /opt/clashbot ", f"cd {app} ")
    assert "/opt/" not in text
    script = tmp_path / "guard.sh"
    script.write_text(text)
    fakes = (("timeout", FAKE_TIMEOUT), ("docker", FAKE_DOCKER), ("stat", FAKE_STAT), ("flock", FAKE_FLOCK), ("curl", FAKE_CURL))
    for name, body in fakes:
        path = fakebin / name
        path.write_text(body)
        path.chmod(0o755)
    return script, backups, app, fakebin


def environment(tmp_path, fakebin, calls, **extra):
    return dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", CALLS=str(calls), CWD=str(tmp_path / "cwd.txt"), **extra)


def read_calls(calls):
    recorded = []
    if calls.exists():
        for entry in calls.read_bytes().decode().split("\x1e"):
            if entry:
                recorded.append(entry.split("\x1f"))
    return recorded


class FakeVps:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.script, self.backups, self.app, self.fakebin = sandbox(tmp_path)
        self.env = {}
        self.stats = "\n".join(SANE_STATS)
        self.calls = []
        self.result = None
        self.cwd = tmp_path / "cwd.txt"
        self.runs = 0
        self.healthy_backups()

    def docker_stats(self, *lines):
        self.stats = "\n".join(lines)

    def path(self, name):
        return self.backups / name

    def read(self, name):
        target = self.path(name)
        return target.read_text() if target.exists() else ""

    def write(self, name, text):
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def samples(self):
        return [json.loads(line) for line in self.read("metrics/samples.jsonl").splitlines()]

    def not_live(self):
        (self.app / ".live").unlink()

    def no_backups(self):
        for dump in (self.backups / "db").glob("*.dump"):
            dump.unlink()
        for name in ("keys/master.key", "backup.log"):
            target = self.path(name)
            if target.exists():
                target.unlink()

    def healthy_backups(self):
        self.no_backups()
        self.path("db/clashbot-20260912-043000.dump").write_bytes(b"dump")
        self.path("keys/master.key").write_bytes(b"master-key-bytes")
        self.write("backup.log", "[2026-09-11 04:30:01] retention-FAIL rc=1\n[2026-09-12 04:30:01] retention-ok righe cancellate: kv_scaduti=0\n")

    def stale_backups(self):
        self.no_backups()
        old = self.path("db/clashbot-20260909-043000.dump")
        old.write_bytes(b"dump")
        stamp = time.time() - 3 * 86400 - 3600
        os.utime(old, (stamp, stamp))
        self.write("backup.log", "[2026-09-11 04:30:01] retention-ok x\n[2026-09-12 04:30:01] retention-FAIL rc=124\n")

    def start(self):
        calls = self.tmp_path / f"calls-{self.runs}.bin"
        self.runs += 1
        env = environment(self.tmp_path, self.fakebin, calls, STATS=self.stats, **self.env)
        process = subprocess.Popen(["bash", str(self.script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return process, calls

    def collect(self, calls):
        self.calls += read_calls(calls)
        return self.calls

    @property
    def notified(self):
        return [call[-1] for call in self.calls if call[:2] == ["docker", "compose"]]


@pytest.fixture
def fake_vps(tmp_path):
    return FakeVps(tmp_path)


def run_guard(vps):
    process, calls = vps.start()
    out, err = process.communicate(timeout=30)
    vps.result = subprocess.CompletedProcess(process.args, process.returncode, out, err)
    vps.collect(calls)
    return vps.result


def without_stat(calls):
    return [call for call in calls if call != ["stat"]]


def bounded(call, limit=SHORT):
    return [limit + call, call]


def message(alerts):
    return f"{TITLE}\n{alerts}"


BROKEN = dict(
    STATE_BOT="exited|unhealthy|true",
    STATE_DB="missing",
    DB_BYTES=str(3 * 1024 * 1024 * 1024),
    LOGS="Traceback (most recent call last)\n2026 x ERROR y\ntutto bene\n",
)

BROKEN_STATS = ("clashbot 2150MiB / 3GiB 250.00%", "clashbot-db 1100MiB / 11.68GiB 1.00%")

EVERY_ALERT = "\n".join([
    "clashbot: exited",
    "clashbot: unhealthy",
    "clashbot: ucciso per memoria",
    "clashbot-db: container assente",
    "backup: ultimo dump di 3gg fa",
    "backup: chiave master non salvata",
    "ritenzione: ultima pulizia fallita",
    "database su disco: 3072 MB, oltre 2 GB",
    "clashbot: 2150 MB, oltre 2 GB",
    "clashbot: 2.50 core, oltre 2",
    "database in memoria: 1100 MB, oltre 1 GB",
    "log: 2 errori in 30 min",
])


def everything_broken(vps):
    vps.env.update(BROKEN)
    vps.docker_stats(*BROKEN_STATS)
    vps.stale_backups()


CHECK_CALLS = [step for check in CHECKS for step in bounded(check)]
PRE = len(CHECK_CALLS) + 1


def test_lo_script_e_sintatticamente_valido():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)


def test_senza_live_non_fa_nulla(fake_vps):
    everything_broken(fake_vps)
    fake_vps.not_live()
    result = run_guard(fake_vps)
    assert result.returncode == 0
    assert fake_vps.calls == []
    assert not fake_vps.path("guard.log").exists()
    assert not fake_vps.path(".guard.lock").exists()
    assert not fake_vps.path("metrics/samples.jsonl").exists()


def test_tutto_sano_nessun_avviso(fake_vps):
    result = run_guard(fake_vps)
    assert result.returncode == 0
    assert without_stat(fake_vps.calls) == [FLOCK] + CHECK_CALLS
    assert not fake_vps.path("guard.log").exists()
    assert fake_vps.path(".guard.lock").exists()


def test_ogni_controllo_produce_il_suo_avviso_e_lo_manda_con_notify(fake_vps):
    everything_broken(fake_vps)
    result = run_guard(fake_vps)
    assert result.returncode == 0
    calls = without_stat(fake_vps.calls)
    assert calls[:PRE] == [FLOCK] + CHECK_CALLS
    assert calls[PRE:] == bounded(REMOVE) + [LONG + NOTIFY + [message(EVERY_ALERT)], NOTIFY + [message(EVERY_ALERT)]]
    assert Path(fake_vps.cwd.read_text().strip()).resolve() == fake_vps.app.resolve()
    assert not fake_vps.path("guard.log").exists()
    assert [riga["alert"] for riga in fake_vps.samples()[1:]] == EVERY_ALERT.splitlines()


def test_backup_mancante_e_container_giu(fake_vps):
    fake_vps.no_backups()
    fake_vps.env["STATE_DB"] = "exited||false"
    run_guard(fake_vps)
    assert without_stat(fake_vps.calls)[-1] == NOTIFY + [message("clashbot-db: exited\nclashbot-db: \nbackup: nessun dump\nbackup: chiave master non salvata")]


def test_il_container_rimasto_si_rimuove_prima_dell_invio(fake_vps):
    fake_vps.env["STATE_BOT"] = "exited|unhealthy|false"
    run_guard(fake_vps)
    calls = without_stat(fake_vps.calls)
    assert calls.index(SHORT + REMOVE) + 1 == calls.index(REMOVE)
    assert calls.index(REMOVE) < calls.index(LONG + NOTIFY + [message("clashbot: exited\nclashbot: unhealthy")])


@pytest.mark.parametrize("extra, rc", [({"NOTIFY_RC": "1"}, "1"), ({"HANG": "compose"}, "124")])
def test_invio_fallito_scrive_gli_avvisi_con_orario_nel_log(fake_vps, extra, rc):
    everything_broken(fake_vps)
    fake_vps.env.update(extra)
    result = run_guard(fake_vps)
    assert result.returncode == 0
    calls = without_stat(fake_vps.calls)
    assert calls[PRE:PRE + 3] == bounded(REMOVE) + [LONG + NOTIFY + [message(EVERY_ALERT)]]
    assert calls[-2:] == bounded(REMOVE) and calls.count(REMOVE) == 2
    lines = fake_vps.read("guard.log").splitlines()
    assert re.fullmatch(f"{TS} notify-FAIL rc={rc}", lines[0])
    assert len(lines) == 1 + len(EVERY_ALERT.splitlines())
    for line, alert in zip(lines[1:], EVERY_ALERT.splitlines()):
        assert re.fullmatch(f"{TS} {re.escape(alert)}", line)
    assert "rm-noise" not in fake_vps.read("guard.log")
    assert "master-key-bytes" not in fake_vps.read("guard.log")
    assert TITLE not in fake_vps.read("guard.log")


def test_il_log_di_riserva_riporta_solo_il_motivo_noto_di_notify(fake_vps):
    output = "\n".join([
        "Traceback (most recent call last):",
        "  segreto-nel-traceback",
        "manca console_token: docker compose run --rm bot secret console_token",
        "rumore di compose",
        "avviso non inviato: Telegram 403: Forbidden: bot was blocked by the user",
    ])
    fake_vps.env.update(STATE_BOT="exited|healthy|false", NOTIFY_RC="1", NOTIFY_OUT=output)
    run_guard(fake_vps)
    text = fake_vps.read("guard.log")
    lines = text.splitlines()
    assert re.fullmatch(f"{TS} notify-FAIL rc=1", lines[0])
    assert re.fullmatch(f"{TS} notify: manca console_token: docker compose run --rm bot secret console_token", lines[1])
    assert re.fullmatch(f"{TS} notify: avviso non inviato: Telegram 403: Forbidden: bot was blocked by the user", lines[2])
    assert re.fullmatch(f"{TS} clashbot: exited", lines[3])
    assert len(lines) == 4
    assert "segreto-nel-traceback" not in text and "Traceback" not in text and "rumore" not in text


def test_il_log_di_riserva_si_accoda(fake_vps):
    fake_vps.no_backups()
    fake_vps.write("guard.log", "[2026-09-12 00:00:00] notify-FAIL rc=1\n[2026-09-12 00:00:00] vecchio\n")
    fake_vps.env["NOTIFY_RC"] = "1"
    result = run_guard(fake_vps)
    assert result.returncode == 0
    lines = fake_vps.read("guard.log").splitlines()
    assert lines[:2] == ["[2026-09-12 00:00:00] notify-FAIL rc=1", "[2026-09-12 00:00:00] vecchio"]
    assert re.fullmatch(f"{TS} notify-FAIL rc=1", lines[2])


def test_il_log_di_riserva_tiene_le_ultime_2000_righe(fake_vps):
    fake_vps.no_backups()
    fake_vps.write("guard.log", "".join(f"[2026-09-01 00:00:00] vecchio {i}\n" for i in range(2500)))
    fake_vps.env["NOTIFY_RC"] = "1"
    result = run_guard(fake_vps)
    assert result.returncode == 0
    lines = fake_vps.read("guard.log").splitlines()
    assert len(lines) == 2000
    assert lines[0] == "[2026-09-01 00:00:00] vecchio 503"
    assert lines[-4] == "[2026-09-01 00:00:00] vecchio 2499"
    assert re.fullmatch(f"{TS} notify-FAIL rc=1", lines[-3])
    assert lines[-2].endswith(" backup: nessun dump") and lines[-1].endswith(" backup: chiave master non salvata")
    assert not fake_vps.path("guard.log.tmp").exists()


@pytest.mark.parametrize("hang_rc", ["124", "137"])
def test_con_docker_bloccato_il_guardiano_finisce_e_lo_segnala(fake_vps, hang_rc):
    fake_vps.env.update(HANG="inspect exec ps stats logs rm compose", HANG_RC=hang_rc)
    started = time.monotonic()
    result = run_guard(fake_vps)
    assert time.monotonic() - started < 20
    assert result.returncode == 0
    calls = without_stat(fake_vps.calls)
    alerts = "clashbot: docker non risponde\nclashbot-db: docker non risponde\nclashbot-tunnel: docker non risponde"
    tentati = [SHORT + check for check in CHECKS if check[1] != "stats"]
    assert calls == [FLOCK] + tentati + [SHORT + REMOVE, LONG + NOTIFY + [message(alerts)], SHORT + REMOVE]
    lines = fake_vps.read("guard.log").splitlines()
    assert re.fullmatch(f"{TS} notify-FAIL rc={hang_rc}", lines[0])
    assert [line.split("] ", 1)[1] for line in lines[1:]] == alerts.splitlines()


def test_ogni_chiamata_a_docker_passa_da_timeout(fake_vps):
    everything_broken(fake_vps)
    fake_vps.env["NOTIFY_RC"] = "1"
    run_guard(fake_vps)
    calls = without_stat(fake_vps.calls)
    dockers = [i for i, call in enumerate(calls) if call[0] == "docker"]
    assert len(dockers) == 10
    for i in dockers:
        limit = LONG if calls[i][1] == "compose" else SHORT
        assert calls[i - 1] == limit + calls[i]
    for line in SCRIPT.read_text().splitlines():
        for match in re.finditer(r"\bdocker (inspect|exec|logs|rm|compose|ps|stats|run|stop|start|kill)\b", line):
            prefix = line[:match.start()]
            assert prefix.endswith("timeout -k 30 120 ") and match.group(1) == "compose" or prefix.endswith("timeout -k 5 30 ")
    assert re.search(r'^dk\(\) \{ timeout -k 5 30 docker "\$@"; \}$', SCRIPT.read_text(), re.M)


def test_una_seconda_copia_non_si_sovrappone_alla_prima(fake_vps):
    release = fake_vps.tmp_path / "release"
    fake_vps.env.update(STATE_BOT="exited|healthy|false", WAIT=str(release))
    first, first_calls = fake_vps.start()
    try:
        deadline = time.monotonic() + 20
        while not any(call[:2] == ["docker", "compose"] for call in read_calls(first_calls)):
            assert first.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)
        before = len(fake_vps.calls)
        second = run_guard(fake_vps)
        assert second.returncode == 0
        assert fake_vps.calls[before:] == [FLOCK]
    finally:
        release.write_text("")
        first.communicate(timeout=30)
    assert first.returncode == 0
    assert sum(call[:2] == ["docker", "compose"] for call in read_calls(first_calls)) == 1
    fake_vps.collect(first_calls)
    fake_vps.env.clear()
    before = len(fake_vps.calls)
    run_guard(fake_vps)
    assert without_stat(fake_vps.calls[before:]) == [FLOCK] + CHECK_CALLS


def test_con_il_lucchetto_occupato_esce_senza_controlli(fake_vps):
    everything_broken(fake_vps)
    fake_vps.env["FLOCK_RC"] = "1"
    result = run_guard(fake_vps)
    assert result.returncode == 0
    assert fake_vps.calls == [FLOCK]
    assert not fake_vps.path("guard.log").exists()
    assert not fake_vps.path("metrics/samples.jsonl").exists()


@pytest.mark.parametrize("flock_rc", ["65", "127"])
def test_se_il_lucchetto_non_funziona_i_controlli_girano_lo_stesso(fake_vps, flock_rc):
    fake_vps.env.update(FLOCK_RC=flock_rc, STATE_BOT="exited|healthy|false")
    result = run_guard(fake_vps)
    assert result.returncode == 0
    calls = without_stat(fake_vps.calls)
    assert calls[:PRE] == [FLOCK] + CHECK_CALLS
    assert calls[-1] == NOTIFY + [message("clashbot: exited")]


def test_i_controlli_nominano_solo_i_container_di_clashbot(fake_vps):
    everything_broken(fake_vps)
    fake_vps.env["NOTIFY_RC"] = "1"
    run_guard(fake_vps)
    containers = []
    for call in without_stat(fake_vps.calls):
        if call[0] != "docker" or call[1] == "compose":
            continue
        if call[1] == "rm":
            assert call == REMOVE
            continue
        if call[1] == "ps":
            assert call == ["docker", "ps", "--filter", "name=clashbot", "-q"]
            continue
        if call[1] == "stats":
            assert call[5:] == IDS
            continue
        assert call[1] in ("inspect", "logs", "exec")
        containers.append(call[-1] if call[1] == "inspect" else call[2])
    assert sorted(containers) == ["clashbot", "clashbot", "clashbot-db", "clashbot-db", "clashbot-tunnel"]
    assert not any(call[0] == "curl" for call in fake_vps.calls)


def test_il_tunnel_e_facoltativo_ma_se_c_e_deve_girare(fake_vps):
    run_guard(fake_vps)
    assert fake_vps.notified == []
    fake_vps.env["STATE_TUNNEL"] = "running|false"
    run_guard(fake_vps)
    assert fake_vps.notified == []
    fake_vps.env["STATE_TUNNEL"] = "exited|true"
    run_guard(fake_vps)
    assert fake_vps.notified[-1] == message("clashbot-tunnel: exited\nclashbot-tunnel: ucciso per memoria")


def test_senza_container_di_clashbot_non_si_chiedono_le_statistiche(fake_vps):
    fake_vps.docker_stats()
    run_guard(fake_vps)
    assert not any(call[0] == "docker" and call[1] == "stats" for call in fake_vps.calls)
    assert fake_vps.samples()[0]["containers"] == {}


def test_lo_script_non_nomina_altri_progetti():
    text = SCRIPT.read_text()
    assert "ntfy" not in text.lower()
    assert "puntovicino" not in text.lower()
    assert "/opt/backups" not in text
    assert "curl" not in text
    assert "/opt/clashbot-backups" in text
    assert re.findall(r"^for c in (.*); do$", text, re.M) == ["clashbot clashbot-db"]
    assert re.findall(r"\.lock", text) == [".lock"]
    assert 'exec 9>"$BACKUPS/.guard.lock"' in text
    assert re.search(r'^IDS=\$\(dk ps --filter name=clashbot -q ', text, re.M)
    assert re.search(r'^\[ -n "\$IDS" \] && USAGE=\$\(dk stats ', text, re.M)
    assert re.findall(r"dk stats", text) == ["dk stats"]


def test_guard_writes_a_sample_and_alerts_over_two_gb(fake_vps):
    fake_vps.docker_stats("clashbot 2150MiB / 3GiB 35.00%", "clashbot-db 300MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    sample = json.loads(fake_vps.read("metrics/samples.jsonl").splitlines()[-2])
    assert sample["containers"]["clashbot"]["mem_mb"] == 2150
    assert any("2 GB" in n or "2048" in n for n in fake_vps.notified)


def test_guard_alerts_once_per_db_gb_level(fake_vps):
    fake_vps.docker_stats("clashbot 100MiB / 3GiB 1.00%", "clashbot-db 1100MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    run_guard(fake_vps)
    assert len([n for n in fake_vps.notified if "database" in n.lower()]) == 1
    fake_vps.docker_stats("clashbot 100MiB / 3GiB 1.00%", "clashbot-db 2100MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    assert len([n for n in fake_vps.notified if "database" in n.lower()]) == 2


def test_guard_alerts_over_two_cores_and_drops_old_samples(fake_vps):
    fake_vps.write("metrics/samples.jsonl", json.dumps({"ts": 0, "containers": {}}) + "\n")
    fake_vps.docker_stats("clashbot 100MiB / 3GiB 250.00%", "clashbot-db 100MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    lines = fake_vps.read("metrics/samples.jsonl").splitlines()
    assert all(json.loads(l)["ts"] > 0 for l in lines)
    assert any("core" in n.lower() for n in fake_vps.notified)


def test_i_core_si_scrivono_col_punto_anche_con_la_lingua_imposta_da_lc_all(fake_vps):
    fake_vps.env["LC_ALL"] = "it_IT.UTF-8"
    fake_vps.docker_stats("clashbot 100MiB / 3GiB 250.00%", "clashbot-db 100MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    assert [n for n in fake_vps.notified if "core, oltre 2" in n] != []
    assert all("clashbot: 2.50 core, oltre 2" in n for n in fake_vps.notified if "core, oltre 2" in n)


def test_il_campione_porta_i_container_il_backup_e_la_ritenzione(fake_vps):
    run_guard(fake_vps)
    sample = fake_vps.samples()[0]
    assert sample["containers"] == {"clashbot": {"mem_mb": 61, "cpu": 0.01}, "clashbot-db": {"mem_mb": 44, "cpu": 0.01}}
    assert sample["backup_age_h"] == 0
    assert sample["retention"] == "ok"
    assert abs(sample["ts"] - time.time()) < 60


def test_senza_dump_e_senza_pulizia_il_campione_dice_niente(fake_vps):
    fake_vps.no_backups()
    run_guard(fake_vps)
    sample = fake_vps.samples()[0]
    assert sample["backup_age_h"] is None
    assert sample["retention"] is None


def test_la_ritenzione_fallita_finisce_nel_campione(fake_vps):
    fake_vps.stale_backups()
    run_guard(fake_vps)
    sample = fake_vps.samples()[0]
    assert sample["retention"] == "fail"
    assert sample["backup_age_h"] == 73


def test_i_campioni_di_sette_giorni_restano_e_i_piu_vecchi_no(fake_vps):
    resta = {"ts": int(time.time()) - 6 * 86400, "containers": {}}
    cade = {"ts": int(time.time()) - 8 * 86400, "containers": {}}
    fake_vps.write("metrics/samples.jsonl", json.dumps(cade) + "\n" + json.dumps(resta) + "\n")
    run_guard(fake_vps)
    tenuti = [sample["ts"] for sample in fake_vps.samples()]
    assert resta["ts"] in tenuti
    assert cade["ts"] not in tenuti


def test_i_campioni_si_leggono_anche_da_chi_non_e_root(fake_vps):
    run_guard(fake_vps)
    assert stat.S_IMODE(fake_vps.path("metrics/samples.jsonl").stat().st_mode) == 0o644


def test_la_memoria_del_bot_non_riavvisa_finche_resta_alta(fake_vps):
    fake_vps.docker_stats("clashbot 2150MiB / 3GiB 35.00%", "clashbot-db 44MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    run_guard(fake_vps)
    assert len([n for n in fake_vps.notified if "MB, oltre 2 GB" in n]) == 1
    fake_vps.docker_stats("clashbot 61MiB / 3GiB 35.00%", "clashbot-db 44MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    fake_vps.docker_stats("clashbot 2150MiB / 3GiB 35.00%", "clashbot-db 44MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    assert len([n for n in fake_vps.notified if "MB, oltre 2 GB" in n]) == 2


def test_la_cpu_del_bot_non_riavvisa_finche_resta_alta(fake_vps):
    fake_vps.docker_stats("clashbot 61MiB / 3GiB 250.00%", "clashbot-db 44MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    run_guard(fake_vps)
    assert len([n for n in fake_vps.notified if "core, oltre 2" in n]) == 1
    fake_vps.docker_stats("clashbot 61MiB / 3GiB 150.00%", "clashbot-db 44MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    fake_vps.docker_stats("clashbot 61MiB / 3GiB 250.00%", "clashbot-db 44MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    assert len([n for n in fake_vps.notified if "core, oltre 2" in n]) == 2


def test_i_giga_del_database_si_contano_anche_in_gibibyte(fake_vps):
    fake_vps.docker_stats("clashbot 61MiB / 3GiB 1.00%", "clashbot-db 2.5GiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    assert [n for n in fake_vps.notified if "database" in n] == [message("database in memoria: 2560 MB, oltre 2 GB")]
    assert fake_vps.read("metrics/db_gb.level").strip() == "2"


def test_il_database_su_disco_ha_il_suo_avviso_accanto_a_quello_in_memoria(fake_vps):
    fake_vps.env["DB_BYTES"] = str(3 * 1024 * 1024 * 1024)
    run_guard(fake_vps)
    assert fake_vps.notified == [message("database su disco: 3072 MB, oltre 2 GB")]
    fake_vps.env["DB_BYTES"] = str(2 * 1024 * 1024 * 1024)
    run_guard(fake_vps)
    assert len(fake_vps.notified) == 1


def test_un_database_muto_o_illeggibile_non_inventa_avvisi(fake_vps):
    fake_vps.env["DB_BYTES"] = "psql: non ci arrivo"
    run_guard(fake_vps)
    assert fake_vps.notified == []


def test_la_ritenzione_in_corso_non_si_spaccia_per_il_bot(fake_vps):
    fake_vps.docker_stats("clashbot 2150MiB / 3GiB 35.00%",
                          "clashbot-db 44MiB / 11.68GiB 1.00%",
                          "clashbot-retention 2500MiB / 3GiB 250.00%")
    run_guard(fake_vps)
    assert fake_vps.notified == [message("clashbot: 2150 MB, oltre 2 GB")]
    assert fake_vps.samples()[0]["containers"]["clashbot-retention"]["mem_mb"] == 2500


def with_restore(vps, last, mark_days=0):
    vps.write("restore.log", f"[2026-09-06 05:20:01] restore-ok vecchia\n[2026-09-13 05:20:01] {last}\n")
    if mark_days is not None:
        mark = vps.path(".restore-ok")
        mark.write_text("weekly-20260913.dump\n")
        stamp = time.time() - mark_days * 86400 - 3600
        os.utime(mark, (stamp, stamp))


def test_una_prova_di_ripristino_fallita_diventa_un_avviso(fake_vps):
    with_restore(fake_vps, "restore-FAIL controllo rc=1")
    run_guard(fake_vps)
    assert without_stat(fake_vps.calls)[-1] == NOTIFY + [message("ripristino: ultima prova fallita")]


def test_una_prova_di_ripristino_vecchia_diventa_un_avviso(fake_vps):
    with_restore(fake_vps, "restore-ok weekly x", mark_days=9)
    run_guard(fake_vps)
    assert without_stat(fake_vps.calls)[-1] == NOTIFY + [message("ripristino: ultima prova riuscita di 9gg fa")]


def test_una_prova_di_ripristino_recente_non_dice_niente(fake_vps):
    with_restore(fake_vps, "restore-ok weekly x", mark_days=2)
    result = run_guard(fake_vps)
    assert result.returncode == 0
    assert without_stat(fake_vps.calls) == [FLOCK] + CHECK_CALLS
    assert not fake_vps.path("guard.log").exists()


def test_senza_nessuna_prova_riuscita_il_guardiano_lo_dice(fake_vps):
    with_restore(fake_vps, "restore-ok weekly x", mark_days=None)
    run_guard(fake_vps)
    assert without_stat(fake_vps.calls)[-1] == NOTIFY + [message("ripristino: nessuna prova riuscita")]


def test_il_guardiano_rimasto_acceso_non_si_spaccia_per_il_bot(fake_vps):
    fake_vps.docker_stats("clashbot 61MiB / 3GiB 1.00%",
                          "clashbot-guard 2500MiB / 3GiB 250.00%",
                          "clashbot-db 1100MiB / 11.68GiB 1.00%")
    run_guard(fake_vps)
    assert fake_vps.notified == [message("database in memoria: 1100 MB, oltre 1 GB")]
