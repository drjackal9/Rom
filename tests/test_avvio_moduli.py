import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTESA = 120
AVVII = ("clashbot.platform", "clashbot.console", "clashbot.reports", "clashbot.site_days",
         "clashbot.web.app", "clashbot.web.security", "clashbot.bot")


def importa(nome):
    return subprocess.run([sys.executable, "-c", "import " + nome], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=ATTESA)


def test_ogni_avvio_si_importa_da_solo_senza_giro_di_import():
    rotti = {}
    for nome in AVVII:
        fatto = importa(nome)
        if fatto.returncode:
            rotti[nome] = (fatto.stderr.strip().splitlines() or [""])[-1]
    assert rotti == {}
