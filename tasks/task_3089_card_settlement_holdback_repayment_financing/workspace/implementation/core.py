"""Core infrastructure: in-memory store, errors, envelope, auth, calculations."""
import math
import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_START = datetime(2026, 9, 1, 0, 0, 0)
_logical_clock = _CLOCK_START


def clock_now():
    return _logical_clock


def clock_set(dt):
    global _logical_clock
    _logical_clock = dt


# ---------------------------------------------------------------------------
# Timestamps / ids
# ---------------------------------------------------------------------------

def ts_now():
    """Logical-clock ISO8601 UTC with three fractional digits (PRD 2.4)."""
    dt = clock_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_ts_now():
    dt = datetime.utcnow()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(18))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def success_object(data, code=200):
    return jsonify({
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_ts_now(),
        },
        "response_type": "object",
        "data": data,
    }), code


def success_list(items, total_count, limit, offset, code=200):
    return jsonify({
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_ts_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        },
        "response_type": "array",
        "data": items,
    }), code


def error_body(api_error):
    return jsonify({
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_ts_now(),
        },
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }), api_error.http_status


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range")
    if offset < 0:
        raise err_invalid_request("offset out of range")
    return limit, offset


def paginate(records, limit, offset):
    """records: list of dicts already sorted by created_at ascending."""
    total = len(records)
    page = records[offset:offset + limit]
    return success_list(page, total, limit, offset)


# ---------------------------------------------------------------------------
# In-memory store (module-level dicts; fresh per process, no seeding)
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.merchants = {}
        self.batches = {}
        self.offers = {}
        self.loans = {}
        self.guarantors = {}
        self.disclosures = {}
        self.sweeps = {}
        self.catchups = {}
        self.enforcements = {}
        self.banks = {}
        self.sales = {}
        self.signals = {}


DB = Store()


def touch(entity):
    entity["updated_at"] = ts_now()
    entity["version"] += 1


def new_common():
    t = ts_now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, 2.7 priority 1-2)
# ---------------------------------------------------------------------------

ROLES = {"PlatformAdmin", "Underwriter", "ServicerAgent", "MerchantOwner",
         "GuarantorPrincipal", "BankOfficer", "Auditor"}
ALL_ROLES = sorted(ROLES)

_id_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]*$")


