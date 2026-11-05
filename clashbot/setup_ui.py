from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import i18n, night, render, webmenu
from .events_registry import (CLAN_EVENTS as EVENTS, CLAN_PACKS as PACKS, INTENSITIES,
                              default_intensity, events_of)
from .settings import (MENTIONS, PRESETS, REMINDER_CHOICES, apply_preset, effective, migrate,
                       next_quiet_preset, web_conf)
from .web.payload import screen_of

STEPS = ("preset", "packs", "routes", "reminders", "mentions", "delegates", "locale", "web",
         "summary")

DONE = "done"

ADVANCED = "adv"

ADVANCED_STEP = "routes"

ALL_STEPS = STEPS + (DONE,)

DEFAULT_PRESET = "war_clan"

DEST_ORDER = ("group", "topic", "leaders_dm", "member_dm", "off")

REMINDER_BUTTONS = tuple((seconds, f"{seconds // 3600}h") for seconds in sorted(REMINDER_CHOICES, reverse=True))

WAR_INTENSITY_EVENTS = ("war.attack", "war.defense")

ON = "✅"
OFF = "🚫"
PICKED = "✓ "
LANG_COLUMNS = 2


def mark(value):
    return ON if value else OFF


def quiet_label(L, quiet):
    if not quiet:
        return L.t("settings.quiet.none")
    return L.t("settings.quiet.range", start=quiet[0], end=quiet[1])


def reminders_label(L, reminders):
    picked = [label for seconds, label in REMINDER_BUTTONS if seconds in (reminders or [])]
    if not picked:
        return L.t("settings.reminders.none")
    return " · ".join(L.t(f"settings.reminder.{label}") for label in picked)


def language_rows(current, prefix):
    buttons = [
        InlineKeyboardButton((PICKED if code == current else "") + name, callback_data=f"{prefix}{code}")
        for code, name in i18n.LANGUAGES.items()
    ]
    return [buttons[i:i + LANG_COLUMNS] for i in range(0, len(buttons), LANG_COLUMNS)]


def code_of(data):
    parts = (data or "").split(":")
    return parts[1] if len(parts) > 1 else ""


def advanced_of(step):
    head, _, pack = (step or "").partition(":")
    return pack if head == ADVANCED and pack in PACKS else None


def valid_step(step):
    return step if step in ALL_STEPS or advanced_of(step) else STEPS[0]


def choices_for(pack, thread=None):
    allowed = set()
    for event in events_of(pack):
        allowed.update(EVENTS[event]["allowed"])
    if not isinstance(thread, int):
        allowed.discard("topic")
    return tuple(dest for dest in DEST_ORDER if dest in allowed) or DEST_ORDER


def grounded(dests, topics, thread):
    if isinstance(thread, int):
        return dict(dests)
    return {pack: "group" if dest == "topic" and pack not in (topics or {}) else dest
            for pack, dest in dests.items()}


def preset_dests(conf):
    dests = {}
    for pack in PACKS:
        picked = "off"
        for event in events_of(pack):
            to = conf["routes"][event]["to"]
            if to != "off":
                picked = to
                break
        dests[pack] = picked
    return dests


def with_preset(state, preset):
    conf = effective(apply_preset(None, preset))
    doc = dict(state)
    doc.pop("base_routes", None)
    doc.pop("base_dests", None)
    doc.pop("events", None)
    doc["preset"] = preset
    doc["packs"] = dict(conf["packs"])
    doc["dests"] = preset_dests(conf)
    doc["intensity"] = conf["routes"]["war.attack"]["intensity"]
    doc["base_intensity"] = doc["intensity"]
    doc["reminders"] = list(conf["reminders"])
    doc["quiet"] = list(conf["quiet"]) if conf["quiet"] else None
    return doc


def from_settings(conf, code=None, user_id=None, thread=None):
    routes = {event: dict(conf["routes"][event]) for event in EVENTS}
    stored = preset_dests(conf)
    dests = grounded(stored, conf.get("topics"), thread)
    return {
        "code": code,
        "user_id": user_id,
        "step": STEPS[0],
        "live": True,
        "thread": thread,
        "lang": conf.get("lang"),
        "tz": conf.get("tz"),
        "preset": conf.get("preset"),
        "packs": {pack: bool((conf.get("packs") or {}).get(pack, True)) for pack in PACKS},
        "web": web_conf(conf),
        "base_routes": routes,
        "base_dests": dict(stored),
        "dests": dests,
        "intensity": routes["war.attack"]["intensity"],
        "base_intensity": routes["war.attack"]["intensity"],
        "topics": dict(conf.get("topics") or {}),
        "reminders": list(conf.get("reminders") or []),
        "quiet": list(conf["quiet"]) if conf.get("quiet") else None,
        "night": conf.get("night"),
        "mentions": conf.get("mentions"),
        "delegates": list(conf.get("delegates") or []),
        "candidates": [],
    }


