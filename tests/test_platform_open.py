import asyncio
from types import SimpleNamespace

from clashbot import feed, i18n, ledger, manager_alerts, platform, site_days
from clashbot.crypto import Vault
from test_intents import ActStore
from test_web_publish import CLAN, NOW

CAPO = 7
COCAPO = 8
GESTORE = 4242
CONF = {"lang": "it"}
MEMBERS = {"#P1": {"name": "Mario", "role": "leader"},
           "#P2": {"name": "Luigi", "role": "coLeader"}}


def link(tag, uid, name):
    return SimpleNamespace(tag=tag, user_id=uid, name=name, dm=True, lang="it", verified=True)


def store_of(tmp_path):
    store = ActStore(Vault(tmp_path))
    store.links = [link("#P1", CAPO, "Mario"), link("#P2", COCAPO, "Luigi")]
    asyncio.run(store.set_state(CLAN.alias, "members", MEMBERS))
    return store


def apri(store, reason):
    return asyncio.run(platform.open_data(store, CLAN, CONF, GESTORE, reason, NOW))


def righe(store, uid):
    return asyncio.run(feed.rows(store, CLAN.alias, uid))


def test_i_motivi_dell_apertura_sono_a_scelta_fissa():
    assert platform.OPEN_REASONS and all(isinstance(one, str) for one in platform.OPEN_REASONS)
    assert platform.OPEN_LOG in ledger.ACTIONS


def test_la_piattaforma_che_apre_senza_motivo_non_apre_niente(tmp_path):
    store = store_of(tmp_path)
    for storto in ("", None, "perche_si", "SUPPORT"):
        assert apri(store, storto) is None
    assert store.logs == [] and righe(store, CAPO) == []


def test_l_apertura_col_motivo_scrive_chi_quando_e_perche_nel_registro(tmp_path):
    store = store_of(tmp_path)
    reason = platform.OPEN_REASONS[0]
    found = apri(store, reason)
    assert found["reason"] == reason and found["at"] == NOW.timestamp()
    alias, entry = store.logs[0]
    assert alias == CLAN.alias
    assert entry["action"] == platform.OPEN_LOG
    assert entry["by"] == GESTORE and entry["detail"] == reason


def test_l_apertura_avvisa_il_capo_in_casella(tmp_path):
    store = store_of(tmp_path)
    reason = platform.OPEN_REASONS[0]
    apri(store, reason)
    rows = righe(store, CAPO)
    assert len(rows) == 1 and rows[0]["kind"] == platform.OPENED
    atteso = i18n.locale("it").t("feed.platform.opened",
                                 reason=i18n.locale("it").t("platform.reason." + reason))
    assert rows[0]["text"] == atteso and not atteso.startswith("[")
    assert righe(store, COCAPO) == []


def test_l_avviso_non_porta_ne_uid_ne_tag(tmp_path):
    store = store_of(tmp_path)
    apri(store, platform.OPEN_REASONS[0])
    testo = righe(store, CAPO)[0]["text"]
    assert str(GESTORE) not in testo and "#P1" not in testo and "#P2" not in testo


def conti(store, mese):
    return asyncio.run(site_days.opens(store, [mese]))


def test_l_apertura_alza_il_conto_del_mese_che_la_pagina_sicurezza_legge(tmp_path):
    store = store_of(tmp_path)
    mese = NOW.strftime("%Y-%m")
    assert conti(store, mese) == {mese: 0}
    apri(store, platform.OPEN_REASONS[0])
    apri(store, platform.OPEN_REASONS[1])
    assert conti(store, mese) == {mese: 2}


def test_l_apertura_senza_motivo_non_alza_il_conto(tmp_path):
    store = store_of(tmp_path)
    mese = NOW.strftime("%Y-%m")
    apri(store, "perche_si")
    assert conti(store, mese) == {mese: 0}


def test_il_conto_delle_aperture_sta_in_un_posto_solo():
    assert site_days.OPENS_KEY is manager_alerts.OPENS_KEY
