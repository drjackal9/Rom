# ClanBoard

[![ci](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

Telegram bot for Clash of Clans clans, in 20 languages. It follows wars, CWL, the Capital, Clan
Games, joins and leaves, and tells the clan group what happens, with the war board pinned on top.
Leaders get reminders, targets, leaderboards, clan titles and a weekly report. Everything is free
and nothing is unlocked by paying.

[Leggimi in italiano](README.it.md)

## Get it in your clan

Write `/newbot` with your clan tag to the ClanBoard console bot on Telegram, confirm in Telegram's
own window, then take the new bot into your clan group. Only verified leaders and co-leaders can
create a bot, and there is one bot per clan. In the group the bot keeps one pinned board and speaks only for the urgent moments of a war. From the button on that board everyone opens their own Mini App inside Telegram: the board, the war, their own data, and for whoever manages the clan the settings, the log and the tools.

## Self-host it

Clone this repository, then, inside it:

```
docker compose up -d db
docker compose run --rm bot setup
docker compose up -d
```

`setup` asks for, and stores encrypted in the database, the facts about your copy: the Telegram
token from BotFather, one or more Clash of Clans API keys, the public address of the source code
of your copy, which the licence requires, and the Telegram id that receives the alerts. The last
two can be skipped with an empty answer and set later with `secret source_url` and
`secret owner_id`: the address usually exists only after you publish your copy. There is no
configuration file, not now and not ever.

The Mini App wants two more things: the public address of the service in `secret site_base` and the
app registered on the console bot of your copy, done once from BotFather. Without them everything
else works the same and the pinned board stays without its button: the exact steps are on the
"Run your own copy" page of the site.

## Management

Every command runs from the terminal and writes nothing in clear text:

```
docker compose run --rm bot secret <kind>
docker compose run --rm bot addbot
docker compose run --rm bot addclan
docker compose run --rm bot status
docker compose run --rm bot retention --dry-run
```

Two kinds of secret are worth knowing by name: `secret channel_url` holds the address of the
official community, the link the home page and `/support` show when it is set, and
`secret otp_reset`, given the username or the Telegram id of a manager, clears the Authenticator
code of that person from the server. That is the only way back in when the phone with the codes is
gone, and it runs on the machine, never from a chat.

`ops/vps/backup.sh` takes the database dump, copies the master key and applies retention;
`ops/vps/guard.sh` watches the containers, the age of the last dump, the size of the database and
the errors in the log, and writes to the owner when something is off. Both are meant to run on a
schedule of the machine that hosts your copy, which stays outside this repository.

## Languages

20 languages, English as the source and fallback: see `clashbot/locales/`. A clan chooses its own
with `/lang`; in private chats the bot follows your Telegram language. Fixing a translation is the
easiest way to contribute: see [CONTRIBUTING.md](CONTRIBUTING.md).

A pull request is signed once, inside the pull request itself, with the contributor agreement in
[CLA.md](CLA.md).

## What it keeps, and for how long

Public game data taken from the official Clash of Clans API, plus what the clan writes through the
bot: the link between a Telegram account and a player tag for whoever links themselves with
`/link`, leader notes, applications. Everything is stored encrypted with AES-GCM; the master key
lives in a separate volume, never in the database and never in the repository. Wars are kept 100
per clan, deactivated clans are deleted after 90 days with everything that hangs from them, and
the keys with an expiry date go in the same cleanup. `/unlink` removes your link.

## Security

Every abuse we expect has a defence in the code and a test that breaks when the defence goes away.
The checklist is in [docs/sicurezza.md](docs/sicurezza.md), in Italian: one line per threat, with
the control and the name of the test that proves it.

## Maintainer

Alexandru Bumbac · GitHub @drjackal9

## Licence

ClanBoard · Copyright (C) 2026 Alexandru Bumbac (@drjackal9) · AGPL-3.0, see [LICENSE](LICENSE).

Running a modified copy that people can reach over a network means publishing your source and
setting its address with `secret source_url`: the bot shows it in `/support`.

## Clash of Clans

This material is unofficial and is not endorsed by Supercell. For more information see Supercell's Fan Content Policy: www.supercell.com/fan-content-policy