def start(code, user_id, lang, tz):
    state = with_preset(
        {
            "code": code,
            "user_id": user_id,
            "lang": lang,
            "tz": tz,
            "mentions": None,
            "delegates": [],
            "candidates": [],
        },
        DEFAULT_PRESET,
    )
    state["step"] = STEPS[0]
    return state


def advance(step, state):
    if step == DONE:
        return DONE
    if advanced_of(step):
        return ADVANCED_STEP
    if step == "mentions" and state.get("mentions") not in MENTIONS:
        return "mentions"
    if step == STEPS[-1]:
        return DONE
    return STEPS[STEPS.index(step) + 1]


def cycle(options, current):
    index = options.index(current) if current in options else -1
    return options[(index + 1) % len(options)]


def candidates_of(state):
    return [(str(ref), name) for ref, name, _ in (state.get("candidates") or [])]


def uid_at(state, ref):
    return next((int(uid) for one, _, uid in (state.get("candidates") or ())
                 if str(one) == str(ref)), 0)


def toggled(state, ref):
    picked = [int(x) for x in (state.get("delegates") or [])]
    uid = uid_at(state, ref)
    if not uid:
        return picked
    if uid in picked:
        return [x for x in picked if x != uid]
    return picked + [uid]


def handle(state, data):
    doc = dict(state)
    parts = (data or "").split(":")
    action = parts[2] if len(parts) > 2 else ""
    value = parts[3] if len(parts) > 3 else ""
    event = parts[4] if len(parts) > 4 else ""
    step = valid_step(doc.get("step"))
    if action == "preset" and value in PRESETS:
        doc = with_preset(doc, value)
        step = "packs"
    elif action == "pack" and value in PACKS:
        packs = dict(doc.get("packs") or {})
        packs[value] = not packs.get(value, True)
        doc["packs"] = packs
    elif action == "dest" and value in PACKS:
        dests = dict(doc.get("dests") or {})
        dests[value] = cycle(choices_for(value, doc.get("thread")), dests.get(value))
        doc["dests"] = dests
    elif action == "web" and value in webmenu.FIELDS:
        doc["web"] = webmenu.apply(doc, value)["web"]
    elif action == ADVANCED and value in PACKS:
        step = f"{ADVANCED}:{value}"
    elif action == "ev" and value in PACKS and event in events_of(value):
        events = dict(doc.get("events") or {})
        options = tuple(dest for dest in EVENTS[event]["allowed"]
                        if dest != "topic" or isinstance(doc.get("thread"), int))
        events[event] = cycle(options, routes_of(doc)[event]["to"])
        doc["events"] = events
        step = f"{ADVANCED}:{value}"
    elif action == "topic" and value in PACKS and isinstance(doc.get("thread"), int):
        topics = dict(doc.get("topics") or {})
        if topics.get(value) == doc["thread"]:
            topics.pop(value, None)
        else:
            topics[value] = doc["thread"]
        doc["topics"] = topics
    elif action == "war":
        doc["intensity"] = cycle(INTENSITIES, doc.get("intensity"))
    elif action == "rem" and value.isdigit() and int(value) in REMINDER_CHOICES:
        picked = set(doc.get("reminders") or [])
        picked.symmetric_difference_update({int(value)})
        doc["reminders"] = [s for s, _ in REMINDER_BUTTONS if s in picked]
    elif action == "quiet":
        doc["quiet"] = next_quiet_preset(doc.get("quiet"))
    elif action == "night":
        doc["night"] = night.next_mode(night.mode(doc))
    elif action == "men" and value in MENTIONS:
        doc["mentions"] = value
        step = "delegates"
    elif action == "dlg" and value:
        doc["delegates"] = toggled(doc, value)
    elif action == "lang" and value in i18n.LANGUAGES:
        doc["lang"] = value
        doc["lang_set"] = True
    elif action == "next":
        step = advance(step, doc)
    doc["step"] = step
    return doc, step


def base_of(state):
    routes = state.get("base_routes")
    if routes:
        return routes, state.get("base_dests") or {}
    conf = effective(apply_preset(None, state.get("preset") if state.get("preset") in PRESETS else DEFAULT_PRESET))
    return conf["routes"], preset_dests(conf)


