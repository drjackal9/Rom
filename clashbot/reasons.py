NOT_LINKED = "not_linked"
NOT_APPROVED = "not_approved"
NOT_IN_WAR = "not_in_war"
NOT_MANAGER = "not_manager"
CHIEF_ONLY = "chief"
TAKEN = "taken"
CLOSED = "closed"
PAUSED = "paused"
BRAKE = "brake"
TEXT_REFUSED = "text_refused"
GONE = "gone"
BANNED = "banned"
BAD = "bad"
REFUSED = "refused"
NEEDS_TOKEN = "needs_token"
TERMS = "terms"
REASONS = (NOT_LINKED, NOT_APPROVED, NOT_IN_WAR, NOT_MANAGER, CHIEF_ONLY, TAKEN, CLOSED,
           PAUSED, BRAKE, TEXT_REFUSED, GONE, BANNED, BAD, REFUSED, NEEDS_TOKEN, TERMS)
RESERVED = (PAUSED,)


def refuse(code):
    if code not in REASONS:
        raise ValueError(code)
    return code


def done(outcome):
    return outcome is True


def code_of(outcome):
    return outcome if outcome in REASONS else REFUSED
