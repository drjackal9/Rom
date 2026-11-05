import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg

from clashbot.crypto import Vault


async def main(key_dir, port):
    vault = Vault(key_dir)
    conn = await asyncpg.connect(host="127.0.0.1", port=int(port), database="clashbot", user="postgres")
    try:
        counts = {}
        for table in ("secrets", "bots", "clans", "links", "families", "war_history", "kv"):
            counts[table] = await conn.fetchval(f"select count(*) from {table}")
        secrets = await conn.fetch("select alias, kind, key_id, data from secrets")
        clans = await conn.fetch("select alias, key_id, identity from clans")
    finally:
        await conn.close()
    for table, n in counts.items():
        print(f"{table}: {n}")
    opened = 0
    for row in secrets:
        if row["key_id"] != vault.key_id:
            print(f"segreto {row['kind']}: chiave diversa ({row['key_id']})")
            continue
        vault.decrypt(row["data"], f"secret:{row['alias']}")
        opened += 1
        print(f"segreto {row['kind']}: apribile")
    named = 0
    for row in clans:
        if row["key_id"] != vault.key_id:
            continue
        doc = vault.decrypt_json(row["identity"], f"clan:{row['alias']}")
        named += 1
        print(f"clan {row['alias']}: {doc.get('name', '?')}")
    if secrets and not opened:
        print("nessun segreto apribile con questa chiave", file=sys.stderr)
        return 1
    if clans and not named:
        print("nessun clan apribile con questa chiave", file=sys.stderr)
        return 1
    print(f"aperti {opened} segreti e {named} clan con la chiave {vault.key_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
