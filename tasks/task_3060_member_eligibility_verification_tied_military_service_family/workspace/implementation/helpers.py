import re
import secrets
from datetime import date, datetime, timezone

from errors import err
import store

VALID_ROLES = {
    "EligibilityApplicant", "VerificationOfficer", "Member",
    "BenefitsOfficer", "ProductAdministrator", "PlatformAdmin",
}
ENTITY_BACKED = {"Member"}

_MONTH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)


def gen_id():
    import uuid
    return str(uuid.uuid4())


def req_id():
    return "req_" + secrets.token_hex(12)


def _iso_to_date(v):
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    s = str(v)
    if not _DATETIME_RE.match(s):
        raise err("ERR_INVALID_REQUEST", 400, "malformed ISO 8601 date")
    s2 = s.replace("Z", "+00:00")
    if "T" in s2 or " " in s2:
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    y, m, d = int(s2[0:4]), int(s2[5:7]), int(s2[8:10])
    return date(y, m, d)


def parse_date_field(v):
    return _iso_to_date(v)


def is_plain_date(v):
    return isinstance(v, str) and _MONTH_RE.match(v) is not None


def require_field(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % name)
    return body[name]


def optional_field(body, name, default=None):
    if not isinstance(body, dict):
        return default
    v = body.get(name, default)
    return default if v is None else v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", 400, "invalid enum value for %s" % name)
    return v


def optional_enum(body, name, allowed, default=None):
    v = optional_field(body, name, default)
    if v is None:
        return None
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", 400, "invalid enum value for %s" % name)
    return v


def require_date(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not _MONTH_RE.match(v):
        raise err("ERR_INVALID_REQUEST", 400, "invalid date for %s" % name)
    return _iso_to_date(v)


def optional_date(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str) or not _MONTH_RE.match(v):
        raise err("ERR_INVALID_REQUEST", 400, "invalid date for %s" % name)
    return _iso_to_date(v)


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, "invalid boolean for %s" % name)
    return v


def optional_bool(body, name, default=False):
    v = optional_field(body, name, default)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, "invalid boolean for %s" % name)
    return v


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, "invalid integer for %s" % name)
    return v


def optional_int(body, name, default=None):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, "invalid integer for %s" % name)
    return v


def date_to_str(d):
    return d.isoformat()


def d_from_str(s):
    return _iso_to_date(s)


def touch(row):
    row["updated_at"] = store.now_iso_ms()
    row["version"] += 1


def new_row():
    ts = store.now_iso_ms()
    return {"id": gen_id(), "created_at": ts, "updated_at": ts, "version": 1}


def whole_months_between(start_d, end_d):
    """Whole calendar months from start_d to end_d (inclusive-ish, conservative).

    Count = number of full month boundaries crossed going from start to end.
    Uses: full month elapsed when end_d >= same-day-of-month in later month.
    """
    if end_d < start_d:
        return 0
    years = end_d.year - start_d.year
    months = years * 12 + (end_d.month - start_d.month)
    if end_d.day < start_d.day:
        months -= 1
    if months < 0:
        months = 0
    return months
