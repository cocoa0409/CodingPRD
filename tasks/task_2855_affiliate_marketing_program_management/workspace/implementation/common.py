"""Foundation layer: logical clock, in-memory store, errors, response envelope,
auth/RBAC helpers, body validation helpers and entity serializers.

All structural names below are taken from PRD.md sections 2.1-2.4 and the
scaffold's response_envelope block:
  * identity headers  : X-User-ID, X-User-Role
  * envelope          : meta / response_type / data
  * error body        : error_id / message
  * pagination fields : limit / offset / total_count / has_more
  * system fields     : id / created_at / updated_at / version
"""

import os
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.9) -- default 2026-08-01T00:00:00.000Z
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.current = DEFAULT_CLOCK


clock = Clock()


def now_dt():
    return clock.current


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(clock.current)


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_instant(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm, ss, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac[1:] + "000000")[:6])
        dt = datetime(
            int(year), int(month), int(day),
            int(hh or 0), int(mm or 0), int(ss or 0), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        dt = dt - sign * offset
    return dt


# ---------------------------------------------------------------------------
# Rounding helpers -- money is integer cents, rates are integer basis points
# ---------------------------------------------------------------------------

def D(value):
    return Decimal(value)


def rhu_int(value):
    """Round half up (away from zero on exact halves) to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu1(value):
    """Round half up to exactly one decimal place; returned as a JSON number."""
    q = Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# ---------------------------------------------------------------------------
# Errors (PRD 5)
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_AFFILIATE_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_TRACKING_LINK_NOT_FOUND": 404,
    "ERR_CONVERSION_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_NETWORK_NOT_FOUND": 404,
    "ERR_TAX_DOCUMENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PAGINATION_INVALID": 400,
    "ERR_AFFILIATE_SUSPENDED": 409,
    "ERR_APPLICATION_TERMINAL": 409,
    "ERR_APPLICATION_NOT_SCREENED": 409,
    "ERR_CONVERSION_ALREADY_ATTRIBUTED": 409,
    "ERR_CONVERSION_NOT_ATTRIBUTED": 409,
    "ERR_CASE_ALREADY_TERMINAL": 409,
    "ERR_CASE_INVALID_TRANSITION": 409,
    "ERR_BATCH_TERMINAL": 409,
    "ERR_BATCH_NOT_VALIDATED": 409,
    "ERR_LINE_NOT_HELD": 409,
    "ERR_AFFILIATE_NOT_ELIGIBLE": 409,
    "ERR_TRACKING_LINK_DISABLED": 409,
    "ERR_STALE_AFFILIATE_VERSION": 412,
    "ERR_STALE_CONVERSION_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_BRAND_SUITABILITY_VIOLATION": 422,
    "ERR_FRAUD_HOLD_NOT_CLEARABLE": 409,
    "ERR_OPEN_VIOLATION_CASES": 409,
    "ERR_RISK_SCORE_TOO_HIGH": 409,
    "ERR_INVALID_EFFECTIVE_WINDOW": 422,
    "ERR_SCAN_WINDOW_OVERLAP": 409,
    "ERR_POLICY_WINDOW_OVERLAP": 409,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_DUPLICATE_ORDER_REF": 409,
    "ERR_SUB_AFFILIATE_DEPTH_EXCEEDED": 422,
    "ERR_CIRCULAR_SUB_AFFILIATE": 422,
    "ERR_REVISION_LIMIT_REACHED": 422,
    "ERR_SCREENING_NOT_PASSED": 422,
    "ERR_ADJUSTMENT_EXCEEDS_ORDER": 422,
    "ERR_NO_ACTIVE_COMMISSION_POLICY": 422,
    "ERR_TAX_DOCUMENT_INVALID": 422,
    "ERR_APPROVAL_LIMIT_EXCEEDED": 422,
    "ERR_NETWORK_FEE_VARIANCE": 422,
    "ERR_NO_ELIGIBLE_PAYOUT_LINES": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# In-memory store -- starts completely empty on every boot, never seeded
# ---------------------------------------------------------------------------

class Store(object):
    def __init__(self):
        self.networks = {}
        self.affiliates = {}
        self.applications = {}
        self.policies = {}
        self.links = {}
        self.clicks = {}
        self.conversions = {}
        self.decisions = {}
        self.scans = {}
        self.cases = {}
        self.tax_documents = {}
        self.ledger = {}
        self.batches = {}
        self.lines = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_row(mutable=True, **fields):
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    if mutable:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    _touched().add(row["id"])
    return row


def _touched():
    s = getattr(g, "_touched_rows", None)
    if s is None:
        s = set()
        g._touched_rows = s
    return s


def touch(row):
    """Mark a row mutated: refresh updated_at and bump version by exactly one
    per request (PRD 2.11 -- a row touched several times inside one request
    still moves by exactly one version)."""
    if row is None:
        return row
    row["updated_at"] = now_iso()
    seen = _touched()
    if row["id"] not in seen:
        seen.add(row["id"])
        if "version" in row:
            row["version"] = row["version"] + 1
    return row


def ordered(collection):
    """Default sort: created_at ascending (insertion sequence breaks ties)."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2 / 2.3)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def respond(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def respond_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        if not re.match(r"^[+-]?\d+$", raw_limit.strip()):
            fail("ERR_PAGINATION_INVALID", "limit must be an integer")
        limit = int(raw_limit.strip())
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            fail("ERR_PAGINATION_INVALID", "limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        if not re.match(r"^[+-]?\d+$", raw_offset.strip()):
            fail("ERR_PAGINATION_INVALID", "offset must be an integer")
        offset = int(raw_offset.strip())
        if offset < 0:
            fail("ERR_PAGINATION_INVALID", "offset must be zero or greater")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Roles and authentication (PRD 2.1)
# ---------------------------------------------------------------------------

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_PARTNER_MANAGER = "PartnerManager"
ROLE_COMPLIANCE = "ComplianceAnalyst"
ROLE_FIN_ANALYST = "FinanceAnalyst"
ROLE_FIN_CONTROLLER = "FinanceController"
ROLE_PARTNER = "AffiliatePartner"
ROLE_INGESTOR = "TrackingIngestor"
ROLE_ANONYMOUS = "Anonymous"

ALL_STAFF = [
    ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE,
    ROLE_FIN_ANALYST, ROLE_FIN_CONTROLLER,
]


def authorize(roles, anonymous_route=False):
    """Rule 1 then rule 2 of the global precedence order: authentication is
    checked before authorization, and both run before any existence lookup."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    uid = uid.strip() if isinstance(uid, str) else ""
    role = role.strip() if isinstance(role, str) else ""
    if not role:
        role = ROLE_ANONYMOUS
    if not uid and not anonymous_route:
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role not in roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    g.user_id = uid or None
    g.role = role
    return g.user_id, role


def require_owner(owner_affiliate_id):
    """Rule 13: an AffiliatePartner acts only on its own records, checked after
    the addressed row has been proven to exist."""
    if getattr(g, "role", None) == ROLE_PARTNER:
        if g.user_id != owner_affiliate_id:
            fail("ERR_NOT_RESOURCE_OWNER", "caller is not the owner of this resource")


def check_sod(other_user_id, message):
    """Rule 16: segregation of duties, compared on X-User-ID."""
    if other_user_id is not None and getattr(g, "user_id", None) == other_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", message)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

CURRENCIES = ["USD", "EUR", "GBP"]
FEE_MODELS = ["PERCENT_OF_COMMISSION", "FLAT_PER_CONVERSION", "HYBRID"]
PARTNER_TYPES = ["CONTENT", "INFLUENCER", "PAID_SEARCH", "COUPON",
                 "LOYALTY_CASHBACK", "SUB_NETWORK"]
AFFILIATE_STATUSES = ["PENDING_APPLICATION", "ACTIVE", "SUSPENDED", "TERMINATED"]
SUSPENSION_CAUSES = ["NONE", "COMPLIANCE_ACTION", "FRAUD_SCORE_BREACH",
                     "PARENT_SUSPENSION"]
INCREMENTALITY_TIERS = ["LOW", "MEDIUM", "HIGH"]
TAX_STATUSES = ["NONE", "PENDING", "VALID", "EXPIRED", "REJECTED"]
TRAFFIC_SOURCES = ["ORGANIC_SEARCH", "PAID_SEARCH", "SOCIAL_ORGANIC",
                   "CONTENT_NEWSLETTER", "COUPON_DIRECTORY", "CASHBACK_PORTAL",
                   "INCENTIVIZED_TRAFFIC"]
PROMO_METHODS = ["EDITORIAL_CONTENT", "EMAIL", "SOCIAL_POST", "COUPON_FEED",
                 "TRADEMARK_PAID_SEARCH", "BROWSER_EXTENSION", "TOOLBAR"]
PRODUCT_CATEGORIES = ["APPAREL", "ELECTRONICS", "HOME", "BEAUTY", "GROCERY"]
APPLICATION_STATES = ["SUBMITTED", "SCREENED", "CHANGES_REQUESTED",
                      "APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED"]
SCREENING_OUTCOMES = ["NOT_SCREENED", "PASS", "CONDITIONAL", "FAIL"]
POLICY_STATES = ["DRAFT", "ACTIVE", "SUPERSEDED"]
LINK_STATES = ["ACTIVE", "DISABLED"]
SYSTEM_DISABLE_REASONS = ["AFFILIATE_SUSPENDED", "AFFILIATE_TERMINATED",
                          "APPLICATION_REJECTED"]
CLICK_TYPES = ["ORGANIC_CLICK", "FORCED_CLICK", "IFRAME_IMPRESSION"]
OTHER_CHANNELS = ["NONE", "PAID_SOCIAL", "EMAIL", "BRAND_PAID_SEARCH", "DIRECT"]
ATTRIBUTION_STATUSES = ["UNATTRIBUTED", "AFFILIATE_ATTRIBUTED", "CREDIT_REDUCED",
                        "DEDUPED_TO_OTHER_CHANNEL", "DETACHED"]
VALIDATION_STATUSES = ["PENDING_VALIDATION", "VALIDATED", "REVERSED", "CLAWED_BACK"]
ALGORITHM_VARIANTS = ["LAST_CLICK_RAW", "INCREMENTALITY_ADJUSTED"]
DEVICE_MATCH_MODES = ["NONE", "DEVICE_EXACT", "HOUSEHOLD_GRAPH"]
DEDUP_REASONS = ["NONE", "NO_ELIGIBLE_CLICK", "OTHER_CHANNEL_LATER_TOUCH",
                 "LOW_INCREMENTALITY_PARTNER"]
LEDGER_TYPES = ["ACCRUAL", "REVERSAL", "CLAWBACK", "ADJUSTMENT", "SETTLEMENT"]
SCAN_ENGINES = ["GOOGLE_ADS", "BING_ADS", "SHOPPING_FEED", "EXTENSION_STORE"]
VIOLATION_TYPES = ["TRADEMARK_BIDDING", "UNAUTHORIZED_COUPON",
                   "COOKIE_STUFFING", "FORCED_CLICK"]
CASE_STATES = ["OPEN", "REMEDIATION_REQUESTED", "REMEDIATION_SUBMITTED",
               "VERIFIED_CLEARED", "ESCALATED", "UPHELD"]
CASE_ACTIONS = ["REQUEST_REMEDIATION", "SUBMIT_REMEDIATION", "VERIFY", "ESCALATE"]
VERIFY_OUTCOMES = ["CLEARED", "FAILED", "UPHELD"]
FORM_TYPES = ["W9", "W8BEN"]
TAX_DOC_STATES = ["PENDING", "VALID", "REJECTED", "EXPIRED"]
VERIFICATION_OUTCOMES = ["VALID", "REJECTED"]
ADJUSTMENT_TYPES = ["FULL_CANCELLATION", "PARTIAL_RETURN", "FULL_RETURN"]
DECISIONS = ["APPROVE", "APPROVE_WITH_CONDITIONS", "REQUEST_CHANGES", "REJECT"]
BATCH_STATES = ["DRAFT", "VALIDATED", "APPROVED", "PAID", "VOIDED"]
LINE_STATES = ["INCLUDED", "HELD_TAX_DOC", "HELD_FRAUD", "HELD_BELOW_MINIMUM",
               "PAID", "VOIDED"]
HOLD_REASONS = ["BELOW_MINIMUM_PAYOUT", "TAX_DOCUMENT_NOT_VALID",
                "AFFILIATE_SUSPENDED"]
RECONCILIATION_STATUSES = ["PENDING", "MATCHED", "ACCEPTED_WITH_VARIANCE"]
AFFILIATE_TARGET_STATUSES = ["SUSPENDED", "ACTIVE", "TERMINATED"]


# ---------------------------------------------------------------------------
# Body validation helpers -- every failure is rule 14 (ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def _missing(payload, name):
    return name not in payload or payload[name] is None


def opt_raw(payload, name):
    """Return the raw value only when the key was supplied and is not null."""
    if _missing(payload, name):
        return None
    return payload[name]


def get_str(payload, name, required=True, default=None, min_len=None,
            max_len=None, prefix=None, exact_len=None):
    if _missing(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if exact_len is not None and len(value) != exact_len:
        fail("ERR_INVALID_REQUEST",
             "%s must be exactly %d characters" % (name, exact_len))
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST",
             "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST",
             "%s must be at most %d characters" % (name, max_len))
    if prefix is not None and not value.startswith(prefix):
        fail("ERR_INVALID_REQUEST", "%s must start with %s" % (name, prefix))
    return value


def get_int(payload, name, required=True, default=None, min_v=None, max_v=None):
    if _missing(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if min_v is not None and value < min_v:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d" % (name, min_v))
    if max_v is not None and value > max_v:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d" % (name, max_v))
    return value


def get_bool(payload, name, required=True, default=None):
    if _missing(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def get_enum(payload, name, allowed, required=True, default=None):
    value = get_str(payload, name, required=required, default=default)
    if value is None:
        return default
    if value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def get_enum_list(payload, name, allowed, required=True, non_empty=True,
                  default=None):
    if _missing(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST",
                 "%s entries must be one of %s" % (name, ", ".join(allowed)))
    return list(value)


def get_str_list(payload, name, required=True, non_empty=True, default=None):
    if _missing(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str) or len(item) == 0:
            fail("ERR_INVALID_REQUEST", "%s entries must be non-empty strings" % name)
    return list(value)


def get_instant(payload, name, required=True, default=None):
    if _missing(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp" % name)
    return parsed


def get_id(payload, name, required=True):
    """Reference fields are validated for shape at rule 14, but their existence
    lookup runs earlier in the precedence order, so callers read the raw value
    first with opt_raw() and only then call this for the shape check."""
    if _missing(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return None
    value = payload[name]
    if not isinstance(value, str) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return value


def query_filter(rows, field, param=None):
    """Simple equality filter on a list query parameter."""
    value = request.args.get(param or field)
    if value is None or value == "":
        return rows
    return [r for r in rows if r.get(field) == value]
