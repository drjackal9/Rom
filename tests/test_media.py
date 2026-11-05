import asyncio

import httpx
import pytest
from telegram.error import BadRequest, Forbidden

from clashbot import __main__ as cli
from clashbot import media

PNG = b"\x89PNG finta immagine"
URL = f"https://{media.BADGE_HOST}/badges/200/abc.png"


class FakeStore:
    def __init__(self, secrets=None, kv=None):
        self.secrets = dict(secrets or {})
        self.kv = dict(kv or {})
        self.saved = []
        self.deleted = []
        self.written = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def set_secret(self, kind, value):
        self.written[kind] = value
        return "sec-1"

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj
        self.saved.append((key, obj, ttl))

    async def kv_del(self, key):
        self.kv.pop(key, None)
        self.deleted.append(key)


class Photo:
    def __init__(self, file_id):
        self.file_id = file_id


class Sent:
    def __init__(self):
        self.photo = [Photo("file-piccolo"), Photo("file-grande")]


class FakeBot:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.calls.append((chat_id, photo, caption, kw))
        if self.error and len(self.calls) == 1:
            raise self.error
        return Sent()


class FakeMessage:
    def __init__(self, fail=False):
        self.photos = []
        self.texts = []
        self.fail = fail

    async def reply_photo(self, photo, caption=None):
        if self.fail:
            raise BadRequest("not enough rights to send photos")
        self.photos.append((photo, caption))
        return Sent()

    async def reply_text(self, text, **kw):
        self.texts.append((text, kw))
        return Sent()


@pytest.fixture(autouse=True)
def pulisci():
    media.forget()
    yield
    media.forget()


def test_la_didascalia_sta_nel_limite_vero_di_telegram():
    assert media.caption("riga") == ("riga", None)
    assert media.caption(None) == ("", None)
    assert media.units("⭐") == 1 and media.units("🙂") == 2
    lungo = "TITOLO\n" + "x" * 1100
    assert media.caption(lungo) == ("TITOLO", "x" * 1100)
    unica = "y" * 1100
    head, rest = media.caption(unica)
    assert media.units(head) == media.CAPTION_LIMIT and rest == unica
    tagliato = "z" * 1100 + "\ncoda"
    head, rest = media.caption(tagliato)
    assert media.units(head) == media.CAPTION_LIMIT and rest == tagliato


def test_la_foto_parte_e_il_file_id_resta_legato_al_suo_bot():
    store, bot = FakeStore(), FakeBot()
    assert asyncio.run(media.send_card(bot, store, "bot-1", 101, PNG, "didascalia", quiet=True)) is True
    chat, photo, caption, kw = bot.calls[0]
    assert (chat, photo, caption) == (101, PNG, "didascalia")
    assert kw == {"disable_notification": True}
    chiave = media._key("bot-1", PNG)
    assert store.saved == [(chiave, {"file_id": "file-grande"}, media.CARD_TTL)]
    assert chiave.startswith("card:bot-1:") and media._key("bot-2", PNG) != chiave
    ancora = FakeBot()
    assert asyncio.run(media.send_card(ancora, store, "bot-1", 101, PNG, "di nuovo")) is True
    assert ancora.calls[0][1] == "file-grande"


def test_un_file_id_rifiutato_si_dimentica_e_la_foto_si_ricarica():
    chiave = media._key("bot-1", PNG)
    store = FakeStore(kv={chiave: {"file_id": "file-vecchio"}})
    bot = FakeBot(error=BadRequest("wrong file identifier"))
    assert asyncio.run(media.send_card(bot, store, "bot-1", 101, PNG, "testo")) is True
    assert [call[1] for call in bot.calls] == ["file-vecchio", PNG]
    assert store.deleted == [chiave] and store.kv[chiave] == {"file_id": "file-grande"}


def test_se_telegram_non_vuole_la_foto_lo_dice_e_non_salva_niente():
    store, bot = FakeStore(), FakeBot(error=Forbidden("bot can't send media"))
    assert asyncio.run(media.send_card(bot, store, "bot-1", 101, PNG, "testo")) is False
    assert store.saved == [] and len(bot.calls) == 1
    store, bot = FakeStore(), FakeBot(error=BadRequest("photo dimensions invalid"))
    assert asyncio.run(media.send_card(bot, store, "bot-1", 101, PNG, "testo")) is False


def test_la_card_puo_andare_in_un_topic():
    store, bot = FakeStore(), FakeBot()
    asyncio.run(media.send_card(bot, store, "bot-1", 101, PNG, "t", thread_id=7))
    assert bot.calls[0][3] == {"disable_notification": False, "message_thread_id": 7}


def immagine(handler):
    async def prendi(url=URL):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await media.badge(url, client)

    return prendi


def test_lo_stemma_si_scarica_una_volta_e_solo_dal_sito_delle_risorse():
    chiamate = []

    def rispondi(request):
        chiamate.append(str(request.url))
        return httpx.Response(200, content=b"byte dello stemma", headers={"content-type": "image/png"})

    prendi = immagine(rispondi)
    assert asyncio.run(prendi()) == b"byte dello stemma"
    assert asyncio.run(prendi()) == b"byte dello stemma"
    assert len(chiamate) == 1
    assert asyncio.run(prendi("https://altro.example/stemma.png")) is None
    assert asyncio.run(prendi(None)) is None
    assert asyncio.run(prendi(f"http://{media.BADGE_HOST}/x.png")) is None
    assert len(chiamate) == 1


