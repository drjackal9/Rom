from zoneinfo import ZoneInfo

from . import night
from .events_registry import (CLAN_EVENTS as EVENTS, CLAN_PACKS as PACKS, URGENT,
                              default_intensity)
from .i18n import locale

SCHEMA_VERSION = 3

MANAGER = "manager"

LIMITED = "limited"

MENTIONS = ("group", "never")

LEGACY_MENTIONS = {"dm": "group"}

ACTIONS = {"settings": MANAGER, "targets": LIMITED, "warnings": LIMITED, "tools": MANAGER,
           "delegates": MANAGER, "pause": MANAGER, "links": LIMITED,
           "views": MANAGER}

LEGACY_OFF = {
    "achievements": ("members.achievement",),
    "agenda": ("cwl.signup", "games.start", "games.last_day", "challenges.season"),
    "polls": ("challenges.poll",),
    "movements": ("members.movement",),
    "board": ("war.board",),
}

LEGACY_SUMMARY = {"defenses": "war.defense"}

DEFAULTS = {
    "lang": None,
    "tz": None,
    "defenses": True,
    "achievements": True,
    "agenda": True,
    "polls": True,
    "movements": True,
    "board": True,
    "reminders": [28800, 14400, 3600],
    "quiet": None,
    "night": None,
    "min_th": None,
    "note": "",
    "web": None,
    "twitch": {},
    "news": False,
    "texts": {},
    "scheduled": [],
    "gate": False,
}

COUNTRY_TZ = {
    "IT": "Europe/Rome", "ES": "Europe/Madrid", "BR": "America/Sao_Paulo", "US": "America/New_York",
    "TR": "Europe/Istanbul", "RU": "Europe/Moscow", "CN": "Asia/Shanghai", "JP": "Asia/Tokyo", "KR": "Asia/Seoul",
    "IN": "Asia/Kolkata", "ID": "Asia/Jakarta", "VN": "Asia/Ho_Chi_Minh", "TH": "Asia/Bangkok", "SA": "Asia/Riyadh",
    "IR": "Asia/Tehran", "DE": "Europe/Berlin", "FR": "Europe/Paris", "PL": "Europe/Warsaw", "NL": "Europe/Amsterdam",
    "GB": "Europe/London", "MX": "America/Mexico_City", "AR": "America/Argentina/Buenos_Aires", "PT": "Europe/Lisbon",
    "EG": "Africa/Cairo", "PH": "Asia/Manila", "AU": "Australia/Sydney", "CA": "America/Toronto",
    "CO": "America/Bogota", "CL": "America/Santiago", "PE": "America/Lima", "AT": "Europe/Vienna", "CH": "Europe/Zurich",
    "BE": "Europe/Brussels", "BY": "Europe/Minsk", "KZ": "Asia/Almaty", "AE": "Asia/Dubai", "MA": "Africa/Casablanca",
    "DZ": "Africa/Algiers", "IQ": "Asia/Baghdad", "TW": "Asia/Taipei", "HK": "Asia/Hong_Kong",
    "SE": "Europe/Stockholm", "NO": "Europe/Oslo", "DK": "Europe/Copenhagen", "FI": "Europe/Helsinki", "IE": "Europe/Dublin",
    "GR": "Europe/Athens", "RO": "Europe/Bucharest", "HU": "Europe/Budapest", "CZ": "Europe/Prague", "SK": "Europe/Bratislava",
    "UA": "Europe/Kyiv", "RS": "Europe/Belgrade", "HR": "Europe/Zagreb", "BG": "Europe/Sofia", "CY": "Asia/Nicosia",
    "IL": "Asia/Jerusalem", "JO": "Asia/Amman", "LB": "Asia/Beirut", "KW": "Asia/Kuwait", "QA": "Asia/Qatar",
    "PK": "Asia/Karachi", "BD": "Asia/Dhaka", "LK": "Asia/Colombo", "NP": "Asia/Kathmandu", "MM": "Asia/Yangon",
    "MY": "Asia/Kuala_Lumpur", "SG": "Asia/Singapore", "NZ": "Pacific/Auckland", "ZA": "Africa/Johannesburg",
    "NG": "Africa/Lagos", "KE": "Africa/Nairobi", "TN": "Africa/Tunis", "LY": "Africa/Tripoli", "ET": "Africa/Addis_Ababa",
    "GH": "Africa/Accra", "UY": "America/Montevideo", "VE": "America/Caracas", "EC": "America/Guayaquil",
    "BO": "America/La_Paz", "PY": "America/Asuncion", "CR": "America/Costa_Rica", "PA": "America/Panama",
    "DO": "America/Santo_Domingo", "CU": "America/Havana", "GT": "America/Guatemala",
}

