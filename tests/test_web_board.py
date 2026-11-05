import asyncio

from clashbot import i18n, recruit
from clashbot.web import board
from clashbot.web import app as web_app
from test_web_status import FakeStore, request, same_dress

L = i18n.locale("en")
CODE = "ab12cd"
OTHER = "ef34gh"
SLUG = "abc123def456abcd"
TARGET = {"alias": "clan-a1", "tag": "#CLAN1", "bot": "PincoBot", "verified": True}


def row(code=CODE, lang="it", min_th=13, country="IT", name=None, tag=None, verified=True, **extra):
    return {"code": code, "level": 18, "members": 46, "free": 4, "league": "Cristallo I",
            "min_th": min_th, "country": country, "lang": lang, "type": "open",
            "war_frequency": "always", "labels": ["Clan Wars"], "name": name, "tag": tag,
            "verified": verified, **extra}


class BoardStore(FakeStore):
    def __init__(self, rows=(), target=None, live=()):
        super().__init__()
        self.rows = list(rows)
        self.target = target
        self.live = set(live)
        self.asked = None

    async def recruit_board(self, limit=20, country=None, min_th=None, lang=None):
        self.asked = {"limit": limit, "country": country, "min_th": min_th, "lang": lang}
        return list(self.rows)

    async def public_codes(self):
        return set(self.live)

    async def recruit_target(self, code):
        return self.target if code == CODE else None


class NetStore(BoardStore):
    async def recruit_board(self, limit=20, country=None, min_th=None, lang=None):
        rows = await super().recruit_board(limit, country, min_th, lang)
        kept = [one for one in rows if recruit.matches(one, country, min_th, lang)]
        return recruit.ordered(kept)[:limit]


def serve(store, path):
    return asyncio.run(web_app.Site(store).router(
        request(path, headers=b"Accept-Language: it\r\n")))


def test_the_filters_are_the_arguments_of_the_recruitment_search():
    assert board.wanted({}) == {"lang": None, "country": None, "min_th": None}
    assert board.wanted({"lang": ["it"], "country": ["it"], "th": ["14"]}) == {
        "lang": "it", "country": "IT", "min_th": 14}
    assert board.wanted({"lang": ["pinco"], "country": ["pinco"], "th": ["pinco"]}) == {
        "lang": None, "country": None, "min_th": None}
    assert board.wanted({"th": ["99"]})["min_th"] == board.TH_MAX
    assert board.wanted({"th": ["0"]})["min_th"] is None
    assert board.wanted({"country": ["i"]})["country"] is None


def test_the_page_asks_the_store_and_does_not_filter_a_second_time():
    store = BoardStore([row(lang="en", min_th=16, country="ES")])
    res = serve(store, "/board?lang=it&country=it&th=14")
    assert store.asked == {"limit": board.PAGE_SIZE, "country": "IT", "min_th": 14, "lang": "it"}
    assert L.t("web.board.anon", code=CODE) in res.body.decode()
    assert not hasattr(board, "keep") and not hasattr(board, "rows")
    assert not hasattr(board, "listing_payload")
    assert not hasattr(board, "ordered") and not hasattr(board, "matches")


def test_la_pagina_lascia_la_fila_che_lo_store_ha_gia_fatto():
    store = BoardStore([row(code=CODE, free=1), row(code=OTHER, free=9)])
    text = serve(store, "/board").body.decode()
    assert text.index(CODE) < text.index(OTHER)


def test_i_clan_con_piu_posti_stanno_davanti():
    store = NetStore([row(code=CODE, free=2), row(code=OTHER, free=9)])
    text = serve(store, "/board").body.decode()
    assert text.index(OTHER) < text.index(CODE)


def test_a_parita_di_posti_resta_davanti_l_aggiornamento_recente():
    fresco, vecchio = row(code=CODE, free=4), row(code=OTHER, free=4)
    assert [one["code"] for one in recruit.ordered([fresco, vecchio])] == [CODE, OTHER]
    assert [one["code"] for one in recruit.ordered([vecchio, fresco])] == [OTHER, CODE]


def test_il_municipio_scelto_esclude_chi_chiede_di_piu():
    store = NetStore([row(code=CODE, min_th=16), row(code=OTHER, min_th=13)])
    text = serve(store, "/board?th=15").body.decode()
    assert OTHER in text and CODE not in text
    assert L.t("recruit.req_th", th=13) in text


def test_la_bacheca_e_una_griglia_di_tessere_senza_liste_ne_moduli():
    text = serve(BoardStore([row(code=CODE), row(code=OTHER)]), "/board").body.decode()
    assert text.count('class="tile"') == 2 and text.count('class="grid three"') == 1
    assert "<ul" not in text and "<ol" not in text and 'class="card"' not in text
    assert "<form" not in text and "<select" not in text and "<input" not in text


