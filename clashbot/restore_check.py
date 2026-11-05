import re

from . import db, manager_alerts

PACK = "platform"
EVENTS = ("platform.restore",)
PRODUCTION = db.DATABASE
CREATED = re.compile(r"create table if not exists (\w+)")


def schema_tables(*sources):
    names = []
    for text in sources:
        for name in CREATED.findall(text):
            if name not in names:
                names.append(name)
    return tuple(names)


TABLES = schema_tables(db.SCHEMA)
PRESENT_SQL = "select table_name from information_schema.tables where table_schema='public'"
COUNT_SQL = "select count(*) from {table}"
FRESH_SQL = "select max(last_seen) from clans"

CHECKS = (
    ("secrets", "data", "select alias, data from secrets order by alias", "secret:{alias}", False),
    ("bots", "identity", "select alias, identity from bots order by alias", "bot:{alias}", True),
    ("clans", "identity", "select alias, identity from clans order by alias", "clan:{alias}", True),
    ("links", "identity", "select alias, identity from links order by alias", "link:{alias}", True),
    ("families", "identity", "select alias, identity from families order by alias", "family:{alias}", True),
    ("clan_state", "data", "select clan_alias, kind, data from clan_state order by clan_alias, kind",
     "state:{clan_alias}:{kind}", True),
    ("war_history", "data", "select clan_alias, war_index, data from war_history order by id",
     "war:{clan_alias}:{war_index}", True),
    ("stat_history", "data", "select clan_alias, stat_index, data from stat_history order by id",
     "stat:{clan_alias}:{stat_index}", True),
    ("member_history", "data", "select clan_alias, member_index, data from member_history order by id",
     "member:{clan_alias}:{member_index}", True),
    ("leader_log", "data", "select clan_alias, data from leader_log order by id", "log:{clan_alias}", True),
    ("base_layouts", "data", "select alias, data from base_layouts order by alias", "base:{alias}", True),
    ("network_clans", "data", "select clan_alias, data from network_clans order by clan_alias",
     "network:{clan_alias}", True),
    ("network_clans", "recruit_data",
     "select clan_alias, recruit_data from network_clans where recruit_data is not null order by clan_alias",
     "recruit:{clan_alias}", True),
    ("tournaments", "data", "select alias, data from tournaments order by alias", "tour:{alias}", True),
    ("cwl_seasons", "data", "select clan_alias, season_index, data from cwl_seasons order by id",
     "cwl:{clan_alias}:{season_index}", True),
    ("kv", "data", "select k, data from kv order by k", "kv:{k}", True),
    ("web_notes", "data", "select name, data from web_notes order by name", "web:{name}", True),
    ("web_pages", "data", "select clan_alias, kind, data from web_pages order by clan_alias, kind",
     "page:{clan_alias}:{kind}", True),
    ("web_intents", "data", "select id, data from web_intents order by id", "intent:{id}", True),
    ("incidents", "data", "select id, data from incidents order by id", db.INCIDENT_AAD, True),
)

ORPHANS_SQL = {
    "clan_senza_bot": ("select count(*) from clans c left join bots b on b.alias=c.bot_alias"
                       " where c.bot_alias is not null and b.alias is null"),
    "famiglia_senza_clan": ("select count(*) from family_clans fc left join families f on f.alias=fc.family_alias"
                            " where f.alias is null"),
    "stato_senza_clan": ("select count(*) from clan_state s left join clans c on c.alias=s.clan_alias"
                         " where c.alias is null"),
}


def rows(report):
    return sum(report["tables"].values())


def unreadable(report):
    return sum(report["unreadable"].values())


def orphans(report):
    return sum(report["orphans"].values())


def verdict(report):
    if report["missing"] or unreadable(report) or orphans(report):
        return False
    return report["tables"].get("secrets", 0) > 0 and report["tables"].get("bots", 0) > 0


def summary(report):
    fresh = report["fresh"]
    return " ".join([
        f"tabelle={len(report['tables'])}/{len(TABLES)}",
        f"righe={rows(report)}",
        f"decifrate={report['checked'] - unreadable(report)}",
        f"illeggibili={unreadable(report)}",
        f"orfani={orphans(report)}",
        f"ultimo_giro={fresh:%Y-%m-%d %H:%M}" if fresh else "ultimo_giro=mai",
        "esito=ok" if report["ok"] else "esito=FALLITA",
    ])


def signature(report):
    if report["ok"]:
        return "ok"
    guasti = sorted(report["missing"]) + sorted(report["unreadable"])
    guasti += sorted(name for name, value in report["orphans"].items() if value)
    return "ko:" + ",".join(guasti or ["vuoto"])


def entry(report):
    return {"ok": report["ok"], "righe": rows(report), "decifrate": report["checked"] - unreadable(report),
            "illeggibili": unreadable(report), "orfani": orphans(report)}


async def inspect(store):
    pool = store.pool
    present = {row["table_name"] for row in await pool.fetch(PRESENT_SQL)}
    report = {"tables": {}, "missing": [name for name in TABLES if name not in present],
              "unreadable": {}, "checked": 0, "orphans": {}, "fresh": None, "ok": False}
    for name in TABLES:
        if name in present:
            report["tables"][name] = int(await pool.fetchval(COUNT_SQL.format(table=name)) or 0)
    for name, column, sql, label, as_json in CHECKS:
        if name not in present:
            continue
        bad = 0
        for row in await pool.fetch(sql):
            aad = label.format(**dict(row))
            try:
                if as_json:
                    store.vault.decrypt_json(row[column], aad)
                else:
                    store.vault.decrypt(row[column], aad)
            except Exception:
                bad += 1
            report["checked"] += 1
        if bad:
            report["unreadable"][name] = report["unreadable"].get(name, 0) + bad
    if not report["missing"]:
        for name, sql in ORPHANS_SQL.items():
            report["orphans"][name] = int(await pool.fetchval(sql) or 0)
        report["fresh"] = await pool.fetchval(FRESH_SQL)
    report["ok"] = verdict(report)
    return report


async def record(store, report, at):
    return await manager_alerts.record(store, "restore", signature(report), entry(report), at)
