import re
from urllib.parse import parse_qs, quote, urlsplit

from . import render

LINK_HOST = "link.clashofclans.com"
VILLAGES = {"HV": "home", "BB": "builder"}
HALL_PREFIX = {"home": "TH", "builder": "BH"}
LABELS = ("war", "farm", "hybrid", "trophy", "cwl")
PAGE = 10
HALL_RE = re.compile(r"^(TH|BH)(\d{1,2})$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def parse_link(raw):
    if not raw:
        return None
    parts = urlsplit(str(raw).strip())
    if parts.scheme not in ("http", "https") or parts.netloc.lower() != LINK_HOST:
        return None
    params = parse_qs(parts.query)
    if (params.get("action") or [""])[0] != "OpenLayout":
        return None
    pieces = (params.get("id") or [""])[0].split(":")
    if len(pieces) != 3:
        return None
    hall_raw, village_raw, payload = pieces[0].upper(), pieces[1].upper(), pieces[2]
    village = VILLAGES.get(village_raw)
    match = HALL_RE.match(hall_raw)
    if not village or not match or not ID_RE.match(payload):
        return None
    if HALL_PREFIX[village] != match.group(1):
        return None
    return {"village": village, "hall": int(match.group(2)),
            "id": f"{hall_raw}:{village_raw}:{payload}"}


def link_url(L, layout_id):
    return (f"https://{LINK_HOST}/{L.t('link.lang')}?action=OpenLayout"
            f"&id={quote(layout_id, safe='')}")


def label_name(L, label):
    return L.t(f"bases.label.{label}") if label in LABELS else L.t("bases.label.war")


def hall_name(village, hall):
    return f"{HALL_PREFIX.get(village, HALL_PREFIX['home'])}{hall}"


def halls(rows, village):
    seen = {row["hall"] for row in rows or ()
            if row.get("village") == village and row.get("hall")}
    return sorted(seen, reverse=True)


def row_line(L, row, index):
    marks = ""
    if row.get("winner"):
        marks += " 🏆"
    if row.get("shared"):
        marks += " 📚"
    if row.get("published"):
        marks += " 📦"
    return L.t("bases.row", rank=render.rank(L, index),
               hall=hall_name(row.get("village"), row.get("hall")),
               label=label_name(L, row.get("label")),
               name=render.esc(row.get("name") or "?"), marks=marks)


def card(L, rows, scope, village, hall):
    subtitle = L.t(f"bases.village.{village}")
    if hall:
        subtitle += f" · {hall_name(village, hall)}"
    if not rows:
        return render.card("🏰", L.t(f"bases.tab.{scope}"), L.t("bases.empty"), subtitle)
    body = render.quote("\n".join(row_line(L, row, i) for i, row in enumerate(rows)))
    return render.card("🏰", L.t(f"bases.tab.{scope}"), body, subtitle)
