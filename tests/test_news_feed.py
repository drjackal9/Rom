import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from clashbot import agenda, base_videos, integration_tools, news_feed

FINTA = "chiave-finta-di-prova"
CANALE = "UCufficiale"
ALTRO = "UCbuilder"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
INIZIO = "20260901T080000.000Z"
FINE = "20260929T050000.000Z"
GOLDPASS = {"startTime": INIZIO, "endTime": FINE}
UPLOADS = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUufficiale"}}}]}
CARICAMENTI = {"items": [
    {"snippet": {"resourceId": {"videoId": "vid1"}, "title": "Aggiornamento di ottobre",
                 "publishedAt": "2026-09-22T10:00:00Z", "description": "niente link"}},
]}


class FakeStore:
    def __init__(self, channels=(), videos=(), kv=None):
        self.kv = dict(kv or {})
        self.videos = list(videos)
        self.saved = []
        self.scopes = []
        if channels:
            self.kv[base_videos.CHANNELS_KEY] = list(channels)

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def videos_rows(self, scope=None, limit=None):
        self.scopes.append(scope)
        return list(self.videos)

    async def videos_put(self, rows):
        self.saved.extend(rows)
        return len(rows)


class FakeCoc:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
        self.calls = 0

    async def goldpass(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.data, None


class FakeClient:
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.urls = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        for piece, body in self.replies:
            if piece in url:
                return SimpleNamespace(status_code=200, json=lambda body=body: body)
        raise AssertionError(f"nessuna risposta per {base_videos.masked(url)}")


def answering():
    return FakeClient([("/channels?", UPLOADS), ("/playlistItems?", CARICAMENTI)])


def official(id=CANALE, title="Clash of Clans"):
    return {"id": id, "title": title, base_videos.OFFICIAL: True}


def clip(id="vid1", channel=CANALE, published="2026-09-22T10:00:00Z"):
    return {"id": id, "channel": channel, "title": "Aggiornamento di ottobre",
            "published": published, "links": []}


def kinds(rows):
    return {row["kind"] for row in rows}


def of_kind(rows, kind):
    return [row for row in rows if row["kind"] == kind]


def collect(store, coc=None, client=None, key=FINTA, now=NOW):
    return asyncio.run(news_feed.collect(store, client or answering(), key,
                                         coc if coc is not None else FakeCoc(GOLDPASS), now))


def test_le_righe_sono_delle_tre_specie_e_non_portano_mai_la_chiave_di_youtube():
    store = FakeStore(channels=[official()], videos=[clip()])
    rows = collect(store)
    assert kinds(rows) == set(news_feed.KINDS)
    assert store.kv[news_feed.ROWS_KEY] == rows
    assert FINTA not in json.dumps(store.kv, default=str)
    assert of_kind(rows, news_feed.VIDEO) == [
        {"kind": news_feed.VIDEO, "id": "vid1", "title": "Aggiornamento di ottobre",
         "published": "2026-09-22T10:00:00Z"}]


def test_il_pass_oro_porta_inizio_e_fine_della_stagione():
    store = FakeStore(channels=[official()], videos=[clip()])
    row = of_kind(collect(store), news_feed.GOLDPASS)[0]
    assert row["start"] == int(datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc).timestamp())
    assert row["end"] == int(datetime(2026, 9, 29, 5, 0, tzinfo=timezone.utc).timestamp())


def test_gli_appuntamenti_sono_quelli_dell_agenda_con_la_fine_del_pass():
    store = FakeStore(channels=[official()], videos=[clip()])
    rows = of_kind(collect(store), news_feed.EVENT)
    attesi = agenda.upcoming(NOW, FINE)
    assert [row["key"] for row in rows] == [item["key"] for item in attesi]
    assert [row["state"] for row in rows] == [item["state"] for item in attesi]
    assert rows[0]["start"] == int(attesi[0]["start"].timestamp())
    assert all(isinstance(row["end"], int) for row in rows)


def test_i_video_arrivano_solo_dal_canale_segnato_ufficiale():
    store = FakeStore(channels=[official(), {"id": ALTRO, "title": "Builder"}],
                      videos=[clip(), clip("vid2", channel=ALTRO)])
    rows = collect(store)
    assert [row["id"] for row in of_kind(rows, news_feed.VIDEO)] == ["vid1"]
    store = FakeStore(channels=[{"id": ALTRO, "title": "Builder"}], videos=[clip("vid2", ALTRO)])
    rows = collect(store)
    assert of_kind(rows, news_feed.VIDEO) == []
    assert of_kind(rows, news_feed.EVENT)


