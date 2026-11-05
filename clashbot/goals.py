from . import hero_caps
from .achievements import BEST_STEP, HERO_STEP, STAR_STEP

KINDS = ("trophies", "warstars", "th", "hero")
STEPS = 3


def _int(value):
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _heroes(snapshot):
    heroes = (snapshot or {}).get("heroes")
    return heroes if isinstance(heroes, dict) else {}


def _ladder(value, step):
    first = (_int(value) // step + 1) * step
    return [first + step * i for i in range(STEPS)]


def choices(snapshot, kind):
    if not isinstance(snapshot, dict):
        return []
    if kind == "trophies":
        return [{"target": t, "hero": None} for t in _ladder(snapshot.get("trophies"), BEST_STEP)]
    if kind == "warstars":
        return [{"target": t, "hero": None} for t in _ladder(snapshot.get("warStars"), STAR_STEP)]
    if kind == "th":
        level = _int(snapshot.get("th"))
        return [{"target": level + 1, "hero": None}] if 0 < level < hero_caps.TOP_TH else []
    if kind != "hero":
        return []
    heroes = _heroes(snapshot)
    for hero in hero_caps.ORDER:
        if hero not in heroes:
            continue
        ceiling = hero_caps.cap(hero, snapshot.get("th"))
        level = _int(heroes.get(hero))
        if not ceiling or level >= ceiling:
            continue
        targets = [t for t in _ladder(level, HERO_STEP) if t <= ceiling]
        if ceiling not in targets:
            targets.append(ceiling)
        return [{"target": t, "hero": hero} for t in targets[:STEPS]]
    return []


def kinds_for(snapshot):
    if not isinstance(snapshot, dict):
        return []
    return [kind for kind in KINDS if choices(snapshot, kind)]


def current(snapshot, goal):
    p = snapshot if isinstance(snapshot, dict) else {}
    kind = (goal or {}).get("kind")
    if kind == "trophies":
        return _int(p.get("trophies"))
    if kind == "warstars":
        return _int(p.get("warStars"))
    if kind == "th":
        return _int(p.get("th"))
    if kind == "hero":
        return _int(_heroes(p).get((goal or {}).get("hero")))
    return 0


def reached(goal, snapshot):
    if not isinstance(goal, dict) or goal.get("kind") not in KINDS:
        return False
    target = _int(goal.get("target"))
    return bool(target) and current(snapshot, goal) >= target


def picks_for(snapshot):
    return [{"kind": kind, "hero": pick["hero"], "target": pick["target"]}
            for kind in kinds_for(snapshot) for pick in choices(snapshot, kind)]


def view(snapshot, goal):
    if not isinstance(snapshot, dict) or not snapshot:
        return None
    chosen = goal if isinstance(goal, dict) and goal.get("kind") in KINDS else {}
    return {"kind": chosen.get("kind"),
            "hero": chosen.get("hero"),
            "target": _int(chosen.get("target")),
            "value": current(snapshot, chosen) if chosen else 0,
            "picks": picks_for(snapshot)}
