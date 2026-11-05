from string import Formatter

import pytest

from clashbot import i18n, scoring, tournaments
from clashbot.events_registry import EVENTS
from test_locales import CATALOGS, SOURCES, forms

GROUP_A = (
    "tournament.kind.derby", "tournament.kind.internal", "tournament.kind.clash",
    "tournament.state.signup", "tournament.state.running", "tournament.state.done",
    "tournament.metric.stars", "tournament.metric.activity", "tournament.metric.both",
    "tournament.metric.triples", "tournament.metric.donated", "tournament.metric.capital_gold",
    "tournament.metric.loot", "tournament.metric.games", "tournament.metric.line",
    "tournament.scope.clan", "tournament.scope.family", "tournament.scope.network",
    "tournament.open.scope", "tournament.no_family", "tournament.no_network",
    "tournament.format.table", "tournament.format.groups", "tournament.format.bracket",
    "tournament.entries", "tournament.entry", "tournament.row", "tournament.value.activity",
    "tournament.group", "tournament.round", "tournament.match", "tournament.match.done",
    "tournament.bye", "tournament.mission", "tournament.list.title", "tournament.list.row",
    "tournament.none", "tournament.open.title", "tournament.open.metric", "tournament.open.format",
    "tournament.open.size", "tournament.open.window", "tournament.btn.join", "tournament.btn.leave",
    "tournament.btn.open", "tournament.btn.refresh", "tournament.btn.window", "tournament.btn.go",
    "tournament.btn.cancel", "tournament.ok", "tournament.dup", "tournament.full",
    "tournament.closed", "tournament.left", "tournament.opened", "tournament.denied",
    "tournament.signup.title", "tournament.signup.body", "tournament.round.title",
    "tournament.result.title", "tournament.final.title", "tournament.final.body",
    "tournament.final.none", "tournament.empty.body", "tournament.notice.signup",
    "tournament.notice.final", "cmd.tournament",
)

GROUP_B = ("title.Derby", "title.Torneo")

GROUP_C = (
    "derby.title", "derby.proposed", "derby.row", "derby.empty", "derby.metric", "derby.mission",
    "derby.mission.first", "derby.btn.go", "derby.btn.skip", "derby.saved", "derby.none",
    "derby.end.title", "derby.end.winner", "derby.end.mission.hit", "derby.end.mission.miss",
    "derby.end.mission.first", "derby.notice",
)

GROUP_D = (
    "family.notice.row", "family.notice.icon.derby", "family.notice.icon.tournament",
    "family.notice.icon.message", "family.suggest.title", "family.suggest.row.below",
    "family.suggest.row.up", "family.suggest.none", "family.message.title", "family.message.ask",
    "family.message.preview", "family.message.btn.send", "family.message.btn.cancel",
    "family.message.sent", "family.message.cancelled", "family.message.too_soon",
    "h.family_notice_private",
)

BLOCK = GROUP_A + GROUP_B + GROUP_C + GROUP_D

ACTIONS = ("join", "leave")

OUTCOMES = ("ok", "dup", "full", "closed", "left")

NOTICE_KINDS = ("derby", "tournament", "message")

SUGGEST_REASONS = ("below", "up")

BLOCK_TITLES = ("Derby", "Torneo")

BLOCK_EVENTS = tuple(
    name for name in EVENTS
    if "tournament" in name or "derby" in name or name in ("family.notice", "family.suggest")
)


def sample(text):
    names = {name for _, name, _, _ in Formatter().parse(text) if name}
    return {name: 2 if name == "n" else "x" for name in names}


def rendered(code, key):
    return i18n.locale(code).t(key, **sample(forms(CATALOGS["en"][key])["other"]))


def carries(code, key):
    return key in CATALOGS[code] and not rendered(code, key).startswith("[")


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_block_keys_are_in_every_catalog(code):
    assert [key for key in BLOCK if key not in CATALOGS[code]] == [], code


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_block_keys_keep_the_english_order(code):
    chosen = set(BLOCK)
    order = [key for key in CATALOGS["en"] if key in chosen]
    assert [key for key in CATALOGS[code] if key in chosen] == order, code


@pytest.mark.parametrize("code", sorted(SOURCES))
def test_block_keys_read_as_written_text(code):
    for key in BLOCK:
        for text in forms(CATALOGS[code][key]).values():
            assert text.strip() and text.strip() != key, (code, key)


@pytest.mark.parametrize("code", sorted(set(i18n.LANGUAGES) - set(SOURCES)))
def test_block_keys_wait_for_the_translation_phase(code):
    for key in BLOCK:
        assert CATALOGS[code].get(key) == CATALOGS["en"][key], (code, key)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_block_keys_render_without_leftovers(code):
    for key in BLOCK:
        text = rendered(code, key)
        assert not text.startswith("["), (code, key)
        assert "{" not in text and "}" not in text, (code, key, text)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_every_tournament_choice_has_a_label(code):
    keys = [f"tournament.kind.{value}" for value in tournaments.KINDS]
    keys += [f"tournament.scope.{value}" for value in tournaments.SCOPES]
    keys += [f"tournament.format.{value}" for value in tournaments.FORMATS]
    keys += [f"tournament.metric.{value}" for value in tournaments.METRICS]
    keys += [f"tournament.state.{value}" for value in tournaments.STATUSES]
    keys += [f"tournament.btn.{value}" for value in ACTIONS]
    keys += [f"tournament.{value}" for value in OUTCOMES]
    for key in keys:
        assert carries(code, key), (code, key)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_family_board_has_every_icon_and_reason(code):
    keys = [f"family.notice.icon.{kind}" for kind in NOTICE_KINDS]
    keys += [f"family.suggest.row.{why}" for why in SUGGEST_REASONS]
    for key in keys:
        assert carries(code, key), (code, key)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_block_events_have_a_setup_label(code):
    assert BLOCK_EVENTS
    for name in BLOCK_EVENTS:
        assert carries(code, f"setup.event.{name}"), (code, name)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_block_titles_are_in_the_albo(code):
    for name in BLOCK_TITLES:
        assert name in scoring.TITLES, name
        assert carries(code, f"title.{name}"), (code, name)
