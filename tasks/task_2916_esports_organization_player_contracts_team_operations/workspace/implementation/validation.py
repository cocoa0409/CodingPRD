"""Band 5 request-shape validation and band 3/6 existence lookups.

PRD section 2.4: computed fields are never client-writable -- an attempt to supply one is
simply ignored, so unknown body keys are never an error.
"""

from flask import request

import db
from errors import fail

MISSING = object()


def body():
    """The request's JSON object, or {} when no body was sent."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def present(payload, name):
    return name in payload and payload[name] is not None


# --------------------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------------------

def req_str(payload, name, min_len=1, max_len=None, upper=False):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    return _as_str(payload[name], name, min_len, max_len, upper)


def opt_str(payload, name, default=None, min_len=1, max_len=None, upper=False,
            allow_null=True):
    if name not in payload:
        return default
    if payload[name] is None:
        if allow_null:
            return None
        _bad(name, "must not be null")
    return _as_str(payload[name], name, min_len, max_len, upper)


def _as_str(value, name, min_len, max_len, upper):
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    if upper and value != value.upper():
        _bad(name, "must be uppercase")
    return value


def free_text(payload, name, default=None):
    """A free-text note: any string, or null."""
    if name not in payload or payload[name] is None:
        return default
    if not isinstance(payload[name], str):
        _bad(name, "must be a string")
    return payload[name]


# --------------------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------------------

def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def req_int(payload, name, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    return _as_int(payload[name], name, minimum, maximum)


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        return default
    return _as_int(payload[name], name, minimum, maximum)


def req_bp(payload, name, maximum=10000):
    return req_int(payload, name, 0, maximum)


def opt_bp(payload, name, default=None, maximum=10000):
    return opt_int(payload, name, default, 0, maximum)


def req_bool(payload, name):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    if not isinstance(payload[name], bool):
        _bad(name, "must be a boolean")
    return payload[name]


def opt_bool(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    if not isinstance(payload[name], bool):
        _bad(name, "must be a boolean")
    return payload[name]


# --------------------------------------------------------------------------------------
# enums, instants, dates, id lists
# --------------------------------------------------------------------------------------

def req_enum(payload, name, values):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    value = payload[name]
    if not isinstance(value, str) or value not in values:
        _bad(name, "must be one of %s" % ", ".join(values))
    return value


def opt_enum(payload, name, values, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in values:
        _bad(name, "must be one of %s" % ", ".join(values))
    return value


def req_instant(payload, name):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    parsed = db.parse_instant(payload[name])
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC instant")
    return parsed


def opt_instant(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    parsed = db.parse_instant(payload[name])
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC instant")
    return parsed


def req_date(payload, name):
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    raw = payload[name]
    if not isinstance(raw, str) or db.parse_date(raw) is None:
        _bad(name, "must be a YYYY-MM-DD date")
    return raw


def req_id_list(payload, name):
    """PRD section 3.5: non-empty, free of duplicates, every entry a string id."""
    if name not in payload or payload[name] is None:
        _bad(name, "is required")
    value = payload[name]
    if not isinstance(value, list) or not value:
        _bad(name, "must be a non-empty array")
    seen = set()
    for entry in value:
        if not isinstance(entry, str) or not entry:
            _bad(name, "must contain only non-empty string ids")
        if entry in seen:
            _bad(name, "must not contain duplicate entries")
        seen.add(entry)
    return list(value)


def enum_filter(name, values):
    """A query-parameter enum filter; an unknown value is a malformed request."""
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    if raw not in values:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s."
             % (name, ", ".join(values)))
    return raw


def instant_filter(name):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    parsed = db.parse_instant(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an ISO 8601 instant." % name)
    return parsed


def str_filter(name):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    return raw


# --------------------------------------------------------------------------------------
# existence
# --------------------------------------------------------------------------------------

def find(collection, identifier, error_id):
    if not isinstance(identifier, str):
        fail(error_id)
    record = collection.get(identifier)
    if record is None:
        fail(error_id)
    return record


def find_league(identifier):
    return find(db.store.leagues, identifier, "ERR_LEAGUE_NOT_FOUND")


def find_organization(identifier):
    return find(db.store.organizations, identifier, "ERR_ORGANIZATION_NOT_FOUND")


def find_player(identifier):
    return find(db.store.players, identifier, "ERR_PLAYER_NOT_FOUND")


def find_offer(identifier):
    return find(db.store.offers, identifier, "ERR_OFFER_NOT_FOUND")


def find_contract(identifier):
    return find(db.store.contracts, identifier, "ERR_CONTRACT_NOT_FOUND")


def find_team_house(identifier):
    return find(db.store.team_houses, identifier, "ERR_TEAM_HOUSE_NOT_FOUND")


def find_block(identifier):
    return find(db.store.practice_blocks, identifier, "ERR_PRACTICE_BLOCK_NOT_FOUND")


def find_deal(identifier):
    return find(db.store.deals, identifier, "ERR_DEAL_NOT_FOUND")


def find_assignment(identifier):
    return find(db.store.assignments, identifier, "ERR_DELIVERABLE_NOT_FOUND")


def find_distribution(identifier):
    return find(db.store.distributions, identifier, "ERR_DISTRIBUTION_NOT_FOUND")


def find_roster_move(identifier):
    return find(db.store.roster_moves, identifier, "ERR_ROSTER_MOVE_NOT_FOUND")