COUNTRY_LANG = {
    "IT": "it",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es", "CL": "es", "PE": "es",
    "BR": "pt-BR", "PT": "pt-BR",
    "DE": "de", "AT": "de", "CH": "de",
    "FR": "fr", "BE": "fr",
    "TR": "tr",
    "RU": "ru", "BY": "ru", "KZ": "ru",
    "SA": "ar", "EG": "ar", "AE": "ar", "MA": "ar", "DZ": "ar", "IQ": "ar",
    "IR": "fa",
    "CN": "zh-Hans",
    "TW": "zh-Hant", "HK": "zh-Hant",
    "JP": "ja",
    "KR": "ko",
    "ID": "id",
    "VN": "vi",
    "TH": "th",
    "IN": "hi",
    "PL": "pl",
    "NL": "nl",
}

QUIET_PRESETS = [None, [23, 7], [0, 8], [22, 8]]

REMINDER_CHOICES = {28800, 14400, 3600}


def _all_packs(value=True):
    return {pack: value for pack in PACKS}


def _leaders_routes():
    routes = {}
    for name, meta in EVENTS.items():
        if name in URGENT:
            to = meta["default"]
        else:
            to = "leaders_dm" if "leaders_dm" in meta["allowed"] else "off"
        routes[name] = {"to": to, "intensity": default_intensity(name)}
    for name in ("war.attack", "war.defense"):
        routes[name] = {"to": "leaders_dm", "intensity": "summary"}
    return routes


PRESETS = {
    "war_clan": {
        "packs": _all_packs(),
        "routes": {
            "war.attack": {"to": "group", "intensity": "all"},
            "war.defense": {"to": "group", "intensity": "all"},
        },
        "reminders": [28800, 14400, 3600],
        "quiet": None,
    },
    "casual_clan": {
        "packs": dict(_all_packs(), cwl=False, recruitment=False, family=False),
        "routes": {
            "war.attack": {"to": "group", "intensity": "summary"},
            "war.defense": {"to": "group", "intensity": "summary"},
        },
        "reminders": [3600],
        "quiet": [23, 7],
    },
    "family": {
        "packs": _all_packs(),
        "routes": {
            "war.attack": {"to": "group", "intensity": "summary"},
            "war.defense": {"to": "group", "intensity": "summary"},
            "family.transfer": {"to": "group", "intensity": None},
            "family.digest": {"to": "group", "intensity": None},
        },
        "reminders": [14400, 3600],
        "quiet": [23, 7],
    },
    "leaders_only": {
        "packs": dict(_all_packs(), bases=False),
        "routes": _leaders_routes(),
        "reminders": [3600],
        "quiet": [23, 7],
    },
}


def valid_tz(tz):
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def _sanitize_quiet(value):
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(
        isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 23 for x in value
    ):
        return list(value)
    return None


def _sanitize_night(value):
    return value if value in night.MODES else None


def _night_of(src):
    chosen = _sanitize_night(src.get("night"))
    if chosen or "night" in src:
        return chosen
    return "digest" if _sanitize_quiet(src.get("quiet")) else None


