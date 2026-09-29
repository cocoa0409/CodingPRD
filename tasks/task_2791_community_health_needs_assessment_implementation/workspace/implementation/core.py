"""Foundation layer: in-memory store, logical clock, envelope, errors, auth,
body-shape validation and pagination.

Storage is a set of plain Python dicts keyed by the record's UUID.  Nothing is
persisted anywhere and nothing is seeded: every boot starts completely empty.
"""

import json
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import g, request

import consts as K

# ---------------------------------------------------------------------------
# in-memory store
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.cycles = {}
        self.indicators = {}
        self.data_points = {}
        self.parties = {}
        self.interviews = {}
        self.candidates = {}
        self.strategies = {}
        self.objectives = {}
        self.agreements = {}
        self.commitments = {}
        self.reports = {}
        self.postings = {}
        self.evaluations = {}
        self._seq = 0
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(raw):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(raw, str):
        return None
    m = TS_RE.match(raw.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        base = datetime(int(y), int(mo), int(d), int(hh), int(mm),
                        int(ss or 0), micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")
        base = base - sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return base


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date into a date, or None."""
    if not isinstance(raw, str):
        return None
    m = DATE_RE.match(raw.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def fmt_instant(dt):
    """Canonical wire format: ISO-8601 UTC with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(db.clock)


def clock_date():
    return db.clock.date()


def set_clock(dt):
    db.clock = dt


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

HTTP_FOR_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_AGREEMENT_PARTY": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_INDICATOR_NOT_FOUND": 404,
    "ERR_DATA_POINT_NOT_FOUND": 404,
    "ERR_PARTY_NOT_FOUND": 404,
    "ERR_INTERVIEW_NOT_FOUND": 404,
    "ERR_CANDIDATE_NOT_FOUND": 404,
    "ERR_STRATEGY_NOT_FOUND": 404,
    "ERR_OBJECTIVE_NOT_FOUND": 404,
    "ERR_PARTNERSHIP_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_POSTING_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_STALE_CANDIDATE_VERSION": 412,
    "ERR_STALE_REPORT_VERSION": 412,
    "ERR_CYCLE_FROZEN": 409,
    "ERR_CYCLE_RESTRICTED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_PHASE_TRANSITION": 409,
    "ERR_STRATEGY_LOCKED": 409,
    "ERR_INPUT_WINDOW_CLOSED": 409,
    "ERR_INDICATOR_DATA_INSUFFICIENT": 409,
    "ERR_STRATEGY_NOT_APPROVED": 409,
    "ERR_PARTNERSHIP_NOT_EXECUTED": 409,
    "ERR_PARTY_TYPE_MISMATCH": 409,
    "ERR_PUBLIC_AVAILABILITY_NOT_MET": 409,
    "ERR_REPORT_NOT_LOCKED": 409,
    "ERR_STRATEGY_SET_INCOMPLETE": 409,
    "ERR_ANNUAL_REPORT_MISSING": 409,
    "ERR_FACILITATOR_WINDOW_CONFLICT": 409,
    "ERR_DATA_POINT_OUT_OF_WINDOW": 409,
    "ERR_COMMITMENT_OUTSIDE_TERM": 409,
    "ERR_DUPLICATE_FISCAL_YEAR": 409,
    "ERR_DUPLICATE_INDICATOR_NAME": 409,
    "ERR_DUPLICATE_ORGANIZATION": 409,
    "ERR_DUPLICATE_REPORT": 409,
    "ERR_DUPLICATE_EVALUATION_PERIOD": 409,
    "ERR_POSTING_BASIS_MISMATCH": 409,
    "ERR_PARTY_FTE_CAPACITY_EXCEEDED": 409,
    "ERR_PARTNERSHIP_PLEDGE_WINDOW_EXCEEDED": 409,
    "ERR_STRATEGY_BUDGET_EXCEEDED": 409,
    "ERR_INSUFFICIENT_INDICATOR_COVERAGE": 409,
    "ERR_NO_COMMUNITY_INPUT": 409,
    "ERR_NO_SELECTED_PRIORITY": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_ADOPTION_VOTE_FAILED": 409,
    "ERR_NO_DOMAIN_INPUT": 409,
    "ERR_STALE_CONCERN_INPUT": 409,
    "ERR_PRIORITY_SCORE_BELOW_THRESHOLD": 409,
    "ERR_REPORT_EMPTY": 409,
    "ERR_OBJECTIVE_PROGRESS_MISSING": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = HTTP_FOR_ERROR.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# JSON serialization — Decimal renders as a literal JSON number, never a string
# ---------------------------------------------------------------------------

_ESCAPES = {
    '"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t",
    "\b": "\\b", "\f": "\\f",
}


def _enc_str(s):
    out = ['"']
    for ch in s:
        esc = _ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def dumps(obj):
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, str):
        return _enc_str(obj)
    if isinstance(obj, dict):
        return "{" + ",".join(
            _enc_str(str(k)) + ":" + dumps(v) for k, v in obj.items()
        ) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(dumps(v) for v in obj) + "]"
    return _enc_str(str(obj))


# ---------------------------------------------------------------------------
# response envelope
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return dumps(body), status, {"Content-Type": "application/json"}


def ok_list(rows, page):
    meta = _meta()
    meta["limit"] = page["limit"]
    meta["offset"] = page["offset"]
    meta["total_count"] = page["total_count"]
    meta["has_more"] = page["has_more"]
    body = {"meta": meta, "response_type": "array", "data": rows}
    return dumps(body), 200, {"Content-Type": "application/json"}


def no_content():
    return "", 204, {}


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return dumps(body), err.http_status, {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# system fields / version bookkeeping
# ---------------------------------------------------------------------------


def new_record():
    stamp = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Mutation bookkeeping: version rises at most once per HTTP request."""
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if rec["id"] not in touched:
        touched.add(rec["id"])
        rec["version"] += 1
    rec["updated_at"] = now_iso()


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# authentication and authorization
# ---------------------------------------------------------------------------


def authenticate(allowed_roles):
    user_id = request.headers.get(K.HDR_USER_ID)
    role = request.headers.get(K.HDR_USER_ROLE)
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in K.ROLES:
        fail("ERR_UNAUTHENTICATED", "A valid X-User-Role header is required.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    g.user_id = str(user_id)
    g.role = role
    return str(user_id), role


# ---------------------------------------------------------------------------
# request body handling
# ---------------------------------------------------------------------------


def body_or_empty():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def raw_field(body, name):
    """Peek at a body field without validating it (rung-2 role refinements)."""
    return body.get(name)


_MISSING = object()


def _present(body, name, required):
    if name not in body or body[name] is None:
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return False
    return True


def v_str(body, name, min_len=1, max_len=None, required=True, default=None):
    if not _present(body, name, required):
        return default
    val = body[name]
    if not isinstance(val, str):
        fail("ERR_VALIDATION", "Field '%s' must be a string." % name)
    if min_len is not None and len(val) < min_len:
        fail("ERR_VALIDATION", "Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(val) > max_len:
        fail("ERR_VALIDATION", "Field '%s' must be at most %d characters." % (name, max_len))
    return val


def v_int(body, name, lo=None, hi=None, required=True, default=None):
    if not _present(body, name, required):
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        fail("ERR_VALIDATION", "Field '%s' must be an integer." % name)
    if lo is not None and val < lo:
        fail("ERR_VALIDATION", "Field '%s' must be >= %d." % (name, lo))
    if hi is not None and val > hi:
        fail("ERR_VALIDATION", "Field '%s' must be <= %d." % (name, hi))
    return val


def _as_decimal(name, val):
    if isinstance(val, bool):
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if isinstance(val, int):
        return Decimal(val)
    if isinstance(val, Decimal):
        return val
    if isinstance(val, float):
        try:
            return Decimal(repr(val))
        except InvalidOperation:
            fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    fail("ERR_VALIDATION", "Field '%s' must be a number." % name)


def _places(dec):
    exp = dec.as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return -exp if exp < 0 else 0


def v_num(body, name, lo=None, hi=None, places=None, exact_places=None,
          exclusive_lo=False, required=True, default=None):
    if not _present(body, name, required):
        return default
    dec = _as_decimal(name, body[name])
    if not dec.is_finite():
        fail("ERR_VALIDATION", "Field '%s' must be a finite number." % name)
    if lo is not None:
        if exclusive_lo and dec <= Decimal(lo):
            fail("ERR_VALIDATION", "Field '%s' must be greater than %s." % (name, lo))
        if not exclusive_lo and dec < Decimal(lo):
            fail("ERR_VALIDATION", "Field '%s' must be >= %s." % (name, lo))
    if hi is not None and dec > Decimal(hi):
        fail("ERR_VALIDATION", "Field '%s' must be <= %s." % (name, hi))
    if exact_places is not None and _places(dec) != exact_places:
        fail("ERR_VALIDATION",
             "Field '%s' must carry exactly %d decimal places." % (name, exact_places))
    if places is not None and _places(dec) > places:
        fail("ERR_VALIDATION",
             "Field '%s' must carry at most %d decimal places." % (name, places))
    return dec


def v_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name, required):
        return default
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        fail("ERR_VALIDATION", "Field '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return val


def v_bool(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    val = body[name]
    if not isinstance(val, bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % name)
    return val


def v_date(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    val = body[name]
    if not isinstance(val, str):
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date string." % name)
    parsed = parse_date(val)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date string." % name)
    return parsed


def v_instant(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    val = body[name]
    parsed = parse_instant(val) if isinstance(val, str) else None
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def v_id(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    val = body[name]
    if not isinstance(val, str) or val.strip() == "":
        fail("ERR_VALIDATION", "Field '%s' must be a non-empty string identifier." % name)
    return val


def v_concern_ratings(body, name="concern_ratings", required=True):
    if not _present(body, name, required):
        return None
    val = body[name]
    if not isinstance(val, dict):
        fail("ERR_VALIDATION", "Field '%s' must be an object." % name)
    out = {}
    for key, rating in val.items():
        if key not in K.DOMAINS:
            fail("ERR_VALIDATION",
                 "Field '%s' keys must be health-domain enum members." % name)
        if isinstance(rating, bool) or not isinstance(rating, int):
            fail("ERR_VALIDATION", "Field '%s' values must be integers 1..5." % name)
        if rating < 1 or rating > 5:
            fail("ERR_VALIDATION", "Field '%s' values must be integers 1..5." % name)
        out[key] = rating
    return out


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------


def _qs_int(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw.strip()):
        fail("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    val = int(raw.strip())
    if lo is not None and val < lo:
        fail("ERR_VALIDATION", "Query parameter '%s' must be >= %d." % (name, lo))
    if hi is not None and val > hi:
        fail("ERR_VALIDATION", "Query parameter '%s' must be <= %d." % (name, hi))
    return val


def paginate(rows):
    limit = _qs_int("limit", K.PAGE_LIMIT_DEFAULT, K.PAGE_LIMIT_MIN, K.PAGE_LIMIT_MAX)
    offset = _qs_int("offset", K.PAGE_OFFSET_DEFAULT, K.PAGE_OFFSET_MIN, None)
    total = len(rows)
    window = rows[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return [public(r) for r in window], page


def filter_eq(rows, field, param=None):
    """Additive equality filter driven by a query-string parameter."""
    name = param or field
    raw = request.args.get(name)
    if raw is None or raw == "":
        return rows
    if field in ("fiscal_year", "period_year"):
        if not re.match(r"^-?\d+$", raw.strip()):
            fail("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
        want = int(raw.strip())
    else:
        want = raw
    return [r for r in rows if r.get(field) == want]


def sorted_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sorted_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q0(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
