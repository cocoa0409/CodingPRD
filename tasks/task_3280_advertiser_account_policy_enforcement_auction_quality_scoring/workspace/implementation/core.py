"""Core infrastructure: logical clock, store, errors, envelope, auth."""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from flask import request, jsonify

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    if s is None:
        return None
    s2 = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Clock:
    def __init__(self):
        self._current = _parse_iso(DEFAULT_CLOCK)

    def now(self):
        return self._current

    def now_iso(self):
        return self._fmt(self._current)

    def today(self):
        return self._current.date()

    def set(self, to_iso8601):
        dt = _parse_iso(to_iso8601)
        self._current = dt
        return self._fmt(dt)

    @staticmethod
    def _fmt(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


CLOCK = Clock()


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_ts():
    """Timestamp for meta.created_at fields (3 fractional digits)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def req_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

HTTP_FOR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_VERIFICATION_REQUIRED": 422,
    "ERR_ACCOUNT_SUSPENDED": 422,
    "ERR_DUPLICATE_VERIFICATION_PENDING": 409,
    "ERR_BILLING_PROFILE_EXISTS": 409,
    "ERR_APPEAL_ALREADY_OPEN": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_APPEAL_COOLDOWN": 422,
    "ERR_RESTRICTED_CATEGORY_UNCERTIFIED": 422,
    "ERR_DUPLICATE_AD_HEADLINE": 409,
    "ERR_DUPLICATE_KEYWORD": 409,
    "ERR_NEGATIVE_KEYWORD_CONFLICT": 409,
    "ERR_BUDGET_BELOW_MINIMUM": 422,
    "ERR_CAMPAIGN_DATE_RANGE_INVALID": 422,
    "ERR_CAMPAIGN_OUTSIDE_FLIGHT_WINDOW": 422,
    "ERR_DAILY_OVERDELIVERY_LIMIT": 422,
    "ERR_NO_ELIGIBLE_AD": 422,
    "ERR_OVERPAYMENT": 422,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_MONTH_NOT_CLOSABLE": 422,
    "ERR_AUCTION_NOT_CLICKED": 409,
    "ERR_CLICK_ALREADY_INVALID": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        self.error_id = error_id
        self.message = message
        self.http_status = HTTP_FOR[error_id]
        super().__init__(message)


def err(error_id, message):
    raise ApiError(error_id, message)


def error_response(e):
    body = {
        "meta": {"api_request_id": new_req_id(), "api_request_timestamp": req_ts()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Success envelope
# ---------------------------------------------------------------------------

def ok(data, status=200, pagination=None):
    meta = {"api_request_id": new_req_id(), "api_request_timestamp": req_ts()}
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def paginate(items):
    """Apply limit/offset from query args; return (page_items, pagination_meta)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        err("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        err("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        err("ERR_VALIDATION", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = {"Anonymous", "Advertiser", "PolicyReviewer", "BillingAdmin", "PlatformAdmin"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers")
    return Caller(uid, role)


def require_role(caller, *roles):
    if caller.role not in roles:
        err("ERR_FORBIDDEN", "Role not permitted for this endpoint")


def check_ownership(caller, account_id):
    if caller.role == "Advertiser" and caller.user_id != account_id:
        err("ERR_FORBIDDEN", "Advertiser may only act on its own account")


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.accounts = {}
        self.verifications = {}
        self.appeals = {}
        self.billing_profiles = {}
        self.campaigns = {}
        self.ad_groups = {}
        self.ads = {}
        self.keywords = {}
        self.policy_reviews = {}
        self.auction_events = {}
        self.daily_spend_records = {}   # keyed by (campaign_id, spend_date)
        self.invoices = {}


DB = Store()


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------

_entity_seq = [0]


def entity_ts():
    """Entity created_at/updated_at stamps come from the logical clock
    (PRD: time never comes from the wall clock), rendered with three
    fractional digits per the common resource shape."""
    now = CLOCK.now()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_record(fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = entity_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    # Monotonic creation sequence so "earliest created" / "creation order"
    # tie-breaks stay deterministic even when several records share the same
    # logical-clock instant.
    _entity_seq[0] += 1
    rec["_seq"] = _entity_seq[0]
    return rec


def touch(rec):
    rec["updated_at"] = entity_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def normalize_text(s):
    return _WS.sub(" ", s.strip().lower())


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a date string")
    return datetime.strptime(s, "%Y-%m-%d").date()