def _sanitize_reminders(value):
    if isinstance(value, list) and all(
        isinstance(x, int) and not isinstance(x, bool) and x in REMINDER_CHOICES for x in value
    ):
        return list(value)
    return list(DEFAULTS["reminders"])


def _sanitize_texts(value):
    return value if isinstance(value, dict) else dict(DEFAULTS["texts"])


def _sanitize_scheduled(value):
    return value if isinstance(value, list) else list(DEFAULTS["scheduled"])


def _sanitize_block(value, key):
    return dict(value) if isinstance(value, dict) else dict(DEFAULTS[key])


def _route_entry(meta, entry):
    if isinstance(entry, str):
        entry = {"to": entry}
    if not isinstance(entry, dict):
        entry = {}
    to = entry.get("to")
    if to not in meta["allowed"]:
        to = meta["default"]
    intensity = entry.get("intensity")
    if not meta["intensity"]:
        intensity = None
    elif intensity not in meta["intensity"]:
        intensity = meta["intensity"][0]
    return {"to": to, "intensity": intensity}


def _clean_routes(raw):
    routes = {}
    stored = raw if isinstance(raw, dict) else {}
    for event, entry in stored.items():
        meta = EVENTS.get(event)
        if not meta:
            continue
        routes[event] = _route_entry(meta, entry)
    return routes


def _prune_routes(routes):
    pruned = {}
    for event, entry in routes.items():
        meta = EVENTS[event]
        if entry["to"] == meta["default"] and entry["intensity"] == default_intensity(event):
            continue
        pruned[event] = entry
    return pruned


def _apply_legacy(routes, src):
    for key, events in LEGACY_OFF.items():
        if key not in src:
            continue
        for event in events:
            if src[key]:
                if routes.get(event, {}).get("to") == "off":
                    routes.pop(event)
            else:
                routes[event] = {"to": "off", "intensity": default_intensity(event)}
    for key, event in LEGACY_SUMMARY.items():
        if key not in src:
            continue
        meta = EVENTS[event]
        entry = routes.get(event) or {"to": meta["default"], "intensity": default_intensity(event)}
        wanted = meta["intensity"][0] if src[key] else meta["intensity"][1]
        routes[event] = {"to": entry["to"], "intensity": wanted}
    return routes


def _clean_packs(raw):
    stored = raw if isinstance(raw, dict) else {}
    return {pack: True if stored.get(pack) is None else bool(stored.get(pack)) for pack in PACKS}


def _clean_delegates(raw):
    stored = raw if isinstance(raw, (list, tuple)) else ()
    picked = []
    for value in stored:
        if isinstance(value, int) and not isinstance(value, bool) and value not in picked:
            picked.append(value)
    return picked


def _clean_topics(raw):
    stored = raw if isinstance(raw, dict) else {}
    return {pack: value for pack, value in stored.items()
            if pack in PACKS and isinstance(value, int) and not isinstance(value, bool)}


def migrate(settings):
    src = dict(settings or {})
    from_v1 = bool(src) and src.get("version") != SCHEMA_VERSION
    setup_done = bool(src.get("setup_done")) or from_v1

    mentions = LEGACY_MENTIONS.get(src.get("mentions"), src.get("mentions"))
    if mentions not in MENTIONS:
        mentions = "group" if setup_done else None

    preset = src.get("preset")
    if preset not in PRESETS:
        preset = None

    routes = _prune_routes(_apply_legacy(_clean_routes(src.get("routes")), src))

    return {
        "version": SCHEMA_VERSION,
        "lang": src.get("lang"),
        "tz": src.get("tz"),
        "preset": preset,
        "packs": _clean_packs(src.get("packs")),
        "routes": routes,
        "topics": _clean_topics(src.get("topics")),
        "mentions": mentions,
        "delegates": _clean_delegates(src.get("delegates")),
        "setup_done": setup_done,
        "reminders": _sanitize_reminders(src.get("reminders")),
        "quiet": _sanitize_quiet(src.get("quiet")),
        "night": _night_of(src),
        "min_th": src.get("min_th"),
        "note": src.get("note") or "",
        "web": web_conf(src),
        "twitch": _sanitize_block(src.get("twitch"), "twitch"),
        "news": bool(src.get("news")),
        "texts": _sanitize_texts(src.get("texts")),
        "scheduled": _sanitize_scheduled(src.get("scheduled")),
        "gate": bool(src.get("gate")),
    }


