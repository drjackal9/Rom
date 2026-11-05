PACKS = ("wars", "cwl", "capital_games", "members", "challenges", "recruitment", "family",
         "leaders", "bases", "platform", "integrations")

PLATFORM_PACK = "platform"

CLAN_PACKS = tuple(pack for pack in PACKS if pack != PLATFORM_PACK)

DESTINATIONS = ("group", "topic", "leaders_dm", "staff_dm", "member_dm", "off", "manager_dm")

PERSONAL = ("member_dm", "leaders_dm", "staff_dm")

URGENT = ("war.reminder", "war.end", "war.risk", "war.last_call", "cwl.reminder")

BOARD_LOST = "board.lost"
LEADERS_SUSPENDED = "leaders.suspended"
LINK_NEWS = "link.news"
TEXT_REFUSED = "text.refused"
PLATFORM_OPENED = "platform.opened"
FEED_ONLY = (BOARD_LOST, LEADERS_SUSPENDED, LINK_NEWS, TEXT_REFUSED, PLATFORM_OPENED)
HANDLER_FEED = ("war.warning", "challenges.ambassador")

INTENSITIES = ("all", "summary")

PUBLIC = ("group", "topic", "leaders_dm", "off")
GROUP_ONLY = ("group", "topic", "off")
MEMBER_OR_LEADERS = ("member_dm", "leaders_dm", "off")
PUBLIC_OR_MEMBER = ("group", "topic", "leaders_dm", "member_dm", "off")
GROUP_OR_MEMBER = ("group", "topic", "member_dm", "off")
PRIVATE = ("leaders_dm", "staff_dm", "off")
MEMBER_ONLY = ("member_dm", "off")
LEADERS_ONLY = ("leaders_dm", "off")
LEADERS_FIRST = ("group", "topic", "leaders_dm", "staff_dm", "off")
STAFF = ("group", "topic", "leaders_dm", "staff_dm", "member_dm", "off")

