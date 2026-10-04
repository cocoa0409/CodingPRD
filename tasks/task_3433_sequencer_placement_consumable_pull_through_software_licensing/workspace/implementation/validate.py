"""Request body parsing and field validators.

All shape failures raise ERR_INVALID_REQUEST (400). Reference resolution
(404) is intentionally handled in the route modules so it can be sequenced
before shape validation per PRD 2.9 (tier 6 before tier 7).
"""

from flask import request

from errors import ApiError, invalid_request, not_found
from timeutil import parse_dt
from store import DB


def get_body():
    """Tolerant JSON object body; empty body parses as {}."""
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def _missing(name):
    raise invalid_request("Missing required field: %s" % name)


def _bad(name, want):
    raise invalid_request("Field %s must be %s" % (name, want))


def f_str(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, str) or v == "":
        _bad(name, "a non-empty string")
    return v


def f_int(body, name, required=True, min_v=None):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "an integer")
    if min_v is not None and v < min_v:
        _bad(name, "an integer >= %d" % min_v)
    return v


def f_num(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "a number")
    return v


def f_bool(body, name, required=False, default=None):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return default
    if not isinstance(v, bool):
        _bad(name, "a boolean")
    return v


def f_enum(body, name, members, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, str) or v not in members:
        _bad(name, "one of %s" % "|".join(members))
    return v


def f_list(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, list):
        _bad(name, "an array")
    return v


def f_dt(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    dt = parse_dt(v)
    if dt is None:
        _bad(name, "an ISO 8601 timestamp")
    return dt


def enum_list(body, name, members, required=True):
    """Validate a list whose members must all be in the enum set."""
    values = f_list(body, name, required=required)
    if values is None:
        return None
    for item in values:
        if not isinstance(item, str) or item not in members:
            _bad(name, "an array with members of %s" % "|".join(members))
    return values


def resolve_ref(body, name, store_key):
    """Body-reference resolution (404) for a well-typed present value.

    Per PRD 2.9 tier 6, an unresolvable reference fails before shape checks.
    Wrong-typed or missing values defer to shape validation (400).
    """
    v = body.get(name)
    if isinstance(v, str) and v and v not in DB[store_key]:
        raise not_found("Reference %s does not resolve" % name)


def kit_by_code(kit_code):
    for kit in DB["kits"].values():
        if kit["kit_code"] == kit_code:
            return kit
    return None


def resolve_line_kit_codes(lines):
    """kit_code members of order/forecast lines are body references (404)."""
    if not isinstance(lines, list):
        return
    for ln in lines:
        if isinstance(ln, dict):
            kc = ln.get("kit_code")
            if isinstance(kc, str) and kc and kit_by_code(kc) is None:
                raise not_found("kit_code %s does not resolve" % kc)


def account_credit_hold(account):
    """credit_hold is computed: true iff the account has a BREACHED program."""
    return any(
        p["account_id"] == account["id"] and p["program_state"] == "BREACHED"
        for p in DB["programs"].values()
    )


def require(condition, error_id, status, message):
    if not condition:
        raise ApiError(error_id, status, message)
