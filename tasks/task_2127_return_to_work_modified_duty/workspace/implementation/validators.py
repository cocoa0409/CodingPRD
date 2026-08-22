"""Priority-3 request shape validation (PRD 2.6)."""
from flask import request

from errors import fail
from util import parse_date

_MISSING = object()


def bad(msg):
    fail("ERR_INVALID_REQUEST", msg)


def body_of(req=None):
    req = req or request
    raw = req.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        bad("Request body must be a JSON object.")
    return raw


def _present(body, name):
    return name in body and body[name] is not None


def req_field(body, name):
    if not _present(body, name):
        bad("Field '%s' is required." % name)
    return body[name]


def str_field(body, name, required=True, min_len=None, max_len=None,
              allow_empty=False, default=None):
    if not _present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_empty and value == "":
        bad("Field '%s' must not be empty." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % name)
    return value


def enum_field(body, name, choices, required=True, default=None):
    if not _present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in choices:
        bad("Field '%s' must be one of %s." % (name, ", ".join(choices)))
    return value


def int_field(body, name, required=True, minimum=None, maximum=None,
              default=None):
    if not _present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        bad("Field '%s' is above its maximum." % name)
    return value


def num_field(body, name, required=True, gt=None, ge=None, lt=None, le=None,
              default=None):
    if not _present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    if gt is not None and not value > gt:
        bad("Field '%s' must be greater than %s." % (name, gt))
    if ge is not None and value < ge:
        bad("Field '%s' must be at least %s." % (name, ge))
    if lt is not None and not value < lt:
        bad("Field '%s' must be less than %s." % (name, lt))
    if le is not None and value > le:
        bad("Field '%s' must be at most %s." % (name, le))
    return value


def bool_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def date_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % name)
    return parsed


def id_list_field(body, name, default=None):
    if not _present(body, name):
        return list(default or [])
    value = body[name]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        bad("Field '%s' must be an array of strings." % name)
    return value


def not_inverted(first, second, first_name, second_name):
    if second < first:
        bad("'%s' must be on or after '%s'." % (second_name, first_name))


# --------------------------------------------------------------------------
# Query string helpers
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("'offset' must be an integer.")
        if offset < 0:
            bad("'offset' must not be negative.")
    return limit, offset


def query_enum(name, choices):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in choices:
        bad("Query parameter '%s' must be one of %s."
            % (name, ", ".join(choices)))
    return value


def query_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_date(name, default=None):
    if name not in request.args:
        return default
    parsed = parse_date(request.args.get(name))
    if parsed is None:
        bad("Query parameter '%s' must be a YYYY-MM-DD calendar date." % name)
    return parsed
