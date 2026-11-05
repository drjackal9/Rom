import asyncio
import os
import re
from pathlib import Path

import pytest

from clashbot import __main__ as cli, tunnel

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "docker-compose.yml"
TOKEN = "eyJhIjoiMjM0NzdjYTAiLCJ0IjoiZjRhMSIsInMiOiJOak0zIn0="


class SecretStore:
    def __init__(self):
        self.saved = {}

    async def set_secret(self, kind, value):
        self.saved[kind] = value
        return "sec-000000"

    async def delete_secret(self, kind):
        return self.saved.pop(kind, None) is not None


def test_il_token_del_tunnel_e_una_riga_sola_senza_spazi():
    assert tunnel.valid(TOKEN)
    for bad in ("", " ", TOKEN + " ", "a b", "a\nb", " " + TOKEN):
        assert not tunnel.valid(bad), repr(bad)


def test_il_file_del_tunnel_nasce_chiuso_e_si_sostituisce_intero(tmp_path):
    target = tunnel.write(TOKEN, tmp_path)
    assert target == tmp_path / tunnel.TOKEN_FILE
    assert target.read_text(encoding="utf-8") == TOKEN + "\n"
    assert oct(os.stat(target).st_mode & 0o777) == "0o600"
    tunnel.write("altro", tmp_path)
    assert target.read_text(encoding="utf-8") == "altro\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [tunnel.TOKEN_FILE]


def test_togliere_il_file_dice_se_c_era(tmp_path):
    assert tunnel.remove(tmp_path) is False
    tunnel.write(TOKEN, tmp_path)
    assert tunnel.remove(tmp_path) is True
    assert not (tmp_path / tunnel.TOKEN_FILE).exists()


def test_il_segreto_tunnel_token_finisce_nel_vault_e_nel_file_e_il_meno_lo_toglie(tmp_path, monkeypatch):
    monkeypatch.setattr(tunnel, "KEY_DIR", str(tmp_path))
    store = SecretStore()
    assert "tunnel_token" in cli.SECRET_KINDS and "tunnel_token" in cli.CLEARABLE_KINDS
    assert "tunnel_token" not in cli.PLAIN_KINDS
    with pytest.raises(SystemExit) as refused:
        asyncio.run(cli.store_secret(store, "tunnel_token", "due parole"))
    assert "due parole" not in str(refused.value) and store.saved == {}
    asyncio.run(cli.store_secret(store, "tunnel_token", TOKEN))
    assert store.saved == {"tunnel_token": TOKEN}
    assert (tmp_path / tunnel.TOKEN_FILE).read_text(encoding="utf-8") == TOKEN + "\n"
    asyncio.run(cli.store_secret(store, "tunnel_token", cli.CLEAR_VALUE))
    assert store.saved == {} and not (tmp_path / tunnel.TOKEN_FILE).exists()


def test_il_container_del_tunnel_legge_solo_il_file_e_non_apre_porte():
    text = COMPOSE.read_text(encoding="utf-8")
    block = text.split("\n  tunnel:")[1].split("\n\nnetworks:")[0]
    assert "container_name: clashbot-tunnel" in block
    assert re.search(r"image: cloudflare/cloudflared:\d{4}\.\d+\.\d+\n", block)
    assert '"--token-file", "/keys/tunnel.token"' in block and '"--no-autoupdate"' in block
    assert "clashbot-keys:/keys:ro" in block and "ports:" not in block
    assert 'user: "1000:1000"' in block and "useradd -m -u 1000 bot" in (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "      - interno\n      - default" in block
    assert "mem_limit:" in block and "max-size: 10m" in block
    web = text.split("\n  web:")[1].split("\n  tunnel:")[0]
    assert "      - default" not in web
