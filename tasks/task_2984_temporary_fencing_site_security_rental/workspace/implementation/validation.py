"""Rung 3 of the ladder: request-shape integrity (PRD 2.7), plus the shared
ISO-8601 instant helpers every temporal rule reads.

Every failure raised from this module is ERR_VALIDATION / HTTP 400.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from errors import ApiError, fail

INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")


def iso_ms(dt):
    """Render an instant as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_instant(value):
    """PRD 2.6: every instant crossing the boundary is ISO 8601 UTC ending in Z."""
    if not isinstance(value, str) or not INSTANT_RE.match(value):
        fail("ERR_VALIDATION", "Instant must be an ISO 8601 UTC timestamp ending in Z.")
    body = value[:-1]
    try:
        if "." in body:
            head, frac = body.split(".", 1)
            frac = (frac + "000000")[:6]
            dt = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(
                microsecond=int(frac), tzinfo=timezone.utc)
        else:
            dt = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        fail("ERR_VALIDATION", "Instant is not a valid ISO 8601 UTC timestamp.")
    return dt


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


def plus_hours_decimal(dt, hours):
    """Advance an instant by a Decimal number of hours (exact on quarter hours)."""
    seconds = (Decimal(hours) * Decimal(3600)).to_integral_value()
    return dt + timedelta(seconds=int(seconds))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------

def require_object_body(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return raw


def check_body(raw, spec):
    """Validate a request body against a field spec.

    spec maps a field name to a dict:
      req      -> True when the field is mandatory
      type     -> int | number | string | bool | instant | array | object
      gt / ge / le  -> numeric bounds (ERR_VALIDATION when violated)
      enum     -> allowed members
      nullable -> explicit JSON null is accepted
      forbidden-> supplying the key at all is ERR_VALIDATION
    Returns a dict of the supplied values, instants parsed into datetimes.
    Absent optional fields are simply missing from the result.
    """
    body = require_object_body(raw)
    for key in body:
        if key not in spec:
            fail("ERR_VALIDATION", "Unknown field '%s'." % key)
    out = {}
    for name, rule in spec.items():
        if rule.get("forbidden"):
            if name in body:
                fail("ERR_VALIDATION", "Field '%s' may not be supplied here." % name)
            continue
        if name not in body:
            if rule.get("req"):
                fail("ERR_VALIDATION", "Missing required field '%s'." % name)
            continue
        value = body[name]
        if value is None:
            if rule.get("nullable"):
                out[name] = None
                continue
            fail("ERR_VALIDATION", "Field '%s' may not be null." % name)
        out[name] = check_value(name, value, rule)
    return out


def check_value(name, value, rule):
    kind = rule.get("type", "string")
    if kind == "int":
        if not is_int(value):
            fail("ERR_VALIDATION", "Field '%s' must be a JSON integer." % name)
    elif kind == "number":
        if not is_number(value):
            fail("ERR_VALIDATION", "Field '%s' must be a JSON number." % name)
    elif kind == "string":
        if not isinstance(value, str):
            fail("ERR_VALIDATION", "Field '%s' must be a JSON string." % name)
    elif kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_VALIDATION", "Field '%s' must be a JSON boolean." % name)
    elif kind == "instant":
        value = parse_instant(value)
    elif kind == "array":
        if not isinstance(value, list):
            fail("ERR_VALIDATION", "Field '%s' must be a JSON array." % name)
    elif kind == "object":
        if not isinstance(value, dict):
            fail("ERR_VALIDATION", "Field '%s' must be a JSON object." % name)
    if "enum" in rule and value not in rule["enum"]:
        fail("ERR_VALIDATION", "Field '%s' carries a value outside its declared members." % name)
    if kind in ("int", "number"):
        if "gt" in rule and not value > rule["gt"]:
            fail("ERR_VALIDATION", "Field '%s' must be greater than %s." % (name, rule["gt"]))
        if "ge" in rule and not value >= rule["ge"]:
            fail("ERR_VALIDATION", "Field '%s' must be at least %s." % (name, rule["ge"]))
        if "le" in rule and not value <= rule["le"]:
            fail("ERR_VALIDATION", "Field '%s' must be at most %s." % (name, rule["le"]))
    if kind == "string":
        if "min_len" in rule and len(value) < rule["min_len"]:
            fail("ERR_VALIDATION", "Field '%s' is shorter than %d characters." % (name, rule["min_len"]))
        if "max_len" in rule and len(value) > rule["max_len"]:
            fail("ERR_VALIDATION", "Field '%s' is longer than %d characters." % (name, rule["max_len"]))
        if "pattern" in rule and not re.match(rule["pattern"], value):
            fail("ERR_VALIDATION", "Field '%s' does not match its required character set." % name)
    return value


def check_object_list(name, rows, spec):
    """Validate an array of objects (addon_lines, unit_returns)."""
    out = []
    for entry in rows:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "Every entry of '%s' must be a JSON object." % name)
        for key in entry:
            if key not in spec:
                fail("ERR_VALIDATION", "Unknown field '%s' in '%s'." % (key, name))
        parsed = {}
        for field, rule in spec.items():
            if field not in entry:
                if rule.get("req"):
                    fail("ERR_VALIDATION", "Missing required field '%s' in '%s'." % (field, name))
                continue
            value = entry[field]
            if value is None:
                if rule.get("nullable"):
                    parsed[field] = None
                    continue
                fail("ERR_VALIDATION", "Field '%s' in '%s' may not be null." % (field, name))
            parsed[field] = check_value("%s[].%s" % (name, field), value, rule)
        out.append(parsed)
    return out


# ---------------------------------------------------------------------------
# Query string validation
# ---------------------------------------------------------------------------

def parse_pagination(args):
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _query_int("limit", raw)
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        offset = _query_int("offset", raw)
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be zero or greater.")
    return limit, offset


def _query_int(name, raw):
    if raw is None or raw == "":
        fail("ERR_VALIDATION", "%s must be an integer." % name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_VALIDATION", "%s must be an integer." % name)


def query_enum(args, name, members):
    if name not in args:
        return None
    value = args.get(name)
    if value not in members:
        fail("ERR_VALIDATION", "%s carries a value outside its declared members." % name)
    return value


def query_bool(args, name):
    if name not in args:
        return None
    value = args.get(name)
    if value == "true":
        return True
    if value == "false":
        return False
    fail("ERR_VALIDATION", "%s must be true or false." % name)


def query_string(args, name):
    if name not in args:
        return None
    return args.get(name)
