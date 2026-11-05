from .util import esc, valid_https

NAME = "ClanBoard"
HOLDER = "Alexandru Bumbac (@drjackal9)"
YEAR = "2026"
LICENSE = "AGPL-3.0"
SECRET = "source_url"


def notice(L):
    return L.t("source.notice", name=NAME, year=YEAR, holder=HOLDER, license=LICENSE)


def offer(L, url=None):
    if not valid_https(url):
        return L.t("source.unpublished")
    return L.t("source.offer", url=esc(url))


def lines(L, url=None):
    return notice(L) + "\n" + offer(L, url)
