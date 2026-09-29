"""Core infrastructure: logical clock, in-memory store, response envelope, errors.

Every structural name in this module is taken from PRD.md sections 2.1-2.9 and
SCAFFOLD.yaml `response_envelope`:
  success envelope : { "meta": {api_request_id, api_request_timestamp, ...},
                       "response_type": "object"|"array", "data": ... }
  error envelope   : { "meta": {...}, "response_type": "error",
                       "data": { "error_id", "message" } }
  pagination fields: limit / offset / total_count / has_more inside meta
  auth headers     : X-User-ID / X-User-Role
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# numeric discipline (PRD 2.6): 2 decimals, round_half_up, JSON numbers
# --------------------------------------------------------------------------
TWO = Decimal("0.01")


def D(value):
    """Coerce to Decimal without float contamination."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value):
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal as a JSON number carried to 2 decimals."""
    return float(q2(value))


# --------------------------------------------------------------------------
# timestamps (PRD 2.4): ISO 8601 UTC with exactly three fractional digits
# --------------------------------------------------------------------------
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock(object):
    """PRD 2.8: the logical clock. Reads 2026-08-01T00:00:00Z before any write
    and never falls back to wall-clock time."""

    def __init__(self):
        self.current = INITIAL_CLOCK

    def now(self):
        return self.current

    def set(self, dt):
        previous = self.current
        self.current = dt
        return previous


clock = Clock()


def now():
    return clock.now()


def plus_hours(dt, hours):
    return dt + timedelta(hours=int(hours))


def plus_days(dt, days):
    return dt + timedelta(days=int(days))


# --------------------------------------------------------------------------
# in-memory store -- starts empty on every boot, never seeded
# --------------------------------------------------------------------------
COLLECTIONS = (
    "policy_rules",
    "country_overrides",
    "advertisers",
    "reviewers",
    "ad_creatives",
    "screening_runs",
    "classifier_decisions",
    "review_tasks",
    "certifications",
    "destination_checks",
    "disapproval_notices",
    "appeals",
    "enforcement_actions",
    "political_archive_entries",
    "violation_ledger_entries",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()

MUTABLE_COMMON = "mutable"
EVIDENCE_COMMON = "evidence"


def new_id():
    return str(uuid.uuid4())


def new_row(kind=MUTABLE_COMMON):
    """Create a row carrying the common fields of PRD 2.4.

    `mutable` rows carry id/created_at/updated_at/version; `evidence` rows
    (ScreeningRun, ClassifierDecision, DestinationCheck, PoliticalArchiveEntry,
    ViolationLedgerEntry) carry only id/created_at.
    """
    stamp = now()
    row = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if kind == MUTABLE_COMMON:
        row["updated_at"] = stamp
        row["version"] = 1
    mark_touched(row)
    return row


def _touched():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def mark_touched(row):
    try:
        _touched().add(row["id"])
    except RuntimeError:
        pass


def touch(row):
    """PRD 2.9: every row a cascade reaches refreshes its own updated_at and
    increments its own version by exactly 1 -- once per request."""
    if row is None or "version" not in row:
        return
    try:
        seen = _touched()
    except RuntimeError:
        seen = None
    if seen is not None:
        if row["id"] in seen:
            return
        seen.add(row["id"])
    row["updated_at"] = now()
    row["version"] += 1


def order_key(row):
    return (row["created_at"], row["_seq"])


def newest_first(rows):
    return sorted(rows, key=order_key, reverse=True)


def oldest_first(rows):
    return sorted(rows, key=order_key)


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of Advertiser, PolicyReviewer, IntegrityAnalyst, PolicyAdmin.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_ADVERTISER_SCOPE_VIOLATION": "The acting principal is out of scope for the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "A reviewer may not adjudicate an appeal against their own disapproval.",
    "ERR_REVIEWER_NOT_AUTHORIZED_COUNTRY": "A target country of the creative is absent from the reviewer's country authorizations.",
    "ERR_REVIEWER_QUEUE_MISMATCH": "The task queue is absent from the reviewer's queue specialties.",
    "ERR_INVALID_REQUEST": "The request body is malformed or violates a declared constraint.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset a non-negative integer.",
    "ERR_ADVERTISER_NOT_FOUND": "No such advertiser.",
    "ERR_AD_CREATIVE_NOT_FOUND": "No such ad creative.",
    "ERR_POLICY_RULE_NOT_FOUND": "No such policy rule.",
    "ERR_REVIEWER_NOT_FOUND": "No such reviewer.",
    "ERR_SCREENING_RUN_NOT_FOUND": "No such screening run.",
    "ERR_REVIEW_TASK_NOT_FOUND": "No such review task.",
    "ERR_CERTIFICATION_NOT_FOUND": "No such certification.",
    "ERR_DISAPPROVAL_NOTICE_NOT_FOUND": "No such disapproval notice.",
    "ERR_APPEAL_NOT_FOUND": "No such appeal.",
    "ERR_ENFORCEMENT_ACTION_NOT_FOUND": "No such enforcement action.",
    "ERR_INVALID_CREATIVE_STATE": "The creative admits no such transition from its current state.",
    "ERR_INVALID_TASK_STATE": "The review task admits no such action from its current status.",
    "ERR_NOTICE_NOT_APPEALABLE": "The disapproval notice is no longer appealable.",
    "ERR_APPEAL_NOT_PENDING": "The appeal is not pending adjudication.",
    "ERR_INVALID_CERTIFICATION_STATE": "The certification is already expired or revoked.",
    "ERR_STALE_CREATIVE_VERSION": "expected_ad_creative_version does not match the current creative version.",
    "ERR_STALE_ADVERTISER_VERSION": "expected_advertiser_version does not match the current advertiser version.",
    "ERR_PROHIBITED_CATEGORY_BLOCKED": "The creative matched a prohibited category or retains a blocked country.",
    "ERR_ADVERTISER_SUSPENDED": "The owning advertiser account is suspended.",
    "ERR_POLITICAL_ELIGIBILITY_MISSING": "The advertiser is not eligible for political advertising.",
    "ERR_POLITICAL_DISCLOSURE_MISSING": "Non-empty disclaimer text is required to approve this creative.",
    "ERR_ADVERTISER_RESTRICTED_CATEGORY": "A restricted account may not author this creative.",
    "ERR_REVIEWER_OFFLINE": "The claiming reviewer is offline.",
    "ERR_REVIEWER_CAPACITY_EXCEEDED": "The reviewer is already at their concurrent claim ceiling.",
    "ERR_CERTIFICATION_MISSING": "No active certification covers a retained country that demands a license.",
    "ERR_INVALID_LIMITED_COUNTRIES": "limited_country_codes must be a non-empty duplicate-free subset of the creative's target countries.",
    "ERR_INVALID_VALIDITY_WINDOW": "valid_until must be strictly after valid_from.",
    "ERR_CERTIFICATION_INTERVAL_OVERLAP": "The certification interval intersects an existing submitted or active interval.",
    "ERR_APPEAL_WINDOW_CLOSED": "The appeal window for this notice has closed.",
    "ERR_ENFORCEMENT_COOLDOWN_CONFLICT": "The action would take effect inside an existing action's cooldown blackout.",
    "ERR_CLOCK_REWIND": "to_iso8601 must be a valid ISO 8601 UTC instant not earlier than the current logical clock.",
    "ERR_APPEAL_ALREADY_EXISTS": "An appeal already exists for this disapproval notice.",
    "ERR_UNKNOWN_POLICY_CATEGORY": "fetched_content_category must be GENERAL or an existing policy rule code.",
    "ERR_INVALID_REASON_CODE": "A supplied reason code contradicts the creative's current state.",
    "ERR_CERTIFICATION_OWNER_MISMATCH": "The evidence certification belongs to a different advertiser.",
    "ERR_DUPLICATE_POLICY_CODE": "The policy code or rule-and-country pair already exists.",
    "ERR_INVALID_THRESHOLD_ORDER": "confidence_auto_disapprove_threshold must be strictly greater than confidence_manual_threshold.",
}


def fail(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# --------------------------------------------------------------------------
# response envelope
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# auth (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_ADVERTISER = "Advertiser"
ROLE_REVIEWER = "PolicyReviewer"
ROLE_ANALYST = "IntegrityAnalyst"
ROLE_ADMIN = "PolicyAdmin"
ALL_ROLES = (ROLE_ADVERTISER, ROLE_REVIEWER, ROLE_ANALYST, ROLE_ADMIN)


def authenticate(*allowed_roles):
    """Validation priority 10 then 12: ERR_UNAUTHENTICATED, then ERR_FORBIDDEN_ROLE."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", 401)
    if role is None or str(role).strip() == "" or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", 401)
    if allowed_roles and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", 403)
    return user_id, role


def require_reviewer_identity(user_id, role):
    """PRD 2.1: a PolicyReviewer's X-User-ID must resolve to an existing Reviewer."""
    if role != ROLE_REVIEWER:
        return None
    reviewer = db.reviewers.get(user_id)
    if reviewer is None:
        fail("ERR_ADVERTISER_SCOPE_VIOLATION", 403)
    return reviewer


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------
def _as_int(raw):
    text = str(raw).strip()
    if text == "":
        return None
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        limit = _as_int(limit_raw)
        if limit is None or limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", 400)
    if offset_raw is not None:
        offset = _as_int(offset_raw)
        if offset is None or offset < 0:
            fail("ERR_INVALID_PAGINATION", 400)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    return None
