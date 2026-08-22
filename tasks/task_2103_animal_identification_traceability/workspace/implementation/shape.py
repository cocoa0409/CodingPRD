"""Priority-3 per-field request-shape validation (PRD 2.5 band 3).

Only per-field checks live here: presence, scalar type, enum membership,
format regex and numeric bound. Comparisons *between* two fields are
deliberately not performed in this band.
"""
import re

from flask import request

from errors import invalid_request
from timeutil import parse_date, parse_instant

PIN_RE = re.compile(r"^[0-9A-Z]{7}$")
SUPPLIER_CODE_RE = re.compile(r"^[A-Z0-9]{4}$")
AIN_RE = re.compile(r"^[0-9]{15}$")
AID_PREFIX_RE = re.compile(r"^[0-9]{3}$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

SERIAL_MIN = 100000000000
SERIAL_MAX = 999999999999


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


def _present(b, name):
    return name in b and b[name] is not None


def _missing(name, required):
    if required:
        raise invalid_request("Field '%s' is required" % name)
    return None


def s_str(b, name, required=True, pattern=None, contains=None):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    if not isinstance(v, str):
        raise invalid_request("Field '%s' must be a string" % name)
    if pattern is not None and not pattern.match(v):
        raise invalid_request("Field '%s' has an invalid format" % name)
    if contains is not None and contains not in v:
        raise invalid_request("Field '%s' must contain '%s'" % (name, contains))
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


def s_date(b, name, required=True):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    try:
        return parse_date(v)
    except Exception:
        raise invalid_request("Field '%s' must be a YYYY-MM-DD date" % name)


def s_instant(b, name, required=True):
    if not _present(b, name):
        return _missing(name, required)
    v = b[name]
    try:
        return parse_instant(v)
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


def q_bool(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v.strip().lower() in ("true", "1", "yes")
