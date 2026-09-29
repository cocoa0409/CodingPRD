"""Priority-4 shape validation helpers. Every failure is ERR_INVALID_REQUEST (422)."""

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import db
from errors import ApiError

_MISSING = object()


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def present(body, field):
    return field in body and body[field] is not None


def _fetch(body, field, required):
    if field not in body or body[field] is None:
        if required:
            bad(field, "is required")
        return _MISSING
    return body[field]


def req_str(body, field, max_len=None):
    value = _fetch(body, field, True)
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-empty string")
    if max_len is not None and len(value) > max_len:
        bad(field, "is too long")
    return value


def opt_str(body, field, default=None, max_len=None):
    value = _fetch(body, field, False)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-empty string")
    if max_len is not None and len(value) > max_len:
        bad(field, "is too long")
    return value


def req_id(body, field):
    value = _fetch(body, field, True)
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-empty identifier string")
    return value


def opt_id(body, field):
    value = _fetch(body, field, False)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-empty identifier string")
    return value


def _check_int(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        bad(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be at most %d" % maximum)
    return value


def req_int(body, field, minimum=None, maximum=None):
    value = _fetch(body, field, True)
    return _check_int(field, value, minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    value = _fetch(body, field, False)
    if value is _MISSING:
        return default
    return _check_int(field, value, minimum, maximum)


def req_bool(body, field):
    value = _fetch(body, field, True)
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def opt_bool(body, field, default=None):
    value = _fetch(body, field, False)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def req_enum(body, field, members):
    value = _fetch(body, field, True)
    if not isinstance(value, str) or value not in members:
        bad(field, "must be one of %s" % ", ".join(members))
    return value


def opt_enum(body, field, members, default=None):
    value = _fetch(body, field, False)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in members:
        bad(field, "must be one of %s" % ", ".join(members))
    return value


def req_enum_list(body, field, members):
    value = _fetch(body, field, True)
    if not isinstance(value, list) or len(value) == 0:
        bad(field, "must be a non-empty array")
    out = []
    for item in value:
        if not isinstance(item, str) or item not in members:
            bad(field, "must contain only %s" % ", ".join(members))
        if item not in out:
            out.append(item)
    return out


def req_instant(body, field):
    value = _fetch(body, field, True)
    if not isinstance(value, str):
        bad(field, "must be an ISO-8601 UTC instant")
    parsed = db.parse_instant(value)
    if parsed is None:
        bad(field, "must be an ISO-8601 UTC instant")
    return parsed


def opt_instant(body, field, default=None):
    value = _fetch(body, field, False)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad(field, "must be an ISO-8601 UTC instant")
    parsed = db.parse_instant(value)
    if parsed is None:
        bad(field, "must be an ISO-8601 UTC instant")
    return parsed


def _to_decimal(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad(field, "must be a decimal number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad(field, "must be a decimal number")


def _check_pct(field, value, minimum, maximum, places):
    dec = _to_decimal(field, value)
    if minimum is not None and dec < minimum:
        bad(field, "must be at least %s" % minimum)
    if maximum is not None and dec > maximum:
        bad(field, "must be at most %s" % maximum)
    return dec.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def req_pct(body, field, minimum=None, maximum=None, places=2):
    value = _fetch(body, field, True)
    return _check_pct(field, value, minimum, maximum, places)


def opt_pct(body, field, default=None, minimum=None, maximum=None, places=2):
    value = _fetch(body, field, False)
    if value is _MISSING:
        return default
    return _check_pct(field, value, minimum, maximum, places)


_CODE_RE = re.compile(r"^[A-Z0-9]{3,8}$")


def req_code(body, field):
    value = req_str(body, field)
    if not _CODE_RE.match(value):
        bad(field, "must be three to eight uppercase alphanumeric characters")
    return value


def window(start, end, start_field="start", end_field="end"):
    """A window whose start instant is after its end instant fails shape validation."""
    if start is not None and end is not None and start > end:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must not be later than '%s'." % (start_field, end_field),
        )