def merge(settings, changes):
    doc = dict(settings) if settings else migrate(None)
    doc.update(changes or {})
    return doc


def pack_on(conf, pack):
    if pack is None:
        return True
    packs = conf.get("packs") or {}
    return packs.get(pack, True) is not False


def route(conf, event):
    meta = EVENTS.get(event)
    if not meta or not pack_on(conf, meta["pack"]):
        return ("off", None)
    entry = _route_entry(meta, (conf.get("routes") or {}).get(event))
    if entry["to"] == "off":
        return ("off", None)
    return (entry["to"], entry["intensity"])


def allowed(conf, action, level):
    needed = ACTIONS.get(action)
    if not needed:
        return False
    if level == MANAGER:
        return True
    return level == LIMITED and needed == LIMITED


def apply_preset(settings, preset):
    doc = migrate(settings)
    spec = PRESETS.get(preset)
    if not spec:
        return doc
    doc["preset"] = preset
    doc["packs"] = dict(spec["packs"])
    doc["routes"] = {event: dict(entry) for event, entry in spec["routes"].items()}
    doc["reminders"] = list(spec["reminders"])
    doc["quiet"] = list(spec["quiet"]) if spec["quiet"] else None
    return migrate(doc)


def effective(settings, clan_json=None):
    conf = migrate(settings)

    location = (clan_json or {}).get("location") or {}
    country = location.get("countryCode")

    lang = conf.get("lang")
    if lang is None:
        lang = COUNTRY_LANG.get(country, "en")

    tz = conf.get("tz")
    if tz is None:
        tz = COUNTRY_TZ.get(country, "UTC")
    if not valid_tz(tz):
        tz = "UTC"

    conf["lang"] = lang
    conf["tz"] = tz
    conf["routes"] = {event: _route_entry(meta, conf["routes"].get(event)) for event, meta in EVENTS.items()}

    for key, events in LEGACY_OFF.items():
        conf[key] = any(route(conf, event)[0] != "off" for event in events)
    for key, event in LEGACY_SUMMARY.items():
        destination, intensity = route(conf, event)
        conf[key] = destination != "off" and intensity == EVENTS[event]["intensity"][0]
    return conf


async def clan_locale(store, clan):
    conf = effective(await store.get_state(clan.alias, "settings"), None)
    return locale(conf["lang"]), conf["tz"]


def is_quiet(settings, now):
    quiet = settings.get("quiet")
    if not quiet:
        return False
    start, end = quiet
    if start == end:
        return False
    tz = settings.get("tz") or "UTC"
    if not valid_tz(tz):
        tz = "UTC"
    local_hour = now.astimezone(ZoneInfo(tz)).hour
    if start < end:
        return start <= local_hour < end
    return local_hour >= start or local_hour < end


def next_quiet_preset(current):
    try:
        index = QUIET_PRESETS.index(current)
    except ValueError:
        index = 0
    return QUIET_PRESETS[(index + 1) % len(QUIET_PRESETS)]


WEB_DEFAULTS = {"page": False, "members": False, "stats": False, "widget": False, "ics": False}


def web_conf(settings):
    stored = (settings or {}).get("web")
    merged = dict(WEB_DEFAULTS)
    if isinstance(stored, dict):
        merged.update({key: bool(value) for key, value in stored.items() if key in WEB_DEFAULTS})
    return merged
