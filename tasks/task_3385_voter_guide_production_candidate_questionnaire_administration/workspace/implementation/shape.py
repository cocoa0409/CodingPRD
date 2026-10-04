"""Priority-3 request-body shape validation (PRD 2.7 band 3).

Per-field checks: presence, scalar type, enum membership, format, numeric
bounds, plus the no-undeclared-fields rule. Cross-field comparisons live in
the route handlers at their ladder position.
"""
from flask import request

from errors import invalid_request
from timeutil import parse_date, parse_instant


def body():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Tolerate a JSON payload sent without an application/json content type.
        data = request.get_json(force=True, silent=True)
    if data is None:
        raise invalid_request("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def no_extra(b, allowed):
    extras = [k for k in b if k not in allowed]
    if extras:
        raise invalid_request("Undeclared field(s): %s" % ", ".join(sorted(extras)))


def _present(b, name):
    return name in b and b[name] is not None


def _missing(name, required):
    if required:
        raise invalid_request("Field '%s' is required" % name)
    return None


def s_str(b, name, required=True, non_empty=False):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    if not isinstance(v, str):
        raise invalid_request("Field '%s' must be a string" % name)
    if non_empty and v == "":
        raise invalid_request("Field '%s' must be non-empty" % name)
    return v


def s_int(b, name, required=True, minimum=None, maximum=None):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("Field '%s' must be an integer" % name)
    if minimum is not None and v < minimum:
        raise invalid_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise invalid_request("Field '%s' must be <= %s" % (name, maximum))
    return v


def s_bool(b, name, required=True):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    if not isinstance(v, bool):
        raise invalid_request("Field '%s' must be a boolean" % name)
    return v


def s_enum(b, name, members, required=True):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    if not isinstance(v, str) or v not in members:
        raise invalid_request("Field '%s' must be one of %s" % (name, ", ".join(members)))
    return v


def s_list(b, name, required=True, non_empty=False):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    if not isinstance(v, list):
        raise invalid_request("Field '%s' must be an array" % name)
    if non_empty and len(v) == 0:
        raise invalid_request("Field '%s' must be non-empty" % name)
    return v


def s_enum_list(b, name, members, required=True, non_empty=False):
    v = s_list(b, name, required=required, non_empty=non_empty)
    if v is None:
        return None
    for item in v:
        if not isinstance(item, str) or item not in members:
            raise invalid_request(
                "Field '%s' entries must be one of %s" % (name, ", ".join(members)))
    return v


def s_date(b, name, required=True):
    if not _present(b, name):
        return _missing(name, required)
    try:
        return parse_date(b[name])
    except Exception:
        raise invalid_request("Field '%s' must be a YYYY-MM-DD date" % name)


def s_instant(b, name, required=True):
    if not _present(b, name):
        return _missing(name, required)
    try:
        return parse_instant(b[name])
    except Exception:
        raise invalid_request("Field '%s' must be an ISO 8601 timestamp" % name)


# --- query string ---------------------------------------------------------
def pagination_params():
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None and raw != "":
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("Query parameter 'limit' must be between 1 and 100")
    raw = request.args.get("offset")
    if raw is not None and raw != "":
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise invalid_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def q(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
