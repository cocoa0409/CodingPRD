"""Core infrastructure: logical clock, in-memory store, errors, envelope, auth."""
import os
import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

API_PREFIX = "/deposit-fraud"

ROLES = {
    "OperationsAdmin",
    "FraudAnalyst",
    "FraudSupervisor",
    "BsaOfficer",
    "LegalCounsel",
    "AccountHolder",
}

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_ACCOUNT_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_FUNDING_SOURCE_NOT_FOUND": 404,
    "ERR_DEPOSIT_ITEM_NOT_FOUND": 404,
    "ERR_CHECK_HOLD_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_FRAUD_CASE_NOT_FOUND": 404,
    "ERR_CHARGE_OFF_NOT_FOUND": 404,
    "ERR_SUBPOENA_NOT_FOUND": 404,
    "ERR_BSA_REFERRAL_NOT_FOUND": 404,
    "ERR_STALE_CHECK_HOLD_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_SELF_LINK": 422,
    "ERR_DUPLICATE_LINK": 409,
    "ERR_DUPLICATE_OPEN_CASE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_ACCESS_LOCKED": 409,
    "ERR_STEP_UP_NOT_REQUIRED": 409,
    "ERR_FUNDING_INVALID_STATE": 409,
    "ERR_ITEM_ALREADY_SETTLED": 409,
    "ERR_HOLD_NOT_ACTIVE": 409,
    "ERR_HOLD_ALREADY_MATURED": 422,
    "ERR_RELEASE_WINDOW_OVERLAP": 409,
    "ERR_RELEASE_EXCEEDS_HOLD": 422,
    "ERR_REVIEW_NOT_SUBMITTED": 409,
    "ERR_REVIEW_NOT_APPROVED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_EXPOSURE_EXCEEDS_AUTHORITY": 422,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_CASE_NOT_SUBSTANTIATED": 409,
    "ERR_PRESERVATION_HOLD_ACTIVE": 409,
    "ERR_BSA_REFERRAL_REQUIRED": 409,
    "ERR_REFERRAL_INVALID_STATE": 409,
    "ERR_PRESERVATION_WINDOW_CONFLICT": 409,
    "ERR_SUBPOENA_INVALID_STATE": 409,
    "ERR_LATE_JUSTIFICATION_REQUIRED": 422,
    "ERR_ACCOUNT_NOT_CLOSED": 409,
    "ERR_CHARGE_OFF_INVALID_STATE": 409,
    "ERR_NO_NET_LOSS": 422,
    "ERR_RECOVERY_EXCEEDS_LOSS": 422,
    "ERR_RECOVERY_ALREADY_POSTED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.customers = {}
        self.accounts = {}
        self.funding_sources = {}
        self.account_links = {}
        self.deposit_items = {}
        self.check_holds = {}
        self.override_reviews = {}
        self.fraud_cases = {}
        self.charge_offs = {}
        self.subpoenas = {}
        self.bsa_referrals = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns aware datetime or None if invalid."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    try:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute, sec = int(m.group(4)), int(m.group(5)), int(m.group(6))
        frac = m.group(7) or ".0"
        micro = int(round(float(frac) * 1000000))
        if micro > 999999:
            micro = 999999
        off = m.group(8)
        if off in ("Z", "z"):
            delta = timedelta(0)
        else:
            sign = 1 if off[0] == "+" else -1
            body = off[1:].replace(":", "")
            delta = sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = datetime(year, month, day, hour, minute, sec, micro, tzinfo=timezone.utc)
        return dt - delta
    except (ValueError, OverflowError):
        return None


def base_row(kind_seq=True):
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()


