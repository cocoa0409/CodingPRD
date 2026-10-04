"""Request body well-formedness validation (pipeline priority 0)."""
from flask import request

from errors import err, ERR_INVALID_REQUEST
import store


def get_body():
    """Return the JSON body as a dict; {} for empty bodies; 400 otherwise."""
    raw = request.get_data()
    if raw is None or raw == b"" or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "request body must be valid JSON")
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def check_unknown_fields(body, allowed):
    extra = set(body.keys()) - set(allowed)
    if extra:
        raise err(
            ERR_INVALID_REQUEST,
            "unknown field(s): %s" % ", ".join(sorted(extra)),
        )


def require_fields(body, required):
    missing = [f for f in required if f not in body or body[f] is None]
    if missing:
        raise err(
            ERR_INVALID_REQUEST,
            "missing required field(s): %s" % ", ".join(sorted(missing)),
        )


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "%s must be a non-empty string" % name)
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer" % name)
    return v


def req_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "%s must be a number" % name)
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return v


def req_enum(body, name, values):
    v = body.get(name)
    if not isinstance(v, str) or v not in values:
        raise err(
            ERR_INVALID_REQUEST,
            "%s must be one of %s" % (name, ", ".join(values)),
        )
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "%s must be a string" % name)
    return v


def req_date(body, name):
    v = body.get(name)
    d = store.parse_date(v)
    if d is None:
        raise err(ERR_INVALID_REQUEST, "%s must be a valid YYYY-MM-DD date" % name)
    return d


def req_datetime(body, name):
    v = body.get(name)
    dt = store.parse_datetime(v)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "%s must be a valid ISO 8601 datetime" % name)
    return dt
