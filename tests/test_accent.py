import asyncio
import io
from types import SimpleNamespace

import httpx
from PIL import Image

from clashbot import accent, media, publish
from clashbot.crypto import Vault
from clashbot.events import member_snapshot
from clashbot.web import payload
from fixtures import BASE_MEMBERS, clan_json
from test_web_publish import CLAN, INFO, NOW, WebStore, tick_for

BADGE = "https://api-assets.clashofclans.com/badges/200/uno.png"
OTHER = "https://api-assets.clashofclans.com/badges/200/due.png"
SIDE = 16
RED = (255, 0, 0, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
CONF = {"lang": "it", "tz": "Europe/Rome"}


def png(top, bottom):
    art = Image.new("RGBA", (SIDE, SIDE), bottom)
    for y in range(SIDE // 2):
        for x in range(SIDE):
            art.putpixel((x, y), top)
    kept = io.BytesIO()
    art.save(kept, format="PNG")
    return kept.getvalue()


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    async def get(self, url):
        self.calls += 1
        return SimpleNamespace(status_code=200, content=self.data,
                               headers={"content-type": "image/png"})


class BrokenClient:
    def __init__(self):
        self.calls = 0

    async def get(self, url):
        self.calls += 1
        raise httpx.ConnectError("rete assente")


def beat_with(store, client):
    return publish.Beat(store, None, None, None, clock=lambda: 0.0, client=client)


def published(beat, info):
    return asyncio.run(beat.app(CLAN, tick_for().settings,
                                member_snapshot(clan_json(BASE_MEMBERS)), info, NOW))


def test_il_colore_del_clan_e_la_tinta_dello_stemma():
    assert accent.dominant(png(RED, WHITE)) == "#ff0000"


def test_lo_stemma_senza_tinte_non_da_colore():
    assert accent.dominant(png(BLACK, WHITE)) is None
    assert accent.dominant(b"non una png") is None
    assert accent.dominant(None) is None


def test_lo_stato_dell_app_porta_il_colore_del_clan():
    body = payload.app_payload(CLAN, CONF, INFO, {}, None, "war", None, {}, {}, {}, {}, NOW,
                               accent="#ff0000")
    assert body["clan"]["accent"] == "#ff0000"
    assert payload.app_payload(CLAN, CONF, INFO, {}, None, "war", None, {}, {}, {}, {},
                               NOW)["clan"]["accent"] is None


def test_il_colore_si_calcola_una_volta_sola_per_stemma(tmp_path):
    store = WebStore(Vault(tmp_path))
    client = FakeClient(png(RED, WHITE))
    beat = beat_with(store, client)
    assert published(beat, dict(INFO, badge=BADGE)) is True
    body = store.pages[(CLAN.alias, payload.APP)][1]
    assert body["clan"]["accent"] == "#ff0000"
    assert client.calls == 1
    assert asyncio.run(store.get_state(CLAN.alias, publish.ACCENT)) == {BADGE: "#ff0000"}
    media.forget()
    published(beat, dict(INFO, badge=BADGE))
    assert client.calls == 1


def test_uno_stemma_nuovo_rifa_il_colore(tmp_path):
    store = WebStore(Vault(tmp_path))
    client = FakeClient(png(RED, WHITE))
    beat = beat_with(store, client)
    published(beat, dict(INFO, badge=BADGE))
    media.forget()
    published(beat, dict(INFO, badge=OTHER))
    assert client.calls == 2
    assert asyncio.run(store.get_state(CLAN.alias, publish.ACCENT)) == {OTHER: "#ff0000"}


def test_lo_stemma_senza_tinte_si_calcola_una_volta_sola(tmp_path):
    store = WebStore(Vault(tmp_path))
    client = FakeClient(png(BLACK, WHITE))
    beat = beat_with(store, client)
    published(beat, dict(INFO, badge=BADGE))
    assert store.pages[(CLAN.alias, payload.APP)][1]["clan"]["accent"] is None
    assert client.calls == 1
    assert asyncio.run(store.get_state(CLAN.alias, publish.ACCENT)) == {BADGE: None}
    media.forget()
    published(beat, dict(INFO, badge=BADGE))
    assert client.calls == 1


def test_lo_stemma_non_scaricato_si_riprova(tmp_path):
    store = WebStore(Vault(tmp_path))
    client = BrokenClient()
    beat = beat_with(store, client)
    published(beat, dict(INFO, badge=BADGE))
    assert store.pages[(CLAN.alias, payload.APP)][1]["clan"]["accent"] is None
    assert asyncio.run(store.get_state(CLAN.alias, publish.ACCENT)) is None
    media.forget()
    published(beat, dict(INFO, badge=BADGE))
    assert client.calls == 2


def test_senza_stemma_nessuno_scarica_niente(tmp_path):
    store = WebStore(Vault(tmp_path))
    client = FakeClient(png(RED, WHITE))
    assert published(beat_with(store, client), dict(INFO)) is True
    assert store.pages[(CLAN.alias, payload.APP)][1]["clan"]["accent"] is None
    assert client.calls == 0
