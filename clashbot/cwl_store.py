from .retention import CWL_SEASONS_KEEP, PRUNE_CWL_SEASONS_SQL


def index_for(vault, alias, season):
    return vault.blind("cwl", f"{alias}:{season}")


async def save_season(store, alias, season, ended_at, record):
    index = index_for(store.vault, alias, season)
    data = store.vault.encrypt_json(record, f"cwl:{alias}:{index}")
    async with store.pool.acquire() as conn, conn.transaction():
        row_id = await conn.fetchval(
            """insert into cwl_seasons(clan_alias, season_index, ended_at, key_id, data)
               values($1,$2,$3,$4,$5)
               on conflict (clan_alias, season_index) do update
               set ended_at=excluded.ended_at, key_id=excluded.key_id, data=excluded.data
               returning id""",
            alias, index, ended_at, store.vault.key_id, data,
        )
        pruned = await conn.fetch(PRUNE_CWL_SEASONS_SQL, alias, CWL_SEASONS_KEEP)
    return all(row["id"] != row_id for row in pruned)


async def seasons(store, alias, limit=12):
    rows = await store.pool.fetch(
        """select season_index, data from cwl_seasons where clan_alias=$1
           order by ended_at desc limit $2""",
        alias, limit,
    )
    return [store.vault.decrypt_json(r["data"], f"cwl:{alias}:{r['season_index']}") for r in rows]