def round_half_up(value):
    """value: Decimal or Fraction-like. Returns int, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps(amount_cents, rate_bps):
    return round_half_up(Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10000))


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _request_meta():
    rid = "req_" + "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(20)
    )
    real = datetime.now(timezone.utc)
    return {
        "api_request_id": rid,
        "api_request_timestamp": real.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (real.microsecond // 1000),
    }


def ok(data, status=200):
    body = {
        "meta": _request_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def endpoint(roles):
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                user_id = request.headers.get("X-User-ID")
                user_role = request.headers.get("X-User-Role")
                if not user_id or not user_role or user_role not in ROLES:
                    raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid credentials.")
                if user_role not in allowed:
                    raise ApiError(
                        "ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % user_role
                    )
                g.user_id = user_id
                g.user_role = user_role
                return fn(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Lookup helpers (path existence, left to right)
# --------------------------------------------------------------------------
def _get(coll, rid, err):
    row = coll.get(rid)
    if row is None:
        raise ApiError(err, "Resource %s not found." % rid)
    return row


def get_customer(rid):
    return _get(db.customers, rid, "ERR_CUSTOMER_NOT_FOUND")


def get_account(rid):
    return _get(db.accounts, rid, "ERR_ACCOUNT_NOT_FOUND")


def get_funding_source(rid):
    return _get(db.funding_sources, rid, "ERR_FUNDING_SOURCE_NOT_FOUND")


def get_deposit_item(rid):
    return _get(db.deposit_items, rid, "ERR_DEPOSIT_ITEM_NOT_FOUND")


def get_check_hold(rid):
    return _get(db.check_holds, rid, "ERR_CHECK_HOLD_NOT_FOUND")


def get_review(rid):
    return _get(db.override_reviews, rid, "ERR_REVIEW_NOT_FOUND")


def get_fraud_case(rid):
    return _get(db.fraud_cases, rid, "ERR_FRAUD_CASE_NOT_FOUND")


def get_charge_off(rid):
    return _get(db.charge_offs, rid, "ERR_CHARGE_OFF_NOT_FOUND")


def get_subpoena(rid):
    return _get(db.subpoenas, rid, "ERR_SUBPOENA_NOT_FOUND")


def get_bsa_referral(rid):
    return _get(db.bsa_referrals, rid, "ERR_BSA_REFERRAL_NOT_FOUND")


# --------------------------------------------------------------------------
# Body / query validation (rank 4 of the ladder)
# --------------------------------------------------------------------------
def body():
    if request.data in (None, b"", ""):
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return data


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def req_present_str(data, field):
    """Present and of declared type; no non-blank rule (PRD states none)."""
    if field not in data or data[field] is None:
        bad("Missing required field %s." % field)
    v = data[field]
    if not isinstance(v, str):
        bad("%s must be a string." % field)
    return v


def req_str(data, field, minlen=1, maxlen=None):
    if field not in data or data[field] is None:
        bad("Missing required field %s." % field)
    v = data[field]
    if not isinstance(v, str):
        bad("%s must be a string." % field)
    if len(v.strip()) < minlen:
        bad("%s must be non-blank." % field)
    if maxlen is not None and len(v) > maxlen:
        bad("%s exceeds %d characters." % (field, maxlen))
    if minlen > 0 and len(v) < minlen:
        bad("%s is too short." % field)
    return v


def opt_str(data, field, maxlen=None, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        bad("%s must be a string." % field)
    if maxlen is not None and len(v) > maxlen:
        bad("%s exceeds %d characters." % (field, maxlen))
    return v


def req_enum(data, field, allowed):
    if field not in data or data[field] is None:
        bad("Missing required field %s." % field)
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        bad("%s must be one of %s." % (field, sorted(allowed)))
    return v


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        bad("%s must be one of %s." % (field, sorted(allowed)))
    return v


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        bad("Missing required field %s." % field)
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        bad("%s must be an integer." % field)
    if minimum is not None and v < minimum:
        bad("%s must be >= %d." % (field, minimum))
    if maximum is not None and v > maximum:
        bad("%s must be <= %d." % (field, maximum))
    return v


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        bad("%s must be an integer." % field)
    if minimum is not None and v < minimum:
        bad("%s must be >= %d." % (field, minimum))
    if maximum is not None and v > maximum:
        bad("%s must be <= %d." % (field, maximum))
    return v


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        bad("%s must be a boolean." % field)
    return v


def req_dt(data, field):
    if field not in data or data[field] is None:
        bad("Missing required field %s." % field)
    dt = parse_iso(data[field])
    if dt is None:
        bad("%s must be an ISO 8601 UTC timestamp." % field)
    return dt


def req_id(data, field):
    if field not in data or data[field] is None:
        bad("Missing required field %s." % field)
    v = data[field]
    if not isinstance(v, str) or not v.strip():
        bad("%s must be a non-empty string." % field)
    return v


def opt_id(data, field):
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if not isinstance(v, str) or not v.strip():
        bad("%s must be a non-empty string." % field)
    return v


DIGITS4 = re.compile(r"^[0-9]{4}$")


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if not re.match(r"^-?\d+$", raw or ""):
            bad("limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if not re.match(r"^-?\d+$", raw or ""):
            bad("offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            bad("offset must be >= 0.")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("%s must be one of %s." % (name, sorted(allowed)))
    return raw


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset : offset + limit]
    return [serializer(r) for r in page], total