def test_il_pass_oro_si_chiede_una_volta_al_giorno():
    store = FakeStore(channels=[official()], videos=[clip()])
    coc = FakeCoc(GOLDPASS)
    collect(store, coc)
    collect(store, coc, now=NOW + timedelta(seconds=news_feed.SEASON_TTL - 1))
    assert coc.calls == 1
    collect(store, coc, now=NOW + timedelta(seconds=news_feed.SEASON_TTL))
    assert coc.calls == 2
    assert store.kv[news_feed.SEASON_KEY]["end"] == FINE


def test_senza_righe_salvate_il_canale_ufficiale_si_chiede_una_volta_sola():
    store = FakeStore(channels=[official()])
    client = answering()
    rows = collect(store, client=client)
    assert [row["id"] for row in of_kind(rows, news_feed.VIDEO)] == ["vid1"]
    assert [row["id"] for row in store.saved] == ["vid1"]
    assert len(client.urls) == 2
    assert all(FINTA not in json.dumps(row) for row in rows)


def test_la_quota_finita_non_fa_chiedere_niente_a_youtube():
    store = FakeStore(channels=[official()],
                      kv={base_videos.QUOTA_KEY: {"until": NOW.timestamp() + 3600}})
    client = answering()
    rows = collect(store, client=client)
    assert client.urls == [] and of_kind(rows, news_feed.VIDEO) == []
    assert of_kind(rows, news_feed.EVENT)


def test_senza_chiave_le_notizie_restano_quelle_del_gioco():
    store = FakeStore(channels=[official()])
    client = answering()
    rows = collect(store, client=client, key=None)
    assert client.urls == [] and of_kind(rows, news_feed.VIDEO) == []
    assert kinds(rows) == {news_feed.GOLDPASS, news_feed.EVENT}


def test_il_pass_oro_rotto_non_toglie_gli_appuntamenti_ne_i_video():
    store = FakeStore(channels=[official()], videos=[clip()])
    collect(store)
    rotto = FakeCoc(error=RuntimeError("giù"))
    rows = collect(store, rotto, now=NOW + timedelta(seconds=news_feed.SEASON_TTL))
    assert rotto.calls == 1
    assert kinds(rows) == set(news_feed.KINDS)


def test_una_fonte_rotta_non_cancella_le_righe_gia_raccolte():
    store = FakeStore(channels=[official()], videos=[clip()])
    prima = collect(store)

    async def rotto(scope=None, limit=None):
        raise RuntimeError("giù")

    store.videos_rows = rotto
    assert collect(store) == []
    assert store.kv[news_feed.ROWS_KEY] == prima


def test_il_canale_ufficiale_si_accende_e_si_spegne_dal_pannello():
    store = FakeStore(channels=[{"id": ALTRO, "title": "Builder"}, {"id": CANALE, "title": "CoC"}])
    assert asyncio.run(base_videos.mark_official(store, "UCmai")) is False
    assert asyncio.run(base_videos.mark_official(store, CANALE)) is True
    rows = asyncio.run(base_videos.platform_rows(store))
    assert base_videos.official_in(rows) == CANALE
    assert rows[0] == {"id": ALTRO, "title": "Builder"}
    assert asyncio.run(base_videos.mark_official(store, ALTRO)) is True
    assert base_videos.official_in(asyncio.run(base_videos.platform_rows(store))) == ALTRO
    assert asyncio.run(base_videos.mark_official(store, ALTRO)) is True
    assert base_videos.official_in(asyncio.run(base_videos.platform_rows(store))) is None


def test_una_stagione_gia_finita_non_finisce_tra_le_notizie():
    store = FakeStore(channels=[official()], videos=[clip()])
    dopo = NOW + timedelta(days=30)
    rows = collect(store, now=dopo)
    assert of_kind(rows, news_feed.GOLDPASS) == []
    assert kinds(rows) == {news_feed.EVENT, news_feed.VIDEO}


def test_la_stagione_del_pass_ha_un_lettore_solo():
    root = Path(news_feed.__file__).parent
    raw = f'kv_get("{news_feed.SEASON_KEY}")'
    letti = [path.name for path in sorted(root.glob("*.py"))
             if raw in path.read_text(encoding="utf-8")
             or "kv_get(SEASON_KEY)" in path.read_text(encoding="utf-8")]
    assert letti == ["news_feed.py"]


def test_la_fine_del_pass_arriva_dalla_copia_senza_chiamare_il_gioco():
    store = FakeStore(kv={news_feed.SEASON_KEY: {"start": INIZIO, "end": FINE, "fetched": 0}})
    assert asyncio.run(integration_tools.goldpass_end(store)) == FINE
    vuoto = FakeStore()
    assert asyncio.run(integration_tools.goldpass_end(vuoto)) is None