def auth(allowed_roles):
    """Priority 1: headers present & well-formed. Priority 2: role allowed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or not _id_re.match(uid) or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-ID or X-User-Role header missing or malformed", 400)
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Caller role not permitted for this endpoint", 403)
    return uid, role


# ---------------------------------------------------------------------------
# Money / ratio helpers (PRD 2.5)
# ---------------------------------------------------------------------------

def round_half_up_int(value):
    """value: Decimal or Fraction-like; return int rounded half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ratio4(num, den):
    if den == 0:
        return 0.0
    d = (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(d)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_iso8601(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1]
    return datetime.fromisoformat(s2)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    d = datetime.strptime(s.strip(), "%Y-%m-%d").date()
    if s.strip() != d.isoformat():
        raise ValueError("not YYYY-MM-DD")
    return d


# ---------------------------------------------------------------------------
# Merchant aggregates (PRD 3.1 / calculation merchant_aggregates)
# ---------------------------------------------------------------------------

def merchant_batches_included(merchant):
    return [b for b in DB.batches.values()
            if b["merchant_id"] == merchant["id"] and b["status"] in ("FINALIZED", "SWEPT")]


def recompute_merchant_aggregates(merchant):
    batches = merchant_batches_included(merchant)
    clock = clock_now()
    clock_date = clock.date()

    lifetime = sum(b["net_settled_cents"] for b in batches)

    # trailing 12m: closed window [clock-365d, clock]
    w12_start = clock_date - timedelta(days=365)
    monthly = {}
    for b in batches:
        d = parse_date(b["processing_date"])
        if w12_start <= d <= clock_date:
            key = (d.year, d.month)
            monthly[key] = monthly.get(key, 0) + b["net_settled_cents"]
    months_recorded = len(monthly)

    if months_recorded == 0:
        seasonality = 0.0
    else:
        vals = list(monthly.values())
        avg = Decimal(sum(vals)) / Decimal(months_recorded)
        idx = (Decimal(max(vals)) - Decimal(min(vals))) / avg
        seasonality = float(idx.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    w30_start = clock_date - timedelta(days=30)
    w60_start = clock_date - timedelta(days=60)
    trailing30 = 0
    prior30 = 0
    cb30 = 0
    for b in batches:
        d = parse_date(b["processing_date"])
        if w30_start <= d < clock_date:
            trailing30 += b["net_settled_cents"]
            cb30 += b["chargebacks_cents"]
        elif w60_start <= d < w30_start:
            prior30 += b["net_settled_cents"]

    merchant["lifetime_net_cents"] = lifetime
    merchant["trailing_12m_months_recorded"] = months_recorded
    merchant["seasonality_index"] = seasonality
    merchant["trailing_30d_net_cents"] = trailing30
    merchant["prior_30d_net_cents"] = prior30
    merchant["trailing_30d_chargeback_ratio"] = ratio4(cb30, trailing30)


def merchant_avg_month_net(merchant):
    """Exact average monthly net (Decimal) over trailing 12m set, or None."""
    batches = merchant_batches_included(merchant)
    clock = clock_now()
    clock_date = clock.date()
    w12_start = clock_date - timedelta(days=365)
    monthly = {}
    for b in batches:
        d = parse_date(b["processing_date"])
        if w12_start <= d <= clock_date:
            key = (d.year, d.month)
            monthly[key] = monthly.get(key, 0) + b["net_settled_cents"]
    if not monthly:
        return None
    return Decimal(sum(monthly.values())) / Decimal(len(monthly))


# ---------------------------------------------------------------------------
# Offer pre-approval (PRD 3.2 / calculation offer_preapproval)
# ---------------------------------------------------------------------------

OFFER_MONTHS_MULT = Decimal("1.25")
CONSERVATIVE_HAIRCUT = Decimal("0.70")
SEASONALITY_THRESHOLD = Decimal("0.75")
OFFER_ROUND_STEP_CENTS = 50000
MIN_MONTHS_RECORDED = 12


def compute_offer_amounts(merchant):
    avg = merchant_avg_month_net(merchant)  # exact Decimal
    avg_cents = int(avg)  # truncate toward zero to whole cents
    base = Decimal(avg_cents) * OFFER_MONTHS_MULT
    standard_raw = base
    conservative_raw = base * CONSERVATIVE_HAIRCUT
    standard = int(standard_raw) // OFFER_ROUND_STEP_CENTS * OFFER_ROUND_STEP_CENTS
    conservative = int(conservative_raw) // OFFER_ROUND_STEP_CENTS * OFFER_ROUND_STEP_CENTS
    seasonality = merchant["seasonality_index"]
    if Decimal(str(seasonality)) > SEASONALITY_THRESHOLD:
        selected = conservative
    else:
        selected = standard
    return {
        "trailing_12m_avg_net_cents": avg_cents,
        "seasonality_index_at_generation": seasonality,
        "preapproved_standard_cents": standard,
        "preapproved_conservative_cents": conservative,
        "preapproved_cents": selected,
    }


# ---------------------------------------------------------------------------
# Loan fee (PRD 3.3 / calculation loan_fee_and_minimum)
# ---------------------------------------------------------------------------

def compute_loan_terms(principal_cents):
    if principal_cents <= 2500000:
        fee_rate = Decimal("0.11")
    elif principal_cents <= 10000000:
        fee_rate = Decimal("0.13")
    else:
        fee_rate = Decimal("0.15")
    fee_cents = int((Decimal(principal_cents) * fee_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total = principal_cents + fee_cents
    minimum = total // 18
    return fee_rate, fee_cents, total, minimum


# ---------------------------------------------------------------------------
# Disclosure APR (PRD 3.3 / calculation disclosure_apr_equivalent)
# ---------------------------------------------------------------------------

SCHEDULED_TERM_DAYS = 1080
PACE_WINDOW_DAYS = 90


def compute_disclosure(merchant, fee_rate, holdback_pct, total_repayment_cents):
    clock = clock_now()
    accept_day = clock.date()
    start = accept_day - timedelta(days=PACE_WINDOW_DAYS)
    batches = merchant_batches_included(merchant)
    window_sum = 0
    for b in batches:
        d = parse_date(b["processing_date"])
        if start <= d <= accept_day:
            window_sum += b["net_settled_cents"]
    daily_pace = (Decimal(window_sum) / Decimal(PACE_WINDOW_DAYS)) * Decimal(str(holdback_pct))

    apr_scheduled = (fee_rate * Decimal(365) / Decimal(SCHEDULED_TERM_DAYS)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)

    if daily_pace <= 0:
        projected_term_days = SCHEDULED_TERM_DAYS
    else:
        projected_term_days = int(math.ceil(Decimal(total_repayment_cents) / daily_pace))
    apr_projected = (fee_rate * Decimal(365) / Decimal(projected_term_days)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)

    return {
        "apr_scheduled": float(apr_scheduled),
        "apr_projected": float(apr_projected),
        "projected_term_days": projected_term_days,
    }


# ---------------------------------------------------------------------------
# Body validation helpers (PRD 2.7 priority 11)
# ---------------------------------------------------------------------------

def get_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    if required and not body:
        # an empty object may still be valid for some endpoints; callers decide
        pass
    return body


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request("Missing or invalid field: %s" % field)
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is not None and not isinstance(v, str):
        raise err_invalid_request("Invalid field: %s" % field)
    return v


def req_cents(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise err_invalid_request("Missing or invalid non-negative integer field: %s" % field)
    return v


def opt_cents(body, field, default=0):
    v = body.get(field, default)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise err_invalid_request("Invalid non-negative integer field: %s" % field)
    return v


def req_state_code(body, field="state_code"):
    v = body.get(field)
    if not isinstance(v, str) or not re.match(r"^[A-Z]{2}$", v):
        raise err_invalid_request("state_code must be two uppercase letters")
    return v


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request("Missing or invalid numeric field: %s" % field)
    return v