def routes_of(state):
    base, base_dests = base_of(state)
    dests = state.get("dests") or {}
    chosen = state.get("events") or {}
    routes = {}
    for event, meta in EVENTS.items():
        entry = dict(base.get(event) or {"to": meta["default"], "intensity": default_intensity(event)})
        dest, before = dests.get(meta["pack"]), base_dests.get(meta["pack"])
        if dest and dest != before and dest in meta["allowed"] and (entry["to"] != "off" or before == "off"):
            entry["to"] = dest
        if chosen.get(event) in meta["allowed"]:
            entry["to"] = chosen[event]
        routes[event] = entry
    intensity = state.get("intensity")
    if intensity in INTENSITIES and intensity != state.get("base_intensity"):
        for event in WAR_INTENSITY_EVENTS:
            routes[event]["intensity"] = intensity
    return routes


def updates(state):
    mentions = state.get("mentions") if state.get("mentions") in MENTIONS else None
    doc = {
        "preset": state.get("preset") if state.get("preset") in PRESETS else None,
        "packs": {pack: bool((state.get("packs") or {}).get(pack, True)) for pack in PACKS},
        "web": web_conf(state),
        "routes": routes_of(state),
        "topics": dict(state.get("topics") or {}),
        "reminders": list(state.get("reminders") or []),
        "quiet": list(state["quiet"]) if state.get("quiet") else None,
        "night": state["night"] if state.get("night") in night.MODES else None,
        "mentions": mentions,
        "delegates": [int(uid) for uid in (state.get("delegates") or [])],
        "setup_done": mentions is not None,
    }
    if state.get("lang_set"):
        doc["lang"] = state.get("lang")
    return doc


def to_settings(state):
    preset = state.get("preset") if state.get("preset") in PRESETS else DEFAULT_PRESET
    doc = apply_preset(None, preset)
    doc.update(updates(state))
    doc["preset"] = preset
    doc["lang"] = state.get("lang")
    doc["tz"] = state.get("tz")
    return migrate(doc)


def cb(state, action, value=None):
    head = f"cfg:{state.get('code')}:{action}"
    return head if value is None else f"{head}:{value}"


def skip_row(L, state, key="setup.btn_skip"):
    return [InlineKeyboardButton(L.t(key), callback_data=cb(state, "next"))]


def on_packs(state):
    return [pack for pack in PACKS if (state.get("packs") or {}).get(pack)]


def dest_label(L, state, pack):
    return L.t("setup.dest." + (state.get("dests") or {}).get(pack, "group"))


def war_label(L, state):
    return L.t("setup.war." + (state.get("intensity") or INTENSITIES[0]))


def mentions_label(L, state):
    return L.t("setup.mentions." + (state.get("mentions") or "never"))


def preset_screen(L, state):
    rows = [
        [InlineKeyboardButton(L.t(f"setup.preset.{name}"), callback_data=cb(state, "preset", name))]
        for name in PRESETS
    ]
    rows.append(skip_row(L, state))
    return L.t("setup.preset.q"), rows


def packs_screen(L, state):
    rows = [
        [InlineKeyboardButton(f"{mark((state.get('packs') or {}).get(pack))} {L.t(f'setup.pack.{pack}')}",
                              callback_data=cb(state, "pack", pack))]
        for pack in PACKS
    ]
    rows.append(skip_row(L, state))
    return L.t("setup.packs.q"), rows


def topic_row(L, state, pack):
    thread = state.get("thread")
    if not isinstance(thread, int) or (state.get("dests") or {}).get(pack) != "topic":
        return []
    label = mark((state.get("topics") or {}).get(pack) == thread) + " " + L.t(
        "setup.topic.use", pack=L.t(f"setup.pack.{pack}"))
    return [[InlineKeyboardButton(label, callback_data=cb(state, "topic", pack))]]


def advanced_row(L, state, pack):
    if not state.get("live"):
        return []
    return [[InlineKeyboardButton(L.t("setup.btn_advanced"), callback_data=cb(state, ADVANCED, pack))]]


def advanced_screen(L, state, pack):
    routes = routes_of(state)
    rows = [
        [InlineKeyboardButton(L.t(f"setup.event.{event}") + ": " + L.t("setup.dest." + routes[event]["to"]),
                              callback_data=cb(state, "ev", f"{pack}:{event}"))]
        for event in events_of(pack)
    ]
    rows.append(skip_row(L, state, "setup.btn_done"))
    return L.t("setup.advanced.q", pack=L.t(f"setup.pack.{pack}")), rows


def routes_screen(L, state):
    rows = []
    for pack in on_packs(state):
        label = L.t(f"setup.pack.{pack}") + ": " + dest_label(L, state, pack)
        rows.append([InlineKeyboardButton(label, callback_data=cb(state, "dest", pack))])
        rows += advanced_row(L, state, pack)
        rows += topic_row(L, state, pack)
    if (state.get("packs") or {}).get("wars"):
        label = L.t("setup.war.label") + ": " + war_label(L, state)
        rows.append([InlineKeyboardButton(label, callback_data=cb(state, "war"))])
    rows.append(skip_row(L, state))
    body = L.t("setup.routes.q") + "\n" + render.quote(L.t("setup.routes.topic_hint"))
    return body, rows


