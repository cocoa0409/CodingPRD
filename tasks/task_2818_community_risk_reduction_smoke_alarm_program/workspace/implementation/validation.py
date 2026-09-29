"""Request-schema validation (ladder step 4) and pagination (PRD 2.3).

Every failure here raises ERR_INVALID_REQUEST (HTTP 400).
"""

from flask import request

import util
from errors import ApiError

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """Parsed JSON object body.  An absent body behaves as an empty object so
    that the missing-required-field branch reports the field, not the body."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def reject_unexpected_version(body, allowed=None):
    """PRD 2.10: only two endpoints take an expected-version field; supplying
    one anywhere else is a schema failure."""
    for key in body.keys():
        if key.startswith("expected_") and key.endswith("_version"):
            if allowed is None or key != allowed:
                bad("Field %s is not accepted by this endpoint." % key)


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, non_empty=True):
    if not _present(body, key):
        bad("Field %s is required." % key)
    value = body[key]
    if not isinstance(value, str):
        bad("Field %s must be a string." % key)
    if non_empty and value.strip() == "":
        bad("Field %s must not be empty." % key)
    return value


def opt_str(body, key, default=None, non_empty=False):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        bad("Field %s must be a string." % key)
    if non_empty and value.strip() == "":
        bad("Field %s must not be empty." % key)
    return value


def _check_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %s must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field %s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field %s must not exceed %s." % (key, maximum))
    return value


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        bad("Field %s is required." % key)
    return _check_int(body[key], key, minimum, maximum)


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        return default
    return _check_int(body[key], key, minimum, maximum)


def _check_num(value, key, minimum, maximum, exclusive_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field %s must be a number." % key)
    dec = util.to_decimal(value)
    if minimum is not None:
        if exclusive_min and dec <= util.to_decimal(minimum):
            bad("Field %s must be greater than %s." % (key, minimum))
        if not exclusive_min and dec < util.to_decimal(minimum):
            bad("Field %s must be at least %s." % (key, minimum))
    if maximum is not None and dec > util.to_decimal(maximum):
        bad("Field %s must not exceed %s." % (key, maximum))
    return dec


def req_num(body, key, minimum=None, maximum=None, exclusive_min=False):
    if not _present(body, key):
        bad("Field %s is required." % key)
    return _check_num(body[key], key, minimum, maximum, exclusive_min)


def opt_num(body, key, default=None, minimum=None, maximum=None, exclusive_min=False):
    if not _present(body, key):
        return default
    return _check_num(body[key], key, minimum, maximum, exclusive_min)


def req_bool(body, key):
    if not _present(body, key):
        bad("Field %s is required." % key)
    if not isinstance(body[key], bool):
        bad("Field %s must be a boolean." % key)
    return body[key]


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    if not isinstance(body[key], bool):
        bad("Field %s must be a boolean." % key)
    return body[key]


def req_enum(body, key, members):
    value = req_str(body, key)
    if value not in members:
        bad("Field %s must be one of %s." % (key, ", ".join(members)))
    return value


def opt_enum(body, key, members, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        bad("Field %s must be a string." % key)
    if value not in members:
        bad("Field %s must be one of %s." % (key, ", ".join(members)))
    return value


def req_str_list(body, key, members=None, non_empty=True):
    if not _present(body, key):
        bad("Field %s is required." % key)
    value = body[key]
    if not isinstance(value, list):
        bad("Field %s must be an array." % key)
    if non_empty and len(value) == 0:
        bad("Field %s must not be empty." % key)
    for item in value:
        if not isinstance(item, str):
            bad("Field %s must contain only strings." % key)
        if members is not None and item not in members:
            bad("Field %s contains an unknown member %s." % (key, item))
    return value


def opt_str_list(body, key, members=None, default=None):
    if not _present(body, key):
        return default
    return req_str_list(body, key, members=members, non_empty=False)


def req_date(body, key):
    raw = req_str(body, key)
    parsed = util.parse_date(raw)
    if parsed is None:
        bad("Field %s must be a YYYY-MM-DD date." % key)
    return parsed


def opt_date(body, key, default=None):
    if not _present(body, key):
        return default
    return req_date(body, key)


def req_instant(body, key):
    raw = req_str(body, key)
    parsed = util.parse_instant(raw)
    if parsed is None:
        bad("Field %s must be an ISO 8601 UTC instant." % key)
    return parsed


def opt_instant(body, key, default=None):
    if not _present(body, key):
        return default
    return req_instant(body, key)


def req_int_map(body, key, minimum=None):
    if not _present(body, key):
        bad("Field %s is required." % key)
    value = body[key]
    if not isinstance(value, dict):
        bad("Field %s must be an object." % key)
    for name, amount in value.items():
        if isinstance(amount, bool) or not isinstance(amount, int):
            bad("Field %s must map every key to an integer." % key)
        if minimum is not None and amount < minimum:
            bad("Field %s must map every key to at least %s." % (key, minimum))
    return dict(value)


def pagination():
    """limit/offset with the PRD 2.3 defaults and bounds."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int(raw_limit, "limit")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if raw_offset is not None:
        offset = _query_int(raw_offset, "offset")
        if offset < PAGE_OFFSET_DEFAULT:
            bad("offset must not be negative.")
    return limit, offset


def _query_int(raw, name):
    text = raw.strip()
    if text == "":
        bad("%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        bad("%s must be an integer." % name)
    return -int(digits) if negative else int(digits)


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


def filter_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("%s must be a boolean." % name)
