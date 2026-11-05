import asyncio
import getpass
import logging
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .coc import CocApi, parse_keys, public_ip, telegram_me
from .crypto import Vault
from .db import DATABASE, Store
from .i18n import LANGUAGES
from .retention import summary
from .settings import valid_tz
from .tunnel import remove as remove_tunnel_file, valid as valid_tunnel_token, write as write_tunnel_file
from .util import normalize_tag, valid_https, valid_telegram

HEARTBEAT = Path("/tmp/clashbot.heartbeat")
WEB_HEARTBEAT = Path("/tmp/clashbot-web.heartbeat")
SECRET_KINDS = ("telegram_token", "console_token", "coc_api_key", "owner_id", "owner_lang", "owner_tz",
                "support_url", "creator_code", "site_base", "twitch_url", "source_url",
                "channel_url", "twitch_client_id", "twitch_client_secret", "youtube_key",
                "tunnel_token", "cloudflare_analytics", "cloudflare_zone")
TOKEN_KINDS = ("telegram_token", "console_token")
PLAIN_KINDS = ("owner_id", "owner_lang", "owner_tz", "support_url", "creator_code", "site_base",
               "twitch_url", "source_url", "channel_url", "twitch_client_id", "cloudflare_zone")
CLEARABLE_KINDS = ("support_url", "creator_code", "site_base", "twitch_url", "channel_url",
                   "twitch_client_id", "twitch_client_secret", "tunnel_token",
                   "cloudflare_analytics", "cloudflare_zone")
OTP_RESET = "otp_reset"
CLEAR_VALUE = "-"
TWITCH_KEY_LEN = 30
TELEGRAM_API = "https://api.telegram.org"
NOTIFY_TIMEOUT = 15
NOTIFY_LIMIT = 4096

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("clashbot")


def read_value(prompt, secret=True):
    if sys.stdin.isatty():
        return (getpass.getpass(prompt) if secret else input(prompt)).strip()
    print(prompt, end="", flush=True)
    return sys.stdin.readline().strip()


def read_keys(prompt):
    if not sys.stdin.isatty():
        print(prompt, end="", flush=True)
        return sys.stdin.read()
    lines = []
    while line := getpass.getpass(prompt if not lines else "altra chiave (invio vuoto per finire): ").strip():
        lines.append(line)
    return "\n".join(lines)


async def check_coc_keys(raw):
    keys = parse_keys(raw)
    if not keys:
        raise SystemExit("valore vuoto")
    failed = []
    for position, key in enumerate(keys, 1):
        api = CocApi(key)
        try:
            _, error = await api.check()
        finally:
            await api.close()
        if error:
            failed.append((position, error))
    if failed:
        detail = ", ".join(f"n.{position} ({error})" for position, error in failed)
        hint = ""
        if any(error == "invalid_ip" for _, error in failed):
            hint = f"; IP attuale {await public_ip()}"
        raise SystemExit(f"chiavi Clash non valide su {len(keys)}: {detail}{hint}. Nessuna chiave salvata")
    print(f"  chiavi Clash ok: {len(keys)}")
    return ",".join(keys)


def valid_twitch_url(value):
    if not valid_https(value):
        return False
    host = urlsplit(value).hostname.lower()
    return host == "twitch.tv" or host.endswith(".twitch.tv")


def valid_channel_url(value):
    return valid_telegram(value)


def valid_creator_code(value):
    return bool(value) and value.isascii() and value.isalnum() and 3 <= len(value) <= 20


def valid_twitch_key(value):
    return bool(value) and value.isascii() and value.isalnum() and len(value) == TWITCH_KEY_LEN


async def clear_secret(store, kind):
    if await store.delete_secret(kind):
        print(f"  {kind} rimosso")
    else:
        print(f"  {kind} non impostato, nulla da rimuovere")
    if kind == "tunnel_token" and remove_tunnel_file():
        print("  file del tunnel tolto")


