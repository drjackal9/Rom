import asyncio
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import tournaments, tourney_results, views

START = 1000000000
GIORNO = 86400
ORA = 3600
ACCESO = "acceso"


class StoreCheConta:
    def __init__(self, clans, acceso):
        self.clans = {clan.alias: clan for clan in clans}
        self.acceso = acceso
        self.conti = {}

    def _segna(self, nome):
        self.conti[nome] = self.conti.get(nome, 0) + 1

    async def clan_by_alias(self, alias):
        self._segna("clan_by_alias")
        return self.clans.get(alias)

    async def wars_since(self, alias, since):
        self._segna("wars_since")
        return []

    async def get_state(self, alias, kind):
        self._segna(f"get_state:{kind}")
        if kind == views.KIND:
            return {views.FAMILY: True} if self.acceso else {}
        return {}

    async def family_clans(self, alias):
        self._segna("family_clans")
        return list(self.clans.values())


def girone(scope, quanti, metric):
    doc = tournaments.empty("clash", scope, metric, "table", START - GIORNO, START - ORA,
                            START + ORA)
    doc["alias"] = "trn-costo0"
    clans = [SimpleNamespace(alias=f"clan-{i}", chat_id=i, tag=f"#C{i}", name=f"C{i}",
                             bot_alias="bot-1", active=True) for i in range(quanti)]
    for clan in clans:
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    return tournaments.make_groups(doc, 1), clans


def conta(scope, quanti, metric, acceso):
    doc, clans = girone(scope, min(quanti, tournaments.MAX_ENTRIES), metric)
    store = StoreCheConta(clans, acceso)
    asyncio.run(tourney_results.refresh(store, doc, datetime.fromtimestamp(START, timezone.utc)))
    conti = dict(store.conti)
    conti["totale"] = sum(store.conti.values())
    return conti


def riassunto(scope, quanti, metric, acceso, conti):
    righe = [f"scope={scope} clan={quanti} metrica={metric} acceso={acceso}"]
    righe += [f"  {nome}: {conti[nome]}" for nome in sorted(conti) if nome != "totale"]
    righe.append(f"  totale: {conti['totale']}")
    return "\n".join(righe)


def principale(dati):
    scope = dati[0] if dati else "family"
    quanti = min(int(dati[1]) if len(dati) > 1 else tournaments.MAX_ENTRIES,
                 tournaments.MAX_ENTRIES)
    metric = dati[2] if len(dati) > 2 else "stars"
    acceso = (dati[3] if len(dati) > 3 else ACCESO) == ACCESO
    print(riassunto(scope, quanti, metric, acceso, conta(scope, quanti, metric, acceso)))
    return 0


if __name__ == "__main__":
    sys.exit(principale(sys.argv[1:]))
