import json
from types import SimpleNamespace

from clashbot import bridge, i18n, render

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
GOOD = {"token": "dtok-1", "guild_id": 5, "guild_name": "Server", "channel_id": 9, "channel_name": "clan"}


def test_la_configurazione_vale_solo_se_ha_token_e_canale():
    assert bridge.config(GOOD)["channel_id"] == 9
    assert bridge.config(dict(GOOD, channel_id="9"))["channel_id"] == 9
    for bad in (None, {}, "rotto", dict(GOOD, token=""), dict(GOOD, token=None),
                dict(GOOD, channel_id=None), dict(GOOD, channel_id="x"), dict(GOOD, channel_id=0)):
        assert bridge.config(bad) is None, bad


def test_il_marchio_della_configurazione_cambia_col_token_e_non_lo_contiene():
    first = bridge.digest(bridge.config(GOOD))
    assert "dtok-1" not in first
    assert bridge.digest(bridge.config(dict(GOOD, token="dtok-2"))) != first
    assert bridge.digest(bridge.config(dict(GOOD, channel_id=10))) != first
    assert bridge.digest(bridge.config(dict(GOOD, guild_name="Altro"))) == first
    assert bridge.digest(None) == ""


def test_testo_e_nome_si_ripuliscono_e_si_accorciano():
    assert bridge.clean("  ciao  ", 10) == "ciao"
    assert bridge.clean("a\r\n\n\n\nb", 10) == "a\n\nb"
    assert bridge.clean("x" * 20, 5) == "xxxxx"
    assert bridge.person(None) == "?" and bridge.person("   ") == "?"
    assert bridge.person("N" * 50) == "N" * bridge.NAME_MAX


def test_il_tetto_verso_telegram_e_quello_delle_card_non_un_numero_nuovo():
    assert not hasattr(bridge, "TELEGRAM_MAX")
    assert bridge.MAX_LEN == render.MAX_LEN
    assert len(bridge.to_telegram("Mario", "x" * (render.MAX_LEN + 500))) <= render.MAX_LEN + 40


def test_verso_discord_si_disinnesca_il_markdown_del_nome():
    assert bridge.to_discord("Ma**rio", "ciao") == "**Ma\\*\\*rio**: ciao"
    assert bridge.to_discord("Mario", "", "[foto]") == "**Mario**: [foto]"
    assert bridge.to_discord("Mario", "") is None
    assert len(bridge.to_discord("Mario", "x" * 5000)) == bridge.DISCORD_LIMIT
    lungo = bridge.to_discord("Mario", "x" * 5000, "[foto]")
    assert len(lungo) == bridge.DISCORD_LIMIT and lungo.endswith("[foto]")


def test_verso_telegram_si_scappa_l_html():
    assert bridge.to_telegram("Ma<rio>", "<b>ciao</b>") == (
        "💬 <b>Ma&lt;rio&gt;</b>: &lt;b&gt;ciao&lt;/b&gt;")
    assert bridge.to_telegram("Mario", "", "[1 file]") == "💬 <b>Mario</b>: [1 file]"
    assert bridge.to_telegram("Mario", None) is None


def test_gli_allegati_diventano_etichette_tradotte():
    message = SimpleNamespace(photo=[1], video=None, animation=None, document=None,
                              audio=None, voice=None, sticker=None)
    assert bridge.kinds_of(message) == ["photo"]
    assert bridge.media_label(IT, ["photo", "video"]) == "[foto] [video]"
    assert bridge.media_label(IT, []) is None
    assert bridge.attachments_label(IT, [1, 2]) == "[2 file]"
    assert bridge.attachments_label(IT, []) is None


def test_le_etichette_del_catalogo_non_portano_le_parentesi():
    for kind in bridge.MEDIA_KINDS:
        assert not IT.t(f"bridge.media.{kind}").startswith("[")
    assert not IT.t("bridge.media.file", n=1).startswith("[")


def test_da_telegram_si_scartano_bot_comandi_e_vuoti():
    def message(**kw):
        base = dict(from_user=SimpleNamespace(id=7, is_bot=False), text="ciao", caption=None,
                    photo=None, video=None, animation=None, document=None, audio=None,
                    voice=None, sticker=None)
        base.update(kw)
        return SimpleNamespace(**base)

    assert bridge.from_telegram_ok(message(), 99) is True
    assert bridge.from_telegram_ok(message(from_user=SimpleNamespace(id=99, is_bot=True)), 99) is False
    assert bridge.from_telegram_ok(message(from_user=SimpleNamespace(id=5, is_bot=True)), 99) is False
    assert bridge.from_telegram_ok(message(text=None), 99) is False
    assert bridge.from_telegram_ok(message(text=None, photo=[1]), 99) is True
    assert bridge.from_telegram_ok(message(from_user=None), 99) is False


def test_da_discord_si_scartano_bot_webhook_e_altri_canali():
    me = SimpleNamespace(id=1)

    def message(**kw):
        base = dict(author=SimpleNamespace(id=2, bot=False, display_name="Toad"), webhook_id=None,
                    channel=SimpleNamespace(id=9), content="ciao", attachments=[])
        base.update(kw)
        return SimpleNamespace(**base)

    assert bridge.from_discord_ok(message(), me, 9) is True
    assert bridge.from_discord_ok(message(author=SimpleNamespace(id=1, bot=True)), me, 9) is False
    assert bridge.from_discord_ok(message(author=SimpleNamespace(id=3, bot=True)), me, 9) is False
    assert bridge.from_discord_ok(message(webhook_id=7), me, 9) is False
    assert bridge.from_discord_ok(message(channel=SimpleNamespace(id=8)), me, 9) is False
    assert bridge.from_discord_ok(message(content="", attachments=[]), me, 9) is False
    assert bridge.from_discord_ok(message(content="", attachments=[1]), me, 9) is True


def test_il_topic_limita_il_ponte():
    assert bridge.in_scope(None, None) is True
    assert bridge.in_scope(44, None) is True
    assert bridge.in_scope(44, 44) is True
    assert bridge.in_scope(None, 44) is False
    assert bridge.in_scope(45, 44) is False


def test_le_etichette_esistono_in_inglese():
    for kind in bridge.MEDIA_KINDS:
        assert f"bridge.media.{kind}" in EN, kind
    assert "bridge.media.file" in EN
