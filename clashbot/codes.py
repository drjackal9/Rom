async def alias_for(store, code):
    if not code:
        return None
    for clan in await store.active_clans():
        if store.recruit_code(clan.alias) == code:
            return clan.alias
    return None


async def clan_for(store, code):
    alias = await alias_for(store, code)
    return await store.clan_by_alias(alias) if alias else None
