KIND = "views"
PLANS = "plans"
BASES = "bases"
LEAGUE = "league"
NUMBERS = "numbers"
SECTIONS = (PLANS, BASES, LEAGUE, NUMBERS)
EVERYONE = "approved"
IN_WAR = "in_war"
STAFF_ONLY = "managers"
VALUES = (EVERYONE, IN_WAR, STAFF_ONLY)
FAMILY = "family_score"
DEFAULTS = {PLANS: IN_WAR, BASES: EVERYONE, LEAGUE: EVERYONE, NUMBERS: EVERYONE}


def state_of(stored):
    stored = stored if isinstance(stored, dict) else {}
    found = {name: (stored.get(name) if stored.get(name) in VALUES else DEFAULTS[name])
             for name in SECTIONS}
    found[FAMILY] = bool(stored.get(FAMILY))
    return found


def set_one(state, section, value):
    if section not in SECTIONS or value not in VALUES:
        raise ValueError(f"{section}:{value}")
    return dict(state_of(state), **{section: value})


def toggle_family(state):
    fresh = state_of(state)
    return dict(fresh, **{FAMILY: not fresh[FAMILY]})


def sees(state, section, boss, in_war):
    if boss:
        return True
    value = state_of(state)[section]
    if value == EVERYONE:
        return True
    return bool(in_war) if value == IN_WAR else False
