"""Ordered request validation helpers (PRD 2.7 checks 1-3 and check 7)."""

import re
from datetime import date, datetime, timezone

from flask import request

import store
from errors import fail

ROLES = (
    "PlatformAdmin",
    "RevenueManager",
    "RevenueDirector",
    "ChannelOpsEngineer",
    "ChannelPartner",
)

INTERNAL_ROLES = (
    "PlatformAdmin",
    "RevenueManager",
    "RevenueDirector",
    "ChannelOpsEngineer",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]00:?00)$"
)


# --- checks 1, 2, 3 ------------------------------------------------------

def auth(*allowed):
    """Header presence, role recognition, role permission. Returns (uid, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid.strip() == "" or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if allowed and role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this operation." % role)
    return uid, role


# --- body access ---------------------------------------------------------

def peek_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def body_obj():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# --- primitive parsing --------------------------------------------------

def pdate(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def is_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        pdate(s)
    except ValueError:
        return False
    return True


def parse_instant(s):
    if not isinstance(s, str):
        return None
    m = _INSTANT_RE.match(s)
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _present(src, name):
    return name in src and src[name] is not None


# --- typed field readers (check 7) --------------------------------------

def v_string(src, name, required=False, default=None, minlen=None, maxlen=None,
             pattern=None, nullable=True):
    if name not in src:
        if required:
            _bad(name, "is required")
        return default
    val = src[name]
    if val is None:
        if required or not nullable:
            _bad(name, "may not be null")
        return None
    if not isinstance(val, str):
        _bad(name, "must be a string")
    if minlen is not None and len(val) < minlen:
        _bad(name, "must be at least %d characters" % minlen)
    if maxlen is not None and len(val) > maxlen:
        _bad(name, "must be at most %d characters" % maxlen)
    if pattern is not None and not re.match(pattern, val):
        _bad(name, "does not match the required pattern")
    return val


def v_int(src, name, required=False, default=None, lo=None, hi=None, nullable=True):
    if name not in src:
        if required:
            _bad(name, "is required")
        return default
    val = src[name]
    if val is None:
        if required or not nullable:
            _bad(name, "may not be null")
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        _bad(name, "must be an integer")
    if lo is not None and val < lo:
        _bad(name, "must be at least %d" % lo)
    if hi is not None and val > hi:
        _bad(name, "must be at most %d" % hi)
    return val


def v_bool(src, name, required=False, default=None):
    if name not in src:
        if required:
            _bad(name, "is required")
        return default
    val = src[name]
    if val is None:
        if required:
            _bad(name, "may not be null")
        return default
    if not isinstance(val, bool):
        _bad(name, "must be a boolean")
    return val


def v_enum(src, name, values, required=False, default=None, nullable=True):
    if name not in src:
        if required:
            _bad(name, "is required")
        return default
    val = src[name]
    if val is None:
        if required or not nullable:
            _bad(name, "may not be null")
        return None
    if not isinstance(val, str) or val not in values:
        _bad(name, "must be one of %s" % ", ".join(values))
    return val


def v_date(src, name, required=False, default=None, nullable=True):
    if name not in src:
        if required:
            _bad(name, "is required")
        return default
    val = src[name]
    if val is None:
        if required or not nullable:
            _bad(name, "may not be null")
        return None
    if not is_date(val):
        _bad(name, "must be a YYYY-MM-DD calendar date")
    return val


def v_instant(src, name, required=False, default=None, nullable=True):
    if name not in src:
        if required:
            _bad(name, "is required")
        return default
    val = src[name]
    if val is None:
        if required or not nullable:
            _bad(name, "may not be null")
        return None
    dt = parse_instant(val)
    if dt is None:
        _bad(name, "must be an ISO 8601 UTC instant")
    return dt


def v_str_array(src, name, default=None, minlen=None, maxlen=None, pattern=None):
    if name not in src or src[name] is None:
        return list(default) if default is not None else default
    val = src[name]
    if not isinstance(val, list):
        _bad(name, "must be an array")
    for elem in val:
        if not isinstance(elem, str):
            _bad(name, "must contain only strings")
        if minlen is not None and len(elem) < minlen:
            _bad(name, "elements must be at least %d characters" % minlen)
        if maxlen is not None and len(elem) > maxlen:
            _bad(name, "elements must be at most %d characters" % maxlen)
        if pattern is not None and not re.match(pattern, elem):
            _bad(name, "elements do not match the required pattern")
    return list(val)


# --- query parameters (check 7 applies to every read) -------------------

def q_pagination():
    limit = _q_int("limit", 10, lo=1, hi=100)
    offset = _q_int("offset", 0, lo=0)
    return limit, offset


def _q_int(name, default, lo=None, hi=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw):
        _bad(name, "must be an integer")
    val = int(raw)
    if lo is not None and val < lo:
        _bad(name, "must be at least %d" % lo)
    if hi is not None and val > hi:
        _bad(name, "must be at most %d" % hi)
    return val


def q_enum(name, values, required=False, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            _bad(name, "is required")
        return default
    if raw not in values:
        _bad(name, "must be one of %s" % ", ".join(values))
    return raw


def q_date(name, required=False, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            _bad(name, "is required")
        return default
    if not is_date(raw):
        _bad(name, "must be a YYYY-MM-DD calendar date")
    return raw


def q_str(name, required=False, default=None, minlen=None, maxlen=None, pattern=None):
    raw = request.args.get(name)
    if raw is None:
        if required:
            _bad(name, "is required")
        return default
    if raw == "" and not required:
        return default
    if minlen is not None and len(raw) < minlen:
        _bad(name, "must be at least %d characters" % minlen)
    if maxlen is not None and len(raw) > maxlen:
        _bad(name, "must be at most %d characters" % maxlen)
    if pattern is not None and not re.match(pattern, raw):
        _bad(name, "does not match the required pattern")
    return raw


def q_bool(name, default=False):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    _bad(name, "must be a boolean")


def q_id(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
