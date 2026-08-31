"""Auth ladder, body validation, datetime and rounding helpers."""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError
from store import db, format_clock

ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")

ROLE_COLLECTION = {
    "Grazier": "graziers",
    "CattleOwner": "cattle_owners",
    "RangeConsultant": "consultants",
}


class Actor(object):
    __slots__ = ("role", "user_id", "record")

    def __init__(self, role, user_id, record):
        self.role = role
        self.user_id = user_id
        self.record = record

    @property
    def is_grazier(self):
        return self.role == "Grazier"

    @property
    def is_owner(self):
        return self.role == "CattleOwner"

    @property
    def is_consultant(self):
        return self.role == "RangeConsultant"


def authenticate(allowed_roles, resolve_identity=True):
    """Validation ladder priorities 1-3 (PRD 2.8)."""
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "A valid X-User-Role header is required.")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s is not authorized for this operation." % role)
    user_id = request.headers.get("X-User-ID")
    record = None
    if resolve_identity and role in ROLE_COLLECTION:
        coll = getattr(db, ROLE_COLLECTION[role])
        if not user_id or user_id not in coll:
            raise ApiError("ERR_PARTY_NOT_FOUND", "X-User-ID does not resolve to an existing %s." % role)
        record = coll[user_id]
    return Actor(role, user_id, record)


def body_of(request_obj=None):
    data = (request_obj or request).get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


# --------------------------------------------------------------------------
# Body validation (priority 7 -> ERR_VALIDATION)
# --------------------------------------------------------------------------
def _fail(name, why):
    raise ApiError("ERR_VALIDATION", "%s %s" % (name, why))


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v.strip() == "":
        _fail(name, "is required and must be a non-empty string.")
    return v


def opt_str(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, str):
        _fail(name, "must be a string.")
    return v


def req_state_code(body, name="state_code"):
    v = req_str(body, name)
    if len(v) != 2 or not v.isalpha() or not v.isupper():
        _fail(name, "must be exactly two uppercase letters.")
    return v


def req_enum(body, name, members):
    v = body.get(name)
    if not isinstance(v, str) or v not in members:
        _fail(name, "must be one of %s." % ", ".join(sorted(members)))
    return v


def opt_enum(body, name, members, default=None):
    if name not in body or body.get(name) is None:
        return default
    return req_enum(body, name, members)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(body, name, minv=None, maxv=None, gt=None):
    v = body.get(name)
    if not _is_int(v):
        _fail(name, "is required and must be an integer.")
    _range(name, v, minv, maxv, gt)
    return v


def opt_int(body, name, default=None, minv=None, maxv=None, gt=None):
    if name not in body or body.get(name) is None:
        return default
    return req_int(body, name, minv, maxv, gt)


def req_num(body, name, minv=None, maxv=None, gt=None):
    v = body.get(name)
    if not _is_num(v):
        _fail(name, "is required and must be a number.")
    _range(name, v, minv, maxv, gt)
    return v


def opt_num(body, name, default=None, minv=None, maxv=None, gt=None):
    if name not in body or body.get(name) is None:
        return default
    return req_num(body, name, minv, maxv, gt)


def _range(name, v, minv, maxv, gt):
    if gt is not None and not (v > gt):
        _fail(name, "must be greater than %s." % gt)
    if minv is not None and v < minv:
        _fail(name, "must be no smaller than %s." % minv)
    if maxv is not None and v > maxv:
        _fail(name, "must be no greater than %s." % maxv)


def opt_bool(body, name, default=False):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, bool):
        _fail(name, "must be a boolean.")
    return v


def req_dt_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or parse_dt(v) is None:
        _fail(name, "is required and must be an ISO 8601 date or datetime.")
    return v


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------
def parse_dt(value):
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            d = datetime.fromisoformat(text)
        except ValueError:
            try:
                d = datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                return None
    else:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def whole_days(later, earlier):
    """Whole days between two instants, fraction discarded (floor)."""
    a = parse_dt(later)
    b = parse_dt(earlier)
    if a is None or b is None:
        return 0
    return int(math.floor((a - b).total_seconds() / 86400.0))


def add_days_iso(value, days):
    """Shift an ISO date/datetime string, preserving date-only shape."""
    d = parse_dt(value)
    if d is None:
        return None
    shifted = d + timedelta(days=days)
    if isinstance(value, str) and len(value.strip()) == 10:
        return shifted.strftime("%Y-%m-%d")
    return format_clock(shifted)


def day_of(value):
    d = parse_dt(value)
    return None if d is None else d.date()


# --------------------------------------------------------------------------
# Rounding — house rule is ROUND_HALF_UP everywhere (PRD 2.5)
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def rhu_float(value, places):
    return float(rhu(value, places))
