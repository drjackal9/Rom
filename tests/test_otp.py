import asyncio
import base64

import pytest

from clashbot import __main__ as cli
from clashbot import i18n, otp, platform
from clashbot.selfmetrics import PLATFORM_INTERVAL

IT = i18n.locale("it")
RFC = base64.b32encode(b"12345678901234567890").decode()
VECTORS = ((59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
           (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130"))
OWNER = 99
DELEGATE = 4242
NAME = "cyfren1"
NOW = 1789000000.0


class FakeStore:
    def __init__(self, secrets=None, kv=None):
        self.secrets = dict(secrets or {})
        self.kv = dict(kv or {})
        self.ttls = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def set_secret(self, kind, value):
        self.secrets[kind] = value
        return f"sec-{len(self.secrets)}"

    async def delete_secret(self, kind):
        return self.secrets.pop(kind, None) is not None

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj
        self.ttls[key] = ttl

    async def kv_del(self, key):
        self.kv.pop(key, None)


def user(uid, username=NAME):
    return type("U", (), {"id": uid, "username": username})()


def test_i_vettori_della_rfc_6238_danno_il_codice_a_sei_cifre():
    for at, expected in VECTORS:
        assert otp.code(RFC, at) == expected


def test_il_codice_vale_anche_nel_passo_successivo_e_non_oltre():
    at = VECTORS[0][0]
    assert otp.verify(RFC, otp.code(RFC, at), at) == otp.step_of(at)
    assert otp.verify(RFC, otp.code(RFC, at), at + otp.STEP) == otp.step_of(at)
    assert otp.verify(RFC, otp.code(RFC, at), at + 2 * otp.STEP) is None


def test_il_codice_gia_usato_non_passa_una_seconda_volta():
    at = VECTORS[3][0]
    step = otp.verify(RFC, otp.code(RFC, at), at)
    assert otp.verify(RFC, otp.code(RFC, at), at, last=step) is None
    assert otp.verify(RFC, otp.code(RFC, at + otp.STEP), at + otp.STEP, last=step) == step + 1


def test_un_codice_malfatto_non_passa():
    at = VECTORS[0][0]
    for storto in ("", None, "28708", "2870821", "abcdef", "28708a", "000000"):
        assert otp.verify(RFC, storto, at) is None


def test_il_codice_passa_anche_scritto_con_gli_spazi():
    at = VECTORS[0][0]
    assert otp.verify(RFC, " 287 082 ", at) == otp.step_of(at)


def test_la_chiave_nuova_si_legge_in_base32_e_l_indirizzo_porta_il_nome():
    key = otp.secret()
    assert key != otp.secret()
    assert len(base64.b32decode(key)) == otp.LENGTH
    indirizzo = otp.uri(key, NAME)
    assert indirizzo.startswith(f"otpauth://totp/{otp.ISSUER}:{NAME}?")
    assert f"secret={key}" in indirizzo and f"issuer={otp.ISSUER}" in indirizzo


def test_senza_codice_attivo_scrive_solo_il_gestore():
    store = FakeStore()
    assert asyncio.run(otp.cleared(store, OWNER, True, NOW)) is True
    assert asyncio.run(otp.cleared(store, DELEGATE, False, NOW)) is False


def test_la_finestra_si_apre_col_codice_e_dura_dieci_minuti():
    store = FakeStore(secrets={otp.seed_of(OWNER): RFC})
    assert asyncio.run(otp.cleared(store, OWNER, True, NOW)) is False
    asyncio.run(otp.mark(store, OWNER, otp.step_of(NOW), NOW))
    assert store.ttls[otp.window_of(OWNER)] == PLATFORM_INTERVAL
    assert asyncio.run(otp.cleared(store, OWNER, True, NOW + PLATFORM_INTERVAL - 1)) is True
    assert asyncio.run(otp.cleared(store, OWNER, True, NOW + PLATFORM_INTERVAL)) is False


def test_ognuno_ha_la_sua_finestra():
    store = FakeStore(secrets={otp.seed_of(OWNER): RFC, otp.seed_of(DELEGATE): otp.secret()})
    asyncio.run(otp.mark(store, OWNER, otp.step_of(NOW), NOW))
    assert asyncio.run(otp.cleared(store, OWNER, True, NOW)) is True
    assert asyncio.run(otp.cleared(store, DELEGATE, False, NOW)) is False


def test_la_prova_accende_il_codice_e_apre_la_finestra():
    store = FakeStore()
    text, _, ask = asyncio.run(otp.act(store, IT, "otpnew", user(OWNER), NOW))
    assert ask is True
    chiave = store.kv[otp.pending_of(OWNER)]["key"]
    assert store.ttls[otp.pending_of(OWNER)] == PLATFORM_INTERVAL
    assert chiave in text and otp.uri(chiave, NAME).split("?")[0] in text
    sbagliato, _, ask = asyncio.run(otp.check(store, IT, OWNER, "000000", NOW))
    assert ask is True and IT.t("otp.bad") in sbagliato
    assert otp.seed_of(OWNER) not in store.secrets
    giusto, _, ask = asyncio.run(otp.check(store, IT, OWNER, otp.code(chiave, NOW), NOW))
    assert ask is False and IT.t("otp.ready", n=PLATFORM_INTERVAL // 60) in giusto
    assert store.secrets[otp.seed_of(OWNER)] == chiave
    assert otp.pending_of(OWNER) not in store.kv
    assert asyncio.run(otp.cleared(store, OWNER, True, NOW)) is True
    assert chiave not in str(store.kv[otp.window_of(OWNER)])


def test_il_codice_riusato_non_riapre_la_finestra():
    store = FakeStore(secrets={otp.seed_of(OWNER): RFC})
    codice = otp.code(RFC, NOW)
    assert asyncio.run(otp.check(store, IT, OWNER, codice, NOW))[2] is False
    text, _, ask = asyncio.run(otp.check(store, IT, OWNER, codice, NOW + 1))
    assert ask is True and IT.t("otp.bad") in text
    assert store.kv[otp.window_of(OWNER)]["at"] == NOW


def test_la_prova_non_riparte_quando_il_codice_e_gia_attivo():
    store = FakeStore(secrets={otp.seed_of(OWNER): RFC})
    text, _, ask = asyncio.run(otp.act(store, IT, "otpnew", user(OWNER), NOW))
    assert ask is False and IT.t("otp.on", n=PLATFORM_INTERVAL // 60) in text
    assert otp.pending_of(OWNER) not in store.kv
    assert store.secrets[otp.seed_of(OWNER)] == RFC


def test_il_reset_dal_server_toglie_chiave_finestra_e_prova(capsys):
    store = FakeStore(secrets={otp.seed_of(DELEGATE): RFC},
                      kv={platform.KEY: [{"username": NAME, "user_id": DELEGATE, "since": NOW}],
                          otp.window_of(DELEGATE): {"at": NOW, "step": 1},
                          otp.pending_of(DELEGATE): {"key": RFC, "at": NOW}})
    asyncio.run(cli.otp_reset(store, f"@{NAME}"))
    assert otp.seed_of(DELEGATE) not in store.secrets
    assert otp.window_of(DELEGATE) not in store.kv
    assert otp.pending_of(DELEGATE) not in store.kv
    assert RFC not in capsys.readouterr().out
    assert asyncio.run(otp.active(store, DELEGATE)) is False
    text, keyboard, ask = asyncio.run(otp.page(store, IT, DELEGATE))
    assert ask is False and IT.t("otp.off") in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        "panel:otpnew", "panel:refresh"]


def test_il_reset_accetta_anche_l_id_e_dice_quando_non_c_era(capsys):
    store = FakeStore(secrets={otp.seed_of(OWNER): RFC})
    asyncio.run(cli.otp_reset(store, str(OWNER)))
    assert otp.seed_of(OWNER) not in store.secrets
    asyncio.run(cli.otp_reset(store, str(OWNER)))
    assert capsys.readouterr().out.count("nessun codice") == 1


def test_il_reset_di_chi_non_si_conosce_si_ferma():
    store = FakeStore(kv={platform.KEY: []})
    with pytest.raises(SystemExit):
        asyncio.run(cli.otp_reset(store, "sconosciuto"))


def test_il_comando_dei_segreti_conosce_il_reset():
    assert cli.OTP_RESET not in cli.SECRET_KINDS
    with pytest.raises(SystemExit) as fermo:
        cli.main(["secret"])
    assert cli.OTP_RESET in str(fermo.value)