async def store_secret(store, kind, value):
    if not value:
        raise SystemExit("valore vuoto")
    if value == CLEAR_VALUE:
        if kind not in CLEARABLE_KINDS:
            raise SystemExit(f"{kind} non si rimuove: {CLEAR_VALUE} vale solo per {', '.join(CLEARABLE_KINDS)}")
        await clear_secret(store, kind)
        return
    if kind in TOKEN_KINDS:
        me = await telegram_me(value)
        if not me:
            raise SystemExit("token Telegram non valido")
        print(f"  bot: @{me.get('username')}")
    elif kind == "coc_api_key":
        value = await check_coc_keys(value)
    elif kind == "owner_id":
        int(value)
    elif kind == "owner_lang":
        if value not in LANGUAGES:
            raise SystemExit(f"lingua sconosciuta, scegli tra: {', '.join(LANGUAGES)}")
    elif kind == "owner_tz":
        if not valid_tz(value):
            raise SystemExit("fuso orario sconosciuto: usa un nome come Europe/Rome")
    elif kind in ("support_url", "site_base", "source_url"):
        if not valid_https(value):
            raise SystemExit(f"{kind} non valido: serve un indirizzo https:// con un host")
    elif kind == "channel_url":
        if not valid_channel_url(value):
            raise SystemExit("channel_url non valido: serve un indirizzo https://t.me/...")
    elif kind == "creator_code":
        if not valid_creator_code(value):
            raise SystemExit("creator_code non valido: da 3 a 20 lettere o cifre, senza spazi né simboli")
    elif kind in ("twitch_client_id", "twitch_client_secret"):
        if not valid_twitch_key(value):
            raise SystemExit(f"{kind} non valido: {TWITCH_KEY_LEN} lettere o cifre, senza spazi né simboli")
    elif kind == "twitch_url":
        if not valid_twitch_url(value):
            raise SystemExit("twitch_url non valido: serve un indirizzo https:// su twitch.tv")
    elif kind == "tunnel_token":
        if not valid_tunnel_token(value):
            raise SystemExit("tunnel_token non valido: una riga sola, senza spazi")
    alias = await store.set_secret(kind, value)
    print(f"  salvato cifrato come {alias}")
    if kind == "tunnel_token":
        write_tunnel_file(value)
        print("  file del tunnel scritto, il container clashbot-tunnel lo legge al prossimo avvio")


def parse_migrate_args(argv):
    uso = "uso: migrate-multibot [--yes] [--database NOME]"
    yes = False
    database = None
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--yes":
            yes = True
        elif arg == "--database":
            database = rest.pop(0) if rest else ""
        elif arg.startswith("--database="):
            database = arg.split("=", 1)[1]
        else:
            raise SystemExit(uso)
        if database is not None and not database:
            raise SystemExit(uso)
    return yes, database


def parse_retention_args(argv):
    if list(argv) == ["--dry-run"]:
        return True
    if not argv:
        return False
    raise SystemExit("uso: retention [--dry-run]")


async def run_retention_command(store, dry_run):
    if dry_run:
        print(f"prova, nulla cancellato: {summary(await store.retention_counts())}")
    else:
        print(f"righe cancellate: {summary(await store.run_retention())}")


def parse_restore_args(argv):
    uso = "uso: restore-check --database NOME"
    database = None
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--database":
            database = rest.pop(0) if rest else ""
        elif arg.startswith("--database="):
            database = arg.split("=", 1)[1]
        else:
            raise SystemExit(uso)
        if not database:
            raise SystemExit(uso)
    if not database:
        raise SystemExit(uso)
    if database == DATABASE:
        raise SystemExit("la prova di ripristino non tocca il database di produzione")
    return database


async def run_restore_check(database):
    from . import restore_check

    try:
        vault = Vault(create=False)
    except OSError:
        raise SystemExit("chiave master non disponibile: prova di ripristino non eseguita") from None
    prova = Store(vault, database=database)
    await prova.open(schema=False)
    try:
        report = await restore_check.inspect(prova)
    finally:
        await prova.close()
    print(restore_check.summary(report))
    produzione = Store(vault)
    await produzione.open()
    try:
        await restore_check.record(produzione, report, time.time())
    finally:
        await produzione.close()
    if not report["ok"]:
        raise SystemExit(1)


def parse_notify_args(argv):
    text = sys.stdin.read() if list(argv) == ["-"] else " ".join(argv)
    text = text.strip()
    if not text:
        raise SystemExit("uso: notify TESTO | notify - (testo da stdin)")
    return text[:NOTIFY_LIMIT]


def redact(text, token):
    return str(text).replace(token, "***")


async def post_notify(token, owner, text, transport):
    async with httpx.AsyncClient(timeout=NOTIFY_TIMEOUT, transport=transport) as client:
        return await client.post(f"{TELEGRAM_API}/bot{token}/sendMessage", json={"chat_id": owner, "text": text})


async def notify(store, text, transport=None):
    token = await store.get_secret("console_token")
    if not token:
        raise SystemExit("manca console_token: docker compose run --rm bot secret console_token")
    owner = await store.get_secret("owner_id")
    if not owner:
        raise SystemExit("manca owner_id: docker compose run --rm bot secret owner_id")
    try:
        response = await asyncio.wait_for(post_notify(token, owner, text, transport), NOTIFY_TIMEOUT)
    except Exception as error:
        raise SystemExit(f"avviso non inviato: {type(error).__name__}") from None
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code == 200 and isinstance(body, dict) and body.get("ok") is True:
        print("avviso inviato al proprietario")
        return
    detail = body.get("description") if isinstance(body, dict) else None
    reason = f"Telegram {response.status_code}" + (f": {redact(detail, token)}" if detail else "")
    raise SystemExit(f"avviso non inviato: {reason}")


