import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .util import zone as _zone

LANGUAGES = {
    "en": "English",
    "it": "Italiano",
    "es": "Español",
    "pt-BR": "Português (Brasil)",
    "de": "Deutsch",
    "fr": "Français",
    "tr": "Türkçe",
    "ru": "Русский",
    "ar": "العربية",
    "fa": "فارسی",
    "zh-Hans": "简体中文",
    "zh-Hant": "繁體中文",
    "ja": "日本語",
    "ko": "한국어",
    "id": "Bahasa Indonesia",
    "vi": "Tiếng Việt",
    "th": "ไทย",
    "hi": "हिन्दी",
    "pl": "Polski",
    "nl": "Nederlands",
}

DEFAULT = "en"

LOCALE_DIR = Path(__file__).resolve().parent / "locales"
OVERRIDE_DIR = Path("/locales")

ALIASES = {
    "pt": "pt-BR",
    "pt-br": "pt-BR",
    "pt-pt": "pt-BR",
    "zh": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-sg": "zh-Hans",
    "zh-hans": "zh-Hans",
    "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant",
    "zh-mo": "zh-Hant",
    "zh-hant": "zh-Hant",
    "in": "id",
}

NARROW = "\u202f"

SEPARATORS = {
    "it": (".", ","),
    "es": (".", ","),
    "pt-BR": (".", ","),
    "de": (".", ","),
    "tr": (".", ","),
    "id": (".", ","),
    "vi": (".", ","),
    "en": (",", "."),
    "zh-Hans": (",", "."),
    "zh-Hant": (",", "."),
    "ja": (",", "."),
    "ko": (",", "."),
    "th": (",", "."),
    "hi": (",", "."),
    "ar": (",", "."),
    "fa": (",", "."),
    "fr": (NARROW, ","),
    "ru": (NARROW, ","),
    "pl": (NARROW, ","),
    "nl": (".", ","),
}

ALWAYS_OTHER = {"zh-Hans", "zh-Hant", "ja", "ko", "vi", "th", "id"}
ZERO_ONE = {"fr", "pt-BR", "fa", "hi"}
SLAVIC = {"ru", "pl", "uk"}

_CATALOGS = {}
_LOCALES = {}
_OVERRIDES = {}


def clear_cache():
    _CATALOGS.clear()
    _LOCALES.clear()
    _OVERRIDES.clear()


def resolve(code):
    if not code:
        return DEFAULT
    raw = str(code).strip().replace("_", "-").lower()
    if not raw:
        return DEFAULT
    if raw in ALIASES:
        return ALIASES[raw]
    base = raw.split("-")[0]
    if base in ALIASES:
        return ALIASES[base]
    for known in LANGUAGES:
        if known.lower() in (raw, base):
            return known
    return DEFAULT


def _read(path):
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _catalog(code):
    if code not in _CATALOGS:
        merged = _read(LOCALE_DIR / f"{code}.json")
        merged.update(_read(Path(OVERRIDE_DIR) / f"{code}.json"))
        merged.update(_OVERRIDES.get(code) or {})
        _CATALOGS[code] = merged
    return _CATALOGS[code]


def set_overrides(code, mapping):
    resolved = resolve(code)
    _OVERRIDES[resolved] = {key: value for key, value in (mapping or {}).items()
                            if isinstance(key, str) and isinstance(value, str)}
    _CATALOGS.pop(resolved, None)


def overrides():
    return {code: dict(rows) for code, rows in _OVERRIDES.items() if rows}


def catalog(code):
    return dict(_catalog(resolve(code)))


def plural_form(code, value):
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return "other"
    if code in ALWAYS_OTHER:
        return "other"
    if code in SLAVIC:
        if number % 10 == 1 and number % 100 != 11:
            return "one"
        if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
            return "few"
        return "many"
    if code == "ar":
        if number == 0:
            return "zero"
        if number == 1:
            return "one"
        if number == 2:
            return "two"
        rest = number % 100
        if 3 <= rest <= 10:
            return "few"
        if 11 <= rest <= 99:
            return "many"
        return "other"
    if code in ZERO_ONE:
        return "one" if number in (0, 1) else "other"
    return "one" if number == 1 else "other"


