import io
import pathlib
import struct
import zlib

import PIL
from PIL import Image

from clashbot import cards, i18n

SPEC = {
    "kind": "war_end", "code": "it", "result": "win",
    "title": "VITTORIA! 83 - 74", "subtitle": "Futuro contro Clan Nemico",
    "score": {"left": {"name": "Futuro", "stars": 83, "destr": "97,4%"},
              "right": {"name": "Clan Nemico", "stars": 74, "destr": "91,0%"}},
    "rows": [{"rank": "1.", "name": "Mario", "value": "6", "extra": "100%"},
             {"rank": "2.", "name": "Luigi", "value": "5", "extra": "94%"},
             {"rank": "3.", "name": "Peach", "value": "5", "extra": "88%"}],
    "footer": "ClanBoard · #CLAN1",
}


def badge_bytes(side=256):
    art = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    middle = side // 2
    for y in range(side):
        for x in range(side):
            if (x - middle) ** 2 + (y - middle) ** 2 < (middle - 8) ** 2:
                art.putpixel((x, y), (32, 110, 214, 255) if y % 3 else (214, 64, 48, 255))
    out = io.BytesIO()
    art.save(out, format="PNG")
    return out.getvalue()


def bomb_bytes():
    side = int((2 * Image.MAX_IMAGE_PIXELS) ** 0.5) + 1

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
            + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b""))


def opened(png):
    with Image.open(io.BytesIO(png)) as img:
        return img.format, img.size


def test_pillow_e_fissato_nei_requisiti():
    requisiti = (pathlib.Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert "Pillow==12.3.0" in requisiti
    assert PIL.__version__ == "12.3.0"


def test_la_card_e_un_png_della_misura_dellanteprima():
    png = cards.draw(SPEC)
    assert png[:4] == b"\x89PNG"
    assert opened(png) == ("PNG", cards.SIZE) == ("PNG", (1200, 630))
    assert len(png) < 10 * 1024 * 1024
    assert sum(cards.SIZE) < 10000 and max(cards.SIZE) / min(cards.SIZE) < 20


def test_lo_stesso_spec_da_sempre_gli_stessi_byte():
    assert cards.draw(SPEC) == cards.draw(SPEC)
    assert cards.draw(dict(SPEC, result="lose")) != cards.draw(SPEC)


def test_lo_stemma_entra_nella_card_e_ne_decide_il_colore():
    art = badge_bytes()
    assert cards.accent(art) != cards.DEFAULT_ACCENT
    assert cards.accent(art) == cards.accent(art)
    assert cards.accent(None) == cards.DEFAULT_ACCENT
    assert cards.accent(b"non sono una immagine") == cards.DEFAULT_ACCENT
    assert cards.draw(SPEC, art) != cards.draw(SPEC)
    assert opened(cards.draw(SPEC, art)) == ("PNG", cards.SIZE)


def test_uno_stemma_enorme_o_rotto_non_ferma_la_card():
    assert opened(cards.draw(SPEC, badge_bytes(cards.MAX_BADGE_SIDE + 2))) == ("PNG", cards.SIZE)
    assert opened(cards.draw(SPEC, b"byte qualunque")) == ("PNG", cards.SIZE)
    bomba = bomb_bytes()
    assert len(bomba) < 1024
    assert cards.accent(bomba) == cards.DEFAULT_ACCENT
    assert opened(cards.draw(SPEC, bomba)) == ("PNG", cards.SIZE)
    assert cards.draw(SPEC, bomba) == cards.draw(SPEC)


def test_il_colore_viene_schiarito_fino_a_essere_leggibile():
    assert sum(cards._lift((10, 10, 40))) > sum((10, 10, 40))
    assert cards._lift(cards.DEFAULT_ACCENT) == cards.DEFAULT_ACCENT
    assert cards._lift((0, 0, 0)) == (0, 0, 0)


def test_le_righe_che_non_stanno_nel_riquadro_vengono_tagliate():
    assert cards.room(SPEC) == 3
    assert cards.room({"rows": []}) == 7
    assert cards.room({"chips": [{}] * 8}) == 2
    assert opened(cards.draw(dict(SPEC, rows=SPEC["rows"] * 5))) == ("PNG", cards.SIZE)


def test_il_testo_troppo_lungo_viene_accorciato_con_i_puntini():
    face = cards.font("it", 30, True)
    assert cards.fit("Mario", face, 400) == "Mario"
    accorciato = cards.fit("Clan con un nome davvero lunghissimo che non ci sta", face, 200)
    assert accorciato.endswith("…") and face.getlength(accorciato) <= 200
    assert cards.fit("", face, 10) == ""
    assert cards.fit("Mario", face, 0) == ""


def test_plain_toglie_i_tag_e_le_entita():
    assert cards.plain("<b>Ciao &amp; via</b>") == "Ciao & via"
    assert cards.plain("<blockquote>riga</blockquote>") == "riga"
    assert cards.plain(None) == ""


def test_ogni_lingua_ha_la_sua_scrittura_e_un_carattere():
    assert set(cards.SCRIPTS) == set(i18n.LANGUAGES)
    for code in i18n.LANGUAGES:
        assert cards.SCRIPTS[code] in cards.FACES, code
        assert hasattr(cards.font(code, 24), "getlength"), code


def test_i_caratteri_si_tengono_in_cache():
    assert cards.font("it", 30, True) is cards.font("it", 30, True)
    assert cards.font("it", 30, True) is not cards.font("it", 30)


def test_senza_file_del_carattere_si_usa_quello_incorporato_e_lo_si_dice():
    assert isinstance(cards.missing_scripts(), tuple)
    cards._FONTS.clear()
    salvato = cards.FACES["thai"]
    cards.FACES["thai"] = (("/nessun/carattere.ttf",), ("/nessun/carattere.ttf",))
    try:
        assert "thai" in cards.missing_scripts()
        assert hasattr(cards.font("th", 24), "getlength")
    finally:
        cards.FACES["thai"] = salvato
        cards._FONTS.clear()


def test_le_scritture_difficili_si_disegnano():
    assert cards.direction("ar") == "rtl" and cards.direction("it") is None
    arabo = dict(SPEC, code="ar", title="ألقاب الشهر", subtitle="سبتمبر ٢٠٢٦")
    assert opened(cards.draw(arabo)) == ("PNG", cards.SIZE)
    for code, titolo in (("zh-Hans", "本月称号"), ("ja", "今月の称号"), ("hi", "महीने के खिताब"),
                         ("th", "ตำแหน่งของเดือน"), ("ru", "Титулы месяца")):
        assert opened(cards.draw(dict(SPEC, code=code, title=titolo))) == ("PNG", cards.SIZE)
