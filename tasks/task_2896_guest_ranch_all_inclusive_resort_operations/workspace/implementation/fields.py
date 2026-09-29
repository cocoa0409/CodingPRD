"""Request body shape checks: precedence rule 9 (required) and rule 10 (type/enum/range)."""

import datetime
import re

from flask import request

from errors import ApiError

UTC = datetime.timezone.utc
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def bad(name, why="is invalid"):
    raise ApiError("ERR_INVALID_FIELD_VALUE", "Field '%s' %s." % (name, why))


def require(data, *names):
    for name in names:
        if name not in data or data[name] is None:
            raise ApiError(
                "ERR_MISSING_REQUIRED_FIELD", "Field '%s' is required." % name
            )


def present(data, name):
    return name in data and data[name] is not None


def as_str(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    return value


def as_enum(data, name, allowed, default=None):
    value = as_str(data, name, None)
    if value is None:
        return default
    if value not in allowed:
        bad(name, "must be one of: %s" % ", ".join(allowed))
    return value


def as_bool(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def as_int(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def as_cents(data, name, default=None):
    """A _cents field: a non-negative integer number of cents."""
    return as_int(data, name, default=default, minimum=0)


def as_number(data, name, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        bad(name, "must be a finite number")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    if exclusive_min is not None and value <= exclusive_min:
        bad(name, "must be greater than %s" % exclusive_min)
    return value


def as_pct(data, name, default=None, exclusive_min=None):
    """A fraction between 0 and 1 inclusive (PRD 2.6)."""
    return as_number(
        data, name, default=default, minimum=0, maximum=1, exclusive_min=exclusive_min
    )


def parse_date(text):
    if not isinstance(text, str) or not DATE_RE.match(text):
        raise ValueError(text)
    return datetime.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def as_date(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        bad(name, "must be an ISO 8601 date (YYYY-MM-DD)")
    try:
        return parse_date(value)
    except ValueError:
        bad(name, "must be an ISO 8601 date (YYYY-MM-DD)")


def parse_instant(text):
    if not isinstance(text, str):
        raise ValueError(text)
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    value = datetime.datetime.fromisoformat(raw)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_instant(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        bad(name, "must be an ISO 8601 UTC instant")
    try:
        return parse_instant(value)
    except ValueError:
        bad(name, "must be an ISO 8601 UTC instant")


def as_list(data, name, default=None, min_len=None, max_len=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, list):
        bad(name, "must be an array")
    if min_len is not None and len(value) < min_len:
        bad(name, "must hold at least %d element(s)" % min_len)
    if max_len is not None and len(value) > max_len:
        bad(name, "must hold at most %d element(s)" % max_len)
    return value


def as_enum_list(data, name, allowed, default=None):
    value = as_list(data, name, None)
    if value is None:
        return default
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad(name, "may only contain: %s" % ", ".join(allowed))
    return value


def query_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_enum(name, allowed):
    raw = query_filter(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "Query parameter '%s' must be one of: %s" % (name, ", ".join(allowed)),
        )
    return raw