def test_la_tessera_dice_posti_requisito_e_lingua_e_nient_altro():
    res = serve(BoardStore([row()]), "/board")
    text = res.body.decode()
    assert res.status == 200 and L.t("web.board.title") in text
    assert L.t("web.board.free", n=4) in text
    assert L.t("recruit.req_th", th=13) in text
    assert L.t("web.board.lang", lang="Italiano") in text
    assert L.t("web.board.anon", code=CODE) in text
    assert f"/r/{CODE}" in text and "t.me" not in text
    assert "Cristallo I" not in text and L.t("web.page.level", n=18) not in text
    assert "Clan Wars" not in text
    assert "X-Robots-Tag" not in res.headers


def test_la_tessera_porta_alla_pagina_accesa_o_alla_candidatura():
    store = BoardStore([row(code=CODE), row(code=OTHER)], live=[CODE])
    text = serve(store, "/board").body.decode()
    assert f'<a class="tile" href="/c/{CODE}"' in text
    assert f'<a class="tile" href="/r/{OTHER}"' in text
    assert f"/r/{CODE}" not in text and SLUG not in text
    assert L.t("web.board.page") in text and L.t("web.board.contact") in text


def test_i_filtri_sono_chip_che_portano_alla_stessa_bacheca():
    store = BoardStore([row(code=CODE, lang="it", country="IT")])
    text = serve(store, "/board").body.decode()
    assert text.count('class="chips"') == 3
    assert 'href="/board?lang=it"' in text and 'href="/board?country=IT"' in text
    for hall in (1, board.TH_MAX):
        assert f'href="/board?th={hall}"' in text, hall
    assert text.count('class="chip on"') == 3
    for label in ("web.board.filter_lang", "web.board.filter_country", "web.board.filter_th"):
        assert L.t(label) in text, label


def test_un_chip_scelto_tiene_le_altre_scelte_e_si_puo_togliere():
    store = BoardStore([row(code=CODE, lang="it", country="IT")])
    text = serve(store, "/board?lang=it&th=15").body.decode()
    assert '<a class="chip on" href="/board?lang=it&amp;th=15">' in text
    assert 'href="/board?lang=it&amp;country=IT&amp;th=15"' in text
    assert 'href="/board?th=15"' in text and 'href="/board?lang=it"' in text
    assert L.t("web.board.any") in text


def test_la_bacheca_della_rete_porta_lo_stesso_vestito_della_home():
    same_dress(serve(BoardStore([row()]), "/board").body.decode())
    same_dress(serve(BoardStore([]), "/board").body.decode())


def test_a_clan_without_a_requirement_says_anyone():
    assert L.t("recruit.req_any") in serve(BoardStore([row(min_th=None)]), "/board").body.decode()


def test_the_leader_who_signed_his_row_is_shown_by_name():
    text = serve(BoardStore([row(name="Futuro", tag="#CLAN1")]), "/board").body.decode()
    assert "Futuro" in text and "#CLAN1" in text
    assert L.t("web.board.anon", code=CODE) not in text


def test_an_empty_board_says_so_without_breaking():
    assert L.t("web.board.empty") in serve(BoardStore([]), "/board").body.decode()


def test_whatever_comes_from_the_game_is_escaped():
    text = serve(BoardStore([row(name="<b>x</b>", tag="#T", country="<i>y</i>")]),
                 "/board").body.decode()
    assert "<b>x</b>" not in text and "<i>y</i>" not in text and "&lt;b&gt;x&lt;/b&gt;" in text


def test_the_contact_hop_opens_the_apply_of_the_clan_bot():
    store = BoardStore([], TARGET)
    res = serve(store, f"/r/{CODE}")
    assert res.status == 302
    assert res.headers["Location"] == f"https://t.me/PincoBot?start=apply_{CODE}"
    assert res.headers["Cache-Control"] == "no-store"


def test_a_code_that_is_not_on_the_board_any_more_is_a_404():
    assert serve(BoardStore([], TARGET), "/r/altrocode").status == 404
    assert serve(BoardStore([], None), f"/r/{CODE}").status == 404
    assert serve(BoardStore([], {**TARGET, "bot": None}), f"/r/{CODE}").status == 404
    assert serve(BoardStore([], {**TARGET, "bot": "Pinco Bot"}), f"/r/{CODE}").status == 404
    assert serve(BoardStore([], TARGET), "/r/pinco.").status == 404
    assert serve(BoardStore([], TARGET), "/r/" + "a" * 40).status == 404


def test_an_unverified_clan_takes_no_contact():
    res = serve(BoardStore([], {**TARGET, "verified": False}), f"/r/{CODE}")
    assert res.status == 403 and "t.me" not in res.body.decode()
    assert L.t("recruit.unverified") in res.body.decode()


def test_the_verified_mark_is_only_for_the_verified_clan():
    text = serve(BoardStore([row(), row(code=OTHER, verified=False)]), "/board").body.decode()
    assert text.count(L.t("recruit.verified")) == 1


def test_the_deep_link_is_built_in_one_place():
    assert board.deep_link(TARGET, CODE) == f"https://t.me/PincoBot?start=apply_{CODE}"
    assert board.deep_link(None, CODE) == ""
    assert board.deep_link({"bot": ""}, CODE) == ""
    assert board.deep_link({"bot": "x" * (board.BOT_MAX + 1)}, CODE) == ""