def reminders_screen(L, state):
    rows = [[
        InlineKeyboardButton(f"{mark(seconds in (state.get('reminders') or []))} {L.t('settings.reminder.' + label)}",
                             callback_data=cb(state, "rem", seconds))
        for seconds, label in REMINDER_BUTTONS
    ]]
    rows.append([InlineKeyboardButton(L.t("settings.quiet.label") + ": " + quiet_label(L, state.get("quiet")),
                                      callback_data=cb(state, "quiet"))])
    rows.append([InlineKeyboardButton(L.t("settings.night.label") + ": " + night.label(L, state),
                                      callback_data=cb(state, "night"))])
    rows.append(skip_row(L, state))
    return L.t("setup.reminders.q"), rows


def mentions_screen(L, state):
    rows = [
        [InlineKeyboardButton(L.t(f"setup.mentions.{value}"), callback_data=cb(state, "men", value))]
        for value in MENTIONS
    ]
    return L.t("setup.mentions.q"), rows


def delegates_screen(L, state):
    picked = [int(uid) for uid in (state.get("delegates") or [])]
    people = candidates_of(state)
    rows = [
        [InlineKeyboardButton(f"{mark(uid_at(state, ref) in picked)} {render.esc(name)}",
                              callback_data=cb(state, "dlg", ref))]
        for ref, name in people
    ]
    rows.append(skip_row(L, state))
    body = L.t("setup.delegates.q")
    if not people:
        body += "\n" + render.quote(L.t("setup.delegates.none"))
    return body, rows


def locale_screen(L, state):
    rows = language_rows(state.get("lang"), f"cfg:{state.get('code')}:lang:")
    rows.append(skip_row(L, state))
    lang = i18n.LANGUAGES.get(state.get("lang"), state.get("lang"))
    return L.t("setup.locale.q", lang=lang, tz=render.esc(state.get("tz"))), rows


def web_screen(L, state):
    body, markup = webmenu.screen(L, state, state.get("url"), state.get("slug"),
                                  lambda field: cb(state, "web", field))
    return body, [list(row) for row in markup.inline_keyboard] + [skip_row(L, state)]


def summary_lines(L, state):
    lines = []
    for pack in on_packs(state):
        lines.append(L.t(f"setup.pack.{pack}") + ": " + dest_label(L, state, pack))
    if (state.get("packs") or {}).get("wars"):
        lines.append(L.t("setup.war.label") + ": " + war_label(L, state))
    lines.append(L.t("settings.reminders.label") + ": " + reminders_label(L, state.get("reminders")))
    lines.append(L.t("settings.quiet.label") + ": " + quiet_label(L, state.get("quiet")))
    lines.append(L.t("settings.night.label") + ": " + night.label(L, state))
    lines.append(L.t("setup.mentions.label") + ": " + mentions_label(L, state))
    lines.append(L.t("setup.delegates.label") + ": "
                 + str(len([int(uid) for uid in (state.get("delegates") or [])])))
    lines.append(L.t("settings.lang.label") + ": "
                 + i18n.LANGUAGES.get(state.get("lang"), state.get("lang")))
    lines.append(L.t("settings.tz.label") + ": " + render.esc(state.get("tz")))
    return lines


def summary_screen(L, state):
    body = (L.t("setup.summary.q") + "\n" + render.quote("\n".join(summary_lines(L, state)))
            + "\n" + L.t("setup.summary.hint"))
    return body, [skip_row(L, state, "setup.btn_done")]


SCREENS = {
    "preset": preset_screen,
    "packs": packs_screen,
    "routes": routes_screen,
    "reminders": reminders_screen,
    "mentions": mentions_screen,
    "delegates": delegates_screen,
    "locale": locale_screen,
    "web": web_screen,
    "summary": summary_screen,
}


def screen(L, state, step):
    live = bool(state.get("live"))
    title = L.t("settings.title" if live else "setup.title")
    pack = advanced_of(step)
    if not pack and step not in SCREENS:
        body = L.t("settings.saved" if live else "setup.done") + "\n" + L.t("setup.summary.hint")
        return render.card("✅", title, body), None
    body, rows = advanced_screen(L, state, pack) if pack else SCREENS[step](L, state)
    subtitle = L.t("setup.step", n=STEPS.index(ADVANCED_STEP if pack else step) + 1, total=len(STEPS))
    return render.card("⚙️", title, body, subtitle=subtitle), InlineKeyboardMarkup(rows)


def to_json(L, state, step):
    return screen_of(*screen(L, state, step))