async def with_store(fn, database=None):
    vault = Vault()
    store = Store(vault, database=database) if database else Store(vault)
    await store.open()
    try:
        return await fn(store)
    finally:
        await store.close()


async def setup(store):
    print("I valori vengono cifrati e salvati nel database. Nessun file di configurazione.")
    await store_secret(store, "telegram_token", read_value("Token Telegram (da BotFather): "))
    await store_secret(store, "coc_api_key", read_value("Chiavi API Clash of Clans (più chiavi separate da virgola): "))
    sorgente = read_value("Indirizzo del codice sorgente di questa copia, se già pubblicato (invio per saltare): ", secret=False)
    if sorgente:
        await store_secret(store, "source_url", sorgente)
    owner = read_value("ID Telegram del proprietario per gli avvisi (invio per saltare): ", secret=False)
    if owner:
        await store_secret(store, "owner_id", owner)
    print("Fatto. Avvia con: docker compose up -d")


async def otp_reset(store, who):
    from . import otp

    uid = await otp.find(store, who)
    if not uid:
        raise SystemExit("persona sconosciuta: passa l'id Telegram o lo username di un delegato")
    if await otp.forget(store, uid):
        print(f"  codice dell'Authenticator tolto a {uid}: dal pannello può attivarne uno nuovo")
    else:
        print(f"  nessun codice dell'Authenticator attivo per {uid}")


async def secret(store, kind):
    if kind == OTP_RESET:
        await otp_reset(store, read_value("username o id Telegram: ", secret=False))
        return
    if kind not in SECRET_KINDS:
        raise SystemExit(f"tipo sconosciuto, scegli tra: {', '.join(SECRET_KINDS + (OTP_RESET,))}")
    if kind == "coc_api_key":
        value = read_keys(f"{kind}, una o più chiavi (invio vuoto per finire): ")
    else:
        hint = f" ({CLEAR_VALUE} per rimuovere)" if kind in CLEARABLE_KINDS else ""
        value = read_value(f"{kind}{hint}: ", secret=kind not in PLAIN_KINDS)
    await store_secret(store, kind, value)


def parse_addclan_args(argv):
    uso = "uso: addclan [--bot ALIAS]"
    bot_alias = None
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--bot":
            bot_alias = rest.pop(0) if rest else ""
        elif arg.startswith("--bot="):
            bot_alias = arg.split("=", 1)[1]
        else:
            raise SystemExit(uso)
        if not bot_alias:
            raise SystemExit(uso)
    return bot_alias


async def clan_bot_alias(store, bot_alias):
    workers = sorted(bot.alias for bot in await store.bots() if bot.kind != "console")
    if bot_alias:
        if bot_alias not in workers:
            raise SystemExit(f"bot sconosciuto: {bot_alias}")
        return bot_alias
    if len(workers) == 1:
        return workers[0]
    if workers:
        raise SystemExit(f"indica il bot con --bot ALIAS tra: {', '.join(workers)}")
    return None


async def addclan(store, bot_alias=None):
    bot_alias = await clan_bot_alias(store, bot_alias)
    chat_id = int(read_value("ID chat Telegram: ", secret=False))
    tag = normalize_tag(read_value("Tag del clan: ", secret=False))
    if not tag:
        raise SystemExit("tag non valido")
    api = CocApi(await store.get_secret("coc_api_key"))
    data, error = await api.clan(tag)
    await api.close()
    if not data:
        raise SystemExit(f"clan non trovato ({error})")
    clan = await store.add_clan(chat_id, tag, data.get("name"), bot_alias=bot_alias)
    print(f"  collegato: {clan.alias} · {clan.name}  bot={clan.bot_alias or '-'}")


async def addbot(store):
    token = read_value("Token del bot da registrare: ")
    me = await telegram_me(token)
    if not me:
        raise SystemExit("token Telegram non valido")
    owner = read_value(f"ID Telegram del proprietario di @{me.get('username')}: ", secret=False)
    try:
        owner_id = int(owner)
    except ValueError:
        raise SystemExit("id del proprietario non valido")
    try:
        bot = await store.add_bot(owner_id, token, me.get("username"), me.get("id"), trusted=True)
    except ValueError as e:
        raise SystemExit(f"bot non registrato ({e})")
    print(f"  bot {bot.alias}  {bot.kind}  @{bot.username}  proprietario {bot.owner_id}")


