MODES = ("silent", "digest")

DEFAULT = "silent"


def mode(conf):
    value = (conf or {}).get("night")
    return value if value in MODES else DEFAULT


def next_mode(current):
    index = MODES.index(current) if current in MODES else 0
    return MODES[(index + 1) % len(MODES)]


def defers(conf, in_quiet):
    return bool(in_quiet) and mode(conf) == "digest"


def label(L, conf):
    return L.t(f"night.mode.{mode(conf)}")
