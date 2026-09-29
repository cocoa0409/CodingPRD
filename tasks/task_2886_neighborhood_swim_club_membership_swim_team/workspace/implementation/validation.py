"""Payload shape, enumeration, paired-time-range and pagination validation.

Rejection ladder bands 5-8 (PRD §2.9), evaluated strictly in that order:
  5. Payload shape   -> ERR_VALIDATION (422)
  6. Enumerations    -> ERR_INVALID_ENUM (422)
  7. Paired ranges   -> ERR_INVALID_TIME_RANGE (422)
  8. Pagination      -> ERR_PAGINATION_INVALID (422)

Because band 5 must be exhausted before band 6 begins, a field spec is walked
twice: once for shape, once for enum membership.
"""
import clock
from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from errors import fail

MISSING = object()


def f(name, kind, required=True, default=None, enum=None, minimum=0, maximum=None):
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "default": default,
        "enum": enum,
        "min": minimum,
        "max": maximum,
    }


def body_of(request):
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        fail("ERR_VALIDATION", "The request body must be a JSON object.")
    return raw


def _shape_one(spec, raw):
    name = spec["name"]
    kind = spec["kind"]
    if name not in raw or raw[name] is None:
        if spec["required"]:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return MISSING
    value = raw[name]

    if kind in ("string", "enum", "date", "instant"):
        if not isinstance(value, str):
            fail("ERR_VALIDATION", "Field '%s' must be a string." % name)
        if not value.strip():
            fail("ERR_VALIDATION", "Field '%s' must be non-empty." % name)
        if kind == "date":
            if clock.parse_date(value) is None:
                fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date." % name)
            return value.strip()
        if kind == "instant":
            parsed = clock.parse_instant(value)
            if parsed is None:
                fail(
                    "ERR_VALIDATION",
                    "Field '%s' must be an ISO-8601 UTC instant." % name,
                )
            return clock.iso(parsed)
        return value

    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_VALIDATION", "Field '%s' must be an integer." % name)
        if spec["min"] is not None and value < spec["min"]:
            fail(
                "ERR_VALIDATION",
                "Field '%s' must be at least %d." % (name, spec["min"]),
            )
        if spec["max"] is not None and value > spec["max"]:
            fail(
                "ERR_VALIDATION",
                "Field '%s' must be at most %d." % (name, spec["max"]),
            )
        return value

    if kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_VALIDATION", "Field '%s' must be a boolean." % name)
        return value

    raise AssertionError("unknown field kind %r" % kind)


def validate(raw, specs):
    """Run band 5 over every field, then band 6 over every enum field."""
    values = {}
    for spec in specs:
        parsed = _shape_one(spec, raw)
        values[spec["name"]] = parsed
    # band 6 - enumerations, only after every shape check has passed
    for spec in specs:
        if spec["enum"] is None:
            continue
        value = values[spec["name"]]
        if value is MISSING:
            continue
        if value not in spec["enum"]:
            fail(
                "ERR_INVALID_ENUM",
                "Field '%s' must be one of %s." % (spec["name"], ", ".join(spec["enum"])),
            )
    # apply declared defaults for omitted optional fields
    for spec in specs:
        if values[spec["name"]] is MISSING:
            values[spec["name"]] = spec["default"]
    return values


def present(values, name):
    return values.get(name) is not None


def require_range(start_value, end_value, kind="instant"):
    """Band 7: a start is strictly earlier than its paired end."""
    if start_value is None or end_value is None:
        return
    if kind == "instant":
        a = clock.parse_instant(start_value)
        b = clock.parse_instant(end_value)
    else:
        a = clock.parse_date(start_value)
        b = clock.parse_date(end_value)
    if a is None or b is None:
        return
    if not a < b:
        fail("ERR_INVALID_TIME_RANGE", "The start must be strictly earlier than the end.")


def pagination(request):
    """Band 8: limit is an integer in [1, 100], offset an integer >= 0."""
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        limit = _as_int(raw)
        if limit is None or limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail(
                "ERR_PAGINATION_INVALID",
                "limit must be an integer between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )
    if "offset" in args:
        raw = args.get("offset")
        offset = _as_int(raw)
        if offset is None or offset < 0:
            fail("ERR_PAGINATION_INVALID", "offset must be an integer of at least 0.")
    return limit, offset


def _as_int(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text[0] in "+-":
        digits = text[1:]
    else:
        digits = text
    if not digits.isdigit():
        return None
    return int(text)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ------------------------------------------------------------------- filtering
def filter_value(request, name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def filter_bool(request, name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return "__nomatch__"


def apply_filters(rows, request, string_fields=(), bool_fields=()):
    """Filters narrow the matched set before pagination and combine
    conjunctively (PRD §2.3)."""
    out = rows
    for field in string_fields:
        wanted = filter_value(request, field)
        if wanted is None:
            continue
        out = [r for r in out if r.get(field) == wanted]
    for field in bool_fields:
        wanted = filter_bool(request, field)
        if wanted is None:
            continue
        if wanted == "__nomatch__":
            return []
        out = [r for r in out if bool(r.get(field)) is wanted]
    return out


def int_filter(rows, request, field):
    raw = request.args.get(field)
    if raw is None:
        return rows
    value = _as_int(raw)
    if value is None:
        return []
    return [r for r in rows if r.get(field) == value]
