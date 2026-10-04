"""Request-shape validation helpers (gauntlet tier 5) plus pagination parsing
and half-open window utilities. Every failure raises ERR_INVALID_REQUEST (400)
unless a more specific helper is used."""

import json

from flask import request

from errors import invalid_request
from store import parse_dt


def get_payload():
    """Return the request JSON object; {} when no body was sent. A malformed
    or non-object body is a shape error."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        try:
            data = json.loads(request.data)
        except (ValueError, TypeError):
            raise invalid_request("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def _present(payload, field):
    return field in payload and payload[field] is not None


def req_str(payload, field):
    if not _present(payload, field):
        raise invalid_request("Missing required field: %s" % field)
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise invalid_request("Field %s must be a non-empty string" % field)
    return value


def opt_str(payload, field):
    if not _present(payload, field):
        return None
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise invalid_request("Field %s must be a non-empty string" % field)
    return value


def req_int(payload, field):
    if not _present(payload, field):
        raise invalid_request("Missing required field: %s" % field)
    return _as_int(payload[field], field)


def opt_int(payload, field, default=None):
    if not _present(payload, field):
        return default
    return _as_int(payload[field], field)


def _as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field %s must be an integer" % field)
    return value


def req_number(payload, field):
    if not _present(payload, field):
        raise invalid_request("Missing required field: %s" % field)
    return _as_number(payload[field], field)


def _as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("Field %s must be a number" % field)
    return value


def req_enum(payload, field, allowed):
    value = req_str(payload, field)
    if value not in allowed:
        raise invalid_request(
            "Field %s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return value


def req_dt(payload, field):
    raw = req_str(payload, field)
    dt = parse_dt(raw)
    if dt is None:
        raise invalid_request("Field %s must be an ISO 8601 timestamp" % field)
    return dt


def req_list(payload, field):
    if not _present(payload, field):
        raise invalid_request("Missing required field: %s" % field)
    value = payload[field]
    if not isinstance(value, list):
        raise invalid_request("Field %s must be an array" % field)
    return value


def opt_list(payload, field, default=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, list):
        raise invalid_request("Field %s must be an array" % field)
    return value


def check_half_open_window(start, end, field_from, field_to):
    """Every window requires start strictly before end (PRD §2.8)."""
    if not start < end:
        raise invalid_request(
            "Field %s must be strictly earlier than %s" % (field_from, field_to))


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test; adjacency does not overlap."""
    return a_start < b_end and b_start < a_end


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0.
    Out-of-range or non-integer values are a shape error (400)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < 1 or limit > 100:
            raise invalid_request("Parameter limit must be between 1 and 100")
    if raw_offset is not None:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < 0:
            raise invalid_request("Parameter offset must be >= 0")
    return limit, offset


def _parse_int_param(raw, name):
    try:
        value = int(raw, 10)
    except (ValueError, TypeError):
        raise invalid_request("Parameter %s must be an integer" % name)
    return value


def apply_filters(rows, args, allowed_fields):
    """Exact-match query filtering over the allowed filter fields."""
    selected = list(rows)
    for field in allowed_fields:
        if field in args:
            wanted = args.get(field)
            selected = [r for r in selected if r.get(field) is not None
                        and str(r.get(field)) == wanted]
    return selected
