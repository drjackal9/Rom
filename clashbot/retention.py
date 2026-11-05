WAR_HISTORY_KEEP = 100
BASE_KEEP = WAR_HISTORY_KEEP
MEMBER_HISTORY_KEEP = 100
LEADER_LOG_KEEP = 100
CWL_SEASONS_KEEP = 100
INACTIVE_CLAN_DAYS = 90
APPLICATION_DECIDED_DAYS = 30

_INACTIVE_CLANS = (
    f"active = false and coalesce(last_seen, created_at) < now() - interval '{INACTIVE_CLAN_DAYS} days'"
)
_EXPIRED_KV = "expires_at is not null and expires_at <= now()"
_OLD_NETWORK = f"updated_at < now() - interval '{INACTIVE_CLAN_DAYS} days'"
_WARS_OVER_CAP = f"""select id from (
      select id, row_number() over (partition by clan_alias order by ended_at desc, id desc) as rn
      from war_history
    ) ranked where rn > {WAR_HISTORY_KEEP}"""
_BASES_OVER_CAP = f"""select alias from (
      select alias, row_number() over (partition by clan_alias order by created_at desc, alias desc) as rn
      from base_layouts
    ) ranked where rn > {BASE_KEEP}"""
_MEMBERS_OVER_CAP = f"""select id from (
      select id, row_number() over (partition by clan_alias order by left_at desc, id desc) as rn
      from member_history
    ) ranked where rn > {MEMBER_HISTORY_KEEP}"""
_LOG_OVER_CAP = f"""select id from (
      select id, row_number() over (partition by clan_alias order by at desc, id desc) as rn
      from leader_log
    ) ranked where rn > {LEADER_LOG_KEEP}"""
_CWL_OVER_CAP = f"""select id from (
      select id, row_number() over (partition by clan_alias order by ended_at desc, id desc) as rn
      from cwl_seasons
    ) ranked where rn > {CWL_SEASONS_KEEP}"""

COUNT_SQL = {
    "guerre_oltre_tetto": f"select count(*) from ({_WARS_OVER_CAP}) over_cap",
    "basi_oltre_tetto": f"select count(*) from ({_BASES_OVER_CAP}) over_cap",
    "ex_membri_oltre_tetto": f"select count(*) from ({_MEMBERS_OVER_CAP}) over_cap",
    "registro_oltre_tetto": f"select count(*) from ({_LOG_OVER_CAP}) over_cap",
    "cwl_oltre_tetto": f"select count(*) from ({_CWL_OVER_CAP}) over_cap",
    "clan_inattivi": f"select count(*) from clans where {_INACTIVE_CLANS}",
    "kv_scaduti": f"select count(*) from kv where {_EXPIRED_KV}",
    "rete_vecchia": f"select count(*) from network_clans where {_OLD_NETWORK}",
}

DELETE_SQL = {
    "guerre_oltre_tetto": f"delete from war_history where id in ({_WARS_OVER_CAP})",
    "basi_oltre_tetto": f"delete from base_layouts where alias in ({_BASES_OVER_CAP})",
    "ex_membri_oltre_tetto": f"delete from member_history where id in ({_MEMBERS_OVER_CAP})",
    "registro_oltre_tetto": f"delete from leader_log where id in ({_LOG_OVER_CAP})",
    "cwl_oltre_tetto": f"delete from cwl_seasons where id in ({_CWL_OVER_CAP})",
    "clan_inattivi": f"delete from clans where {_INACTIVE_CLANS}",
    "kv_scaduti": f"delete from kv where {_EXPIRED_KV}",
    "rete_vecchia": f"delete from network_clans where {_OLD_NETWORK}",
}

PRUNE_CLAN_WARS_SQL = """delete from war_history where clan_alias = $1 and id in (
      select id from war_history where clan_alias = $1
      order by ended_at desc, id desc offset $2
    ) returning id"""

PRUNE_CLAN_BASES_SQL = """delete from base_layouts where clan_alias = $1 and alias in (
      select alias from base_layouts where clan_alias = $1
      order by created_at desc, alias desc offset $2
    )"""

PRUNE_CLAN_MEMBERS_SQL = """delete from member_history where clan_alias = $1 and id in (
      select id from member_history where clan_alias = $1
      order by left_at desc, id desc offset $2
    ) returning id"""

PRUNE_CLAN_LOG_SQL = """delete from leader_log where clan_alias = $1 and id in (
      select id from leader_log where clan_alias = $1
      order by at desc, id desc offset $2
    )"""

PRUNE_CWL_SEASONS_SQL = """delete from cwl_seasons where clan_alias = $1 and id in (
      select id from cwl_seasons where clan_alias = $1
      order by ended_at desc, id desc offset $2
    ) returning id"""

STAT_HISTORY_KEEP = 100

_STATS_OVER_CAP = f"""select id from (
      select id, row_number() over (partition by clan_alias, kind order by ended_at desc, id desc) as rn
      from stat_history
    ) ranked where rn > {STAT_HISTORY_KEEP}"""

COUNT_SQL["statistiche_oltre_tetto"] = f"select count(*) from ({_STATS_OVER_CAP}) over_cap"
DELETE_SQL["statistiche_oltre_tetto"] = f"delete from stat_history where id in ({_STATS_OVER_CAP})"

PRUNE_CLAN_STATS_SQL = """delete from stat_history where clan_alias = $1 and kind = $2 and id in (
      select id from stat_history where clan_alias = $1 and kind = $2
      order by ended_at desc, id desc offset $3
    ) returning id"""

_TOURNAMENTS_OVER_CAP = f"""select alias from (
      select alias, row_number() over (
        partition by coalesce(family_alias, clan_alias, owner_index)
        order by updated_at desc, alias desc) as rn
      from tournaments where status = 'done'
    ) ranked where rn > {WAR_HISTORY_KEEP}"""

COUNT_SQL["tornei_oltre_tetto"] = f"select count(*) from ({_TOURNAMENTS_OVER_CAP}) over_cap"
DELETE_SQL["tornei_oltre_tetto"] = f"delete from tournaments where alias in ({_TOURNAMENTS_OVER_CAP})"

_STUCK_INTENTS = "created_at < now() - interval '1 hour'"

COUNT_SQL["intenti_appesi"] = f"select count(*) from web_intents where {_STUCK_INTENTS}"
DELETE_SQL["intenti_appesi"] = f"delete from web_intents where {_STUCK_INTENTS}"


def deleted_rows(status):
    return int(status.split()[-1])


def summary(counts):
    return " ".join(f"{name}={value}" for name, value in counts.items())