async def migrate_multibot(store, yes):
    token = await store.get_secret("telegram_token")
    if not token:
        raise SystemExit("manca telegram_token: docker compose run --rm bot secret telegram_token")
    owner = await store.get_secret("owner_id")
    if not owner:
        raise SystemExit("manca owner_id: docker compose run --rm bot secret owner_id")
    me = await telegram_me(token)
    if not me:
        raise SystemExit("token Telegram non valido")
    pending = await store.pending_migration()
    print(f"database: {store.dsn['database']}")
    print(f"bot worker: @{me.get('username')} (id {me.get('id')}), proprietario {owner}")
    print(f"da assegnare: {pending['clans']} clan, {pending['families']} famiglie")
    for bot in await store.bots():
        print(f"  già registrato: {bot.alias}  {bot.kind}  @{bot.username}")
    if not yes:
        print("nessuna modifica: ripeti con --yes per eseguire")
        return
    bot = await store.migrate_multibot(token, int(owner), me.get("username"), me.get("id"))
    print(f"  bot {bot.alias}  {bot.kind}  @{bot.username}")
    print(f"  clan assegnati: {bot.migrated_clans}, famiglie assegnate: {bot.migrated_families}")


async def status(store):
    print(f"chiave master: {store.vault.key_id}")
    for row in await store.list_secrets():
        print(f"  {row['kind']:<15} {row['alias']}  aggiornato {row['updated_at']:%Y-%m-%d %H:%M}")
    print(f"chiavi Clash: {len(parse_keys(await store.get_secret('coc_api_key')))}")
    bots = await store.bots()
    print(f"bot: {len(bots)}")
    for bot in bots:
        stato = "attivo" if bot.active else f"fermo ({bot.reason or 'senza motivo'})"
        print(f"  {bot.alias}  {bot.kind:<7} @{bot.username}  {stato}  clan={await store.count_clans(bot.alias)}")
    counts = await store.counts()
    print(f"clan: {counts['active']} attivi su {counts['total']}")
    for clan in await store.active_clans():
        seen = f"{clan.last_seen:%Y-%m-%d %H:%M}" if clan.last_seen else "mai"
        print(f"  {clan.alias}  {clan.name}  bot={clan.bot_alias or '-'}  errori={clan.failures}  ultimo controllo {seen}")


def health(argv=()):
    path = WEB_HEARTBEAT if list(argv) == ["--web"] else HEARTBEAT
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        raise SystemExit(1)
    raise SystemExit(0 if age < 300 else 1)


async def serve(supervisor):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        await supervisor.start()
        await stop.wait()
    finally:
        await supervisor.stop()


def run():
    async def load(store):
        return {kind: await store.get_secret(kind) for kind in ("telegram_token", "console_token", "coc_api_key")}

    secrets = asyncio.run(with_store(load))
    if not secrets["coc_api_key"] or not (secrets["telegram_token"] or secrets["console_token"]):
        log.error("configurazione mancante: docker compose run --rm bot setup")
        raise SystemExit(1)
    from .cards import missing_scripts
    from .supervisor import Supervisor

    absent = missing_scripts()
    if absent:
        log.warning("caratteri mancanti per le scritture: %s", ", ".join(absent))
    asyncio.run(serve(Supervisor(Store(Vault()), CocApi(secrets["coc_api_key"]))))


def main(argv):
    command = argv[0] if argv else "run"
    if command == "run":
        run()
    elif command == "health":
        health(argv[1:])
    elif command == "web":
        from .web.app import run as web_run

        asyncio.run(web_run())
    elif command == "setup":
        asyncio.run(with_store(setup))
    elif command == "secret":
        if len(argv) < 2:
            raise SystemExit(f"uso: secret <{'|'.join(SECRET_KINDS + (OTP_RESET,))}>")
        asyncio.run(with_store(lambda s: secret(s, argv[1])))
    elif command == "addclan":
        bot_alias = parse_addclan_args(argv[1:])
        asyncio.run(with_store(lambda s: addclan(s, bot_alias)))
    elif command == "addbot":
        asyncio.run(with_store(addbot))
    elif command == "status":
        asyncio.run(with_store(status))
    elif command == "retention":
        dry_run = parse_retention_args(argv[1:])
        asyncio.run(with_store(lambda s: run_retention_command(s, dry_run)))
    elif command == "notify":
        text = parse_notify_args(argv[1:])
        asyncio.run(with_store(lambda s: notify(s, text)))
    elif command == "restore-check":
        database = parse_restore_args(argv[1:])
        asyncio.run(run_restore_check(database))
    elif command == "migrate-multibot":
        yes, database = parse_migrate_args(argv[1:])
        asyncio.run(with_store(lambda s: migrate_multibot(s, yes), database))
    else:
        raise SystemExit(
            "comandi: run | web | setup | secret <tipo> | addbot | addclan [--bot ALIAS] | status"
            " | retention [--dry-run] | notify TESTO|- | restore-check --database NOME"
            " | migrate-multibot [--yes] [--database NOME] | health [--web]"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