EVENTS = {
    "war.prep": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.start": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.attack": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": INTENSITIES},
    "war.defense": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": INTENSITIES},
    "war.end": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.reminder": {"pack": "wars", "default": "group", "allowed": PUBLIC_OR_MEMBER, "intensity": None},
    "war.board": {"pack": "wars", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "war.opponent_history": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.record": {"pack": "wars", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "cwl.day": {"pack": "cwl", "default": "group", "allowed": PUBLIC, "intensity": None},
    "cwl.reminder": {"pack": "cwl", "default": "group", "allowed": PUBLIC_OR_MEMBER, "intensity": None},
    "cwl.signup": {"pack": "cwl", "default": "group", "allowed": PUBLIC, "intensity": None},
    "cwl.season": {"pack": "cwl", "default": "group",
                   "allowed": ("group", "topic", "leaders_dm", "off"), "intensity": None},
    "cwl.roster": {"pack": "cwl", "default": "leaders_dm",
                   "allowed": ("group", "topic", "leaders_dm", "off"), "intensity": None},
    "cwl.scout": {"pack": "cwl", "default": "group",
                  "allowed": ("group", "topic", "leaders_dm", "off"), "intensity": None},
    "cwl.standings": {"pack": "cwl", "default": "group",
                      "allowed": ("group", "topic", "leaders_dm", "off"), "intensity": None},
    "cwl.bonus": {"pack": "cwl", "default": "leaders_dm",
                  "allowed": ("group", "topic", "leaders_dm", "off"), "intensity": None},
    "capital.start": {"pack": "capital_games", "default": "group", "allowed": PUBLIC, "intensity": None},
    "capital.reminder": {"pack": "capital_games", "default": "group", "allowed": PUBLIC_OR_MEMBER, "intensity": None},
    "capital.end": {"pack": "capital_games", "default": "group", "allowed": PUBLIC, "intensity": None},
    "capital.gold": {"pack": "capital_games", "default": "group", "allowed": PUBLIC, "intensity": None},
    "capital.skipped": {"pack": "capital_games", "default": "member_dm", "allowed": MEMBER_OR_LEADERS, "intensity": None},
    "capital.level": {"pack": "capital_games", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "games.start": {"pack": "capital_games", "default": "group", "allowed": PUBLIC, "intensity": None},
    "games.last_day": {"pack": "capital_games", "default": "group", "allowed": PUBLIC, "intensity": None},
    "games.board": {"pack": "capital_games", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "games.reminder": {"pack": "capital_games", "default": "member_dm", "allowed": MEMBER_OR_LEADERS,
                       "intensity": None},
    "games.end": {"pack": "capital_games", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "members.movement": {"pack": "members", "default": "group", "allowed": LEADERS_FIRST, "intensity": None},
    "members.rejoin": {"pack": "members", "default": "group", "allowed": PUBLIC, "intensity": None},
    "members.anniversary": {"pack": "members", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "members.achievement": {"pack": "members", "default": "group", "allowed": STAFF, "intensity": None},
    "members.report": {"pack": "members", "default": "leaders_dm", "allowed": PRIVATE, "intensity": None},
    "members.builder_board": {"pack": "members", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "members.builder_goal": {"pack": "members", "default": "group", "allowed": GROUP_OR_MEMBER,
                             "intensity": None},
    "members.legend": {"pack": "members", "default": "member_dm", "allowed": GROUP_OR_MEMBER,
                       "intensity": None},
    "members.goal": {"pack": "members", "default": "group", "allowed": GROUP_OR_MEMBER,
                     "intensity": None},
    "members.progress": {"pack": "members", "default": "member_dm", "allowed": GROUP_OR_MEMBER,
                         "intensity": None},
    "boards.week": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "boards.season": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "boards.mvp": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "boards.record": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "boards.rank": {"pack": "members", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "boards.donations": {"pack": "members", "default": "leaders_dm", "allowed": LEADERS_ONLY,
                         "intensity": None},
    "challenges.poll": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "challenges.season": {"pack": "challenges", "default": "group", "allowed": PUBLIC, "intensity": None},
    "challenges.quiz": {"pack": "challenges", "default": "off", "allowed": GROUP_ONLY, "intensity": None},
    "challenges.duel": {"pack": "challenges", "default": "group", "allowed": GROUP_OR_MEMBER, "intensity": None},
    "challenges.mission": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "challenges.bingo": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "challenges.award": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "challenges.vote": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "challenges.badge": {"pack": "challenges", "default": "member_dm", "allowed": GROUP_OR_MEMBER,
                         "intensity": None},
    "challenges.ambassador": {"pack": "challenges", "default": "member_dm", "allowed": MEMBER_ONLY,
                              "intensity": None},
    "family.transfer": {"pack": "family", "default": "group", "allowed": LEADERS_FIRST, "intensity": None},
    "family.digest": {"pack": "family", "default": "group", "allowed": LEADERS_FIRST, "intensity": None},
    "family.recruit": {"pack": "recruitment", "default": "leaders_dm", "allowed": LEADERS_FIRST, "intensity": None},
    "system.notice": {"pack": None, "default": "group", "allowed": PUBLIC, "intensity": None},
    "system.diagnostic": {"pack": None, "default": "leaders_dm", "allowed": LEADERS_FIRST, "intensity": None},
    "system.link_nudge": {"pack": "members", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.cleanup": {"pack": "wars", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "war.last_call": {"pack": "wars", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "war.midway": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.risk": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.availability": {"pack": "wars", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "war.roster": {"pack": "wars", "default": "leaders_dm", "allowed": PUBLIC, "intensity": None},
    "war.scout": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.forecast": {"pack": "wars", "default": "leaders_dm", "allowed": LEADERS_ONLY, "intensity": None},
    "war.forecast_result": {"pack": "wars", "default": "group", "allowed": PUBLIC, "intensity": None},
    "war.warning": {"pack": "wars", "default": "leaders_dm", "allowed": LEADERS_ONLY, "intensity": None},
    "leaders.welcome": {"pack": "leaders", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "leaders.rules": {"pack": "leaders", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "leaders.scheduled": {"pack": "leaders", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "leaders.gate": {"pack": "leaders", "default": "leaders_dm", "allowed": PUBLIC, "intensity": None},
    "leaders.exit": {"pack": "leaders", "default": "leaders_dm", "allowed": LEADERS_ONLY, "intensity": None},
    "leaders.promotion": {"pack": "leaders", "default": "leaders_dm", "allowed": LEADERS_ONLY,
                          "intensity": None},
    "leaders.trial": {"pack": "leaders", "default": "leaders_dm", "allowed": LEADERS_ONLY, "intensity": None},
    "family.derby.open": {"pack": "family", "default": "group", "allowed": PUBLIC, "intensity": None},
    "family.derby.end": {"pack": "family", "default": "group", "allowed": PUBLIC, "intensity": None},
    "family.notice": {"pack": "family", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "family.suggest": {"pack": "family", "default": "leaders_dm", "allowed": LEADERS_ONLY,
                       "intensity": None},
    "family.tournament.signup": {"pack": "family", "default": "group", "allowed": GROUP_ONLY,
                                 "intensity": None},
    "family.tournament.round": {"pack": "family", "default": "group", "allowed": GROUP_ONLY,
                                "intensity": None},
    "family.tournament.result": {"pack": "family", "default": "group", "allowed": GROUP_ONLY,
                                 "intensity": None},
    "family.tournament.final": {"pack": "family", "default": "group", "allowed": GROUP_ONLY,
                                "intensity": None},
    "challenges.tournament.signup": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY,
                                     "intensity": None},
    "challenges.tournament.round": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY,
                                    "intensity": None},
    "challenges.tournament.result": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY,
                                     "intensity": None},
    "challenges.tournament.final": {"pack": "challenges", "default": "group", "allowed": GROUP_ONLY,
                                    "intensity": None},
    "recruit.application": {"pack": "recruitment", "default": "leaders_dm",
                            "allowed": ("leaders_dm", "group", "topic", "off"), "intensity": None},
    "recruit.reminder": {"pack": "recruitment", "default": "leaders_dm",
                         "allowed": ("leaders_dm", "off"), "intensity": None},
    "bases.new": {"pack": "bases", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "bases.poll": {"pack": "bases", "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "bases.pack": {"pack": "bases", "default": "leaders_dm", "allowed": PUBLIC, "intensity": None},
    "system.stickers": {"pack": "members", "default": "group", "allowed": GROUP_ONLY,
                        "intensity": None},
    "system.survey": {"pack": None, "default": "group", "allowed": GROUP_ONLY, "intensity": None},
    "platform.key_down": {"pack": "platform", "default": "manager_dm", "allowed": ("manager_dm",),
                          "intensity": None},
    "platform.key_back": {"pack": "platform", "default": "manager_dm", "allowed": ("manager_dm",),
                          "intensity": None},
    "platform.restore": {"pack": "platform", "default": "manager_dm", "allowed": ("manager_dm",),
                         "intensity": None},
    "platform.ops": {"pack": "platform", "default": "manager_dm", "allowed": ("manager_dm",),
                     "intensity": None},
    "web.ready": {"pack": "members", "default": "leaders_dm",
                  "allowed": ("group", "topic", "leaders_dm", "off"), "intensity": None},
    "integrations.twitch_live": {"pack": "integrations", "default": "group", "allowed": GROUP_ONLY,
                                 "intensity": None},
    "integrations.bridge": {"pack": "integrations", "default": "group", "allowed": GROUP_ONLY,
                            "intensity": None},
    "integrations.notice": {"pack": "integrations", "default": "leaders_dm",
                            "allowed": ("leaders_dm", "group", "topic", "off"), "intensity": None},
}

EVENTS["system.news"] = dict(EVENTS["system.notice"], default="group", allowed=GROUP_ONLY)


CLAN_EVENTS = {name: meta for name, meta in EVENTS.items() if meta["pack"] != PLATFORM_PACK}


def default_intensity(event):
    meta = EVENTS.get(event)
    if not meta or not meta["intensity"]:
        return None
    return meta["intensity"][0]


def events_of(pack):
    return tuple(name for name, meta in EVENTS.items() if meta["pack"] == pack)


def routed(name):
    return name in EVENTS