def test_uno_stemma_troppo_grande_o_che_non_e_una_immagine_viene_scartato():
    def grande(request):
        return httpx.Response(200, content=b"x" * (media.BADGE_LIMIT + 1),
                              headers={"content-type": "image/png"})

    def pagina(request):
        return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})

    def errore(request):
        raise httpx.ConnectError("niente rete", request=request)

    for handler in (grande, pagina, errore):
        media.forget()
        assert asyncio.run(immagine(handler)()) is None


def test_gli_stemmi_in_memoria_hanno_un_tetto():
    def rispondi(request):
        return httpx.Response(200, content=b"s", headers={"content-type": "image/png"})

    async def molti():
        async with httpx.AsyncClient(transport=httpx.MockTransport(rispondi)) as client:
            for i in range(media.BADGE_MEMO + 2):
                await media.badge(f"https://{media.BADGE_HOST}/b{i}.png", client)

    asyncio.run(molti())
    assert len(media._BADGES) <= media.BADGE_MEMO


def test_il_sito_si_legge_una_volta_sola_e_si_ricorda():
    store = FakeStore(secrets={"site_base": "https://clanboard.it"})
    letture = []
    vero = store.get_secret

    async def conta(kind):
        letture.append(kind)
        return await vero(kind)

    store.get_secret = conta
    assert asyncio.run(media.site_base(store)) == "https://clanboard.it"
    assert asyncio.run(media.site_base(store)) == "https://clanboard.it"
    assert letture == ["site_base"]
    media.forget()
    assert asyncio.run(media.site_base(FakeStore())) is None


def test_lanteprima_si_accende_solo_per_le_pagine_di_clanboard():
    assert media.hosts() == media.PREVIEW_HOSTS
    assert media.hosts("https://clanboard.it/x") == media.PREVIEW_HOSTS + ("clanboard.it",)
    assert media.hosts("non un indirizzo") == media.PREVIEW_HOSTS
    opzioni = media.preview('apri <a href="https://t.me/FuturoCoCBot?start=collega">qui</a>')
    assert opzioni.is_disabled is False
    assert opzioni.url == "https://t.me/FuturoCoCBot?start=collega"
    assert opzioni.prefer_large_media is True
    for testo in ("vedi https://esempio.it/pagina", "nessun link", None, "http://t.me/Bot",
                  "la pagina: https://clanboard.it/c/abc"):
        assert media.preview(testo).is_disabled is True
    con_sito = media.preview("la pagina: https://clanboard.it/c/abc.", "https://clanboard.it")
    assert con_sito.is_disabled is False and con_sito.url == "https://clanboard.it/c/abc"


def test_reply_mette_lanteprima_giusta_al_messaggio():
    store, message = FakeStore(), FakeMessage()
    asyncio.run(media.reply(message, store, 'apri <a href="https://t.me/Bot?start=collega">qui</a>'))
    opzioni = message.texts[0][1]["link_preview_options"]
    assert opzioni.is_disabled is False and opzioni.url.endswith("start=collega")
    asyncio.run(media.reply(message, store, "solo testo"))
    assert message.texts[1][1]["link_preview_options"].is_disabled is True


def test_card_reply_manda_la_foto_col_testo_in_didascalia(monkeypatch):
    monkeypatch.setattr(media.cards, "draw", lambda spec, badge=None: PNG)
    store, message = FakeStore(), FakeMessage()
    assert asyncio.run(media.card_reply(message, store, "bot-1", {"code": "it"}, None,
                                        "IL TUO PROFILO")) is True
    assert message.photos == [(PNG, "IL TUO PROFILO")] and message.texts == []


def test_card_reply_spezza_il_testo_lungo_e_ripiega_se_la_foto_non_passa(monkeypatch):
    monkeypatch.setattr(media.cards, "draw", lambda spec, badge=None: PNG)
    store, message = FakeStore(), FakeMessage()
    lungo = "TITOLO\n" + "x" * 1100
    assert asyncio.run(media.card_reply(message, store, "bot-1", {"code": "it"}, None, lungo)) is True
    assert message.photos == [(PNG, "TITOLO")] and message.texts[0][0] == "x" * 1100
    intero = FakeMessage()
    titolone = "z" * 1100 + "\ncoda"
    assert asyncio.run(media.card_reply(intero, FakeStore(), "bot-1", {"code": "it"}, None,
                                        titolone)) is True
    assert media.units(intero.photos[0][1]) == media.CAPTION_LIMIT
    assert intero.texts[0][0] == titolone
    negato = FakeMessage(fail=True)
    assert asyncio.run(media.card_reply(negato, FakeStore(), "bot-1", {"code": "it"}, None, "t")) is False
    assert negato.photos == [] and negato.texts == []


def test_il_sito_pubblico_e_un_segreto_della_piattaforma(capsys):
    assert "site_base" in cli.SECRET_KINDS
    assert "site_base" in cli.PLAIN_KINDS and "site_base" in cli.CLEARABLE_KINDS
    assert "site_base" not in cli.TOKEN_KINDS
    store = FakeStore()
    with pytest.raises(SystemExit):
        asyncio.run(cli.store_secret(store, "site_base", "http://clanboard.it"))
    asyncio.run(cli.store_secret(store, "site_base", "https://clanboard.it"))
    assert store.written == {"site_base": "https://clanboard.it"}
    capsys.readouterr()