def _pick(value, code, kw):
    if isinstance(value, dict):
        number = kw["count"] if "count" in kw else kw.get("n", 0)
        for form in (plural_form(code, number), "other", "one"):
            if isinstance(value.get(form), str):
                return value[form]
        return None
    return value


def _fill(raw, kw):
    if not kw or "{" not in raw:
        return raw
    try:
        return raw.format(**kw)
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        return raw


def _now():
    return datetime.now(timezone.utc)


class Locale:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return f"Locale({self.code!r})"

    def t(self, key, **kw):
        for code in (self.code, DEFAULT):
            raw = _pick(_catalog(code).get(key), self.code, kw)
            if isinstance(raw, str):
                return _fill(raw, kw)
        return f"[{key}]"

    def n(self, value):
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return "?"
        group = SEPARATORS.get(self.code, (",", "."))[0]
        return f"{number:,}".replace(",", group)

    def pct(self, value, digits=1):
        try:
            number = Decimal(str(float(value)))
            if not number.is_finite():
                return "?"
            text = str(number.quantize(Decimal(1).scaleb(-int(digits)), rounding=ROUND_HALF_UP))
        except (TypeError, ValueError, ArithmeticError):
            return "?"
        point = SEPARATORS.get(self.code, (",", "."))[1]
        return text.replace(".", point) + "%"

    def delta(self, target, now=None):
        if not target:
            return "?"
        try:
            seconds = int((target - (now or _now())).total_seconds())
        except TypeError:
            return "?"
        if seconds <= 0:
            return "0" + self.t("unit.m")
        hours, rest = divmod(seconds, 3600)
        minutes = rest // 60
        if hours >= 24:
            days, hours = divmod(hours, 24)
            return f"{days}{self.t('unit.d')} {hours}{self.t('unit.h')}"
        if hours:
            return f"{hours}{self.t('unit.h')} {minutes:02d}{self.t('unit.m')}"
        return f"{minutes}{self.t('unit.m')}"

    def ago(self, target, now=None):
        if not target:
            return "?"
        try:
            seconds = int(((now or _now()) - target).total_seconds())
        except TypeError:
            return "?"
        if seconds < 3600:
            return self.t("ago.now")
        if seconds < 86400:
            return self.t("ago.hours", n=seconds // 3600)
        days = seconds // 86400
        if days == 1:
            return self.t("ago.yesterday")
        return self.t("ago.days", n=days)

    def when(self, target, tz="UTC"):
        if not target:
            return "?"
        try:
            local = target.astimezone(_zone(tz))
        except (AttributeError, TypeError, ValueError):
            return "?"
        return self.t(
            "time.when",
            weekday=self.t(f"weekday.{local.weekday()}"),
            date=self.t("date.short", d=local.day, m=local.month),
            time=f"{local.hour:02d}:{local.minute:02d}",
        )

    def clock(self, target=None, tz="UTC"):
        try:
            local = (target or _now()).astimezone(_zone(tz))
        except (AttributeError, TypeError, ValueError):
            return "?"
        return f"{local.hour:02d}:{local.minute:02d}"

    def stars(self, n, total=3):
        try:
            slots = max(0, int(total))
        except (TypeError, ValueError):
            slots = 3
        try:
            filled = max(0, min(slots, int(n or 0)))
        except (TypeError, ValueError):
            filled = 0
        return "⭐" * filled + "☆" * (slots - filled)


def locale(code):
    resolved = resolve(code)
    if resolved not in _LOCALES:
        _LOCALES[resolved] = Locale(resolved)
    return _LOCALES[resolved]
