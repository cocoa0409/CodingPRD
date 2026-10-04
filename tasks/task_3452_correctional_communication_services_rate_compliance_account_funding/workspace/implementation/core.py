"""Core primitives: errors, logical clock, in-memory storage, envelope, auth.

All structural names (headers, envelope fields, pagination params, error ids)
are taken from SCAFFOLD.yaml / PRD.md:
  - auth headers: X-User-ID / X-User-Role (PRD section 2.1)
  - envelope: meta.api_request_id / meta.api_request_timestamp / response_type /
    data; error body data.error_id / data.message (PRD section 2.2)
  - pagination: limit / offset / total_count / has_more, defaults 10 / 0,
    min 1, max 100 (PRD section 2.3)
  - logical clock default 2026-09-01T00:00:00Z, no wall-clock fallback (PRD 2.4)
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify, request


# ----------------------------------------------------------------- errors ---
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# ------------------------------------------------------------------ clock ---
DEFAULT_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    """Server-side logical clock; never falls back to wall-clock time."""

    def __init__(self):
        self._now = DEFAULT_START

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = _Clock()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field="datetime"):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400,
            "Field '%s' must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400,
            "Field '%s' is not a parseable datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400,
            "Field '%s' must be a YYYY-MM-DD date string" % field)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        err("ERR_INVALID_REQUEST", 400,
            "Field '%s' is not a parseable date" % field)


# ---------------------------------------------------------------- storage ---
class DB:
    """Process-local in-memory store; empty at every boot (no seeding)."""

    facilities = {}
    caps = {}
    contracts = {}
    schedules = {}
    inmates = {}
    accounts = {}
    ledger = {}  # account_id -> [FundingTransaction], append-only
    recipients = {}
    calls = {}
    sessions = {}
    messages = {}
    refunds = {}
    complaints = {}
    seq = 0


def next_seq():
    DB.seq += 1
    return DB.seq


def new_entity():
    """Common fields for every primary resource (PRD section 2.5)."""
    now = CLOCK.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def new_ledger_entry(account_id, type_, amount, reference_id, note, group=None):
    """FundingTransaction: only id + created_at of the common set (append-only)."""
    entry = {
        "id": str(uuid.uuid4()),
        "created_at": CLOCK.now(),
        "_seq": next_seq(),
        "account_id": account_id,
        "type": type_,
        "amount_cents": amount,
        "reference_id": reference_id,
        "note": note,
    }
    if group is not None:
        entry["_group"] = group
    return entry


def touch(entity):
    entity["updated_at"] = CLOCK.now()
    entity["version"] += 1


def pub(entity):
    """Serialize: strip internal '_'-keys, format datetimes."""
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out


def append_ledger(account, type_, amount, reference_id=None, note="", group=None):
    """Append a FundingTransaction row.

    Deliberately does NOT touch the account: a ledger row is its own
    (versionless) resource, and PRD section 2.5/2.7 pin the account's
    version to advance by exactly one per mutation request — a request that
    appends several rows (deposit, remittance, disbursement) is still one
    mutation. The request handler calls touch(account) once.
    """
    entry = new_ledger_entry(account["id"], type_, amount, reference_id, note, group)
    DB.ledger.setdefault(account["id"], []).append(entry)
    return entry


def ledger_of(account_id):
    return DB.ledger.get(account_id, [])


def balance_of(account_id):
    return sum(e["amount_cents"] for e in ledger_of(account_id))


def settled_totals(account_id):
    """Magnitudes of REFUND_PAYOUT and ESCHEAT_REMITTANCE already on the ledger."""
    refunded = 0
    escheated = 0
    for entry in ledger_of(account_id):
        if entry["type"] == "REFUND_PAYOUT":
            refunded += -entry["amount_cents"]
        elif entry["type"] == "ESCHEAT_REMITTANCE":
            escheated += -entry["amount_cents"]
    return refunded, escheated


def new_verification_code():
    return "%06d" % random.randint(0, 999999)


def new_group():
    return str(uuid.uuid4())


# --------------------------------------------------------------- envelope ---
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(CLOCK.now()),
    }


def ok_obj(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


# ------------------------------------------------------------------- auth ---
ROLES = (
    "PlatformAdmin",
    "StateRegulator",
    "FacilityStaff",
    "AccountHolder",
    "RecipientParty",
    "ComplianceOfficer",
)
ALL_ROLES = list(ROLES)


def auth(allowed):
    """Tiers 1-2: header presence/validity, then role authorization."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers are required and the role must "
            "be one of the six declared roles")
    if role not in allowed:
        err("ERR_FORBIDDEN_FOR_ROLE", 403,
            "Role %s is not authorized for this endpoint" % role)
    return user_id, role


# ---------------------------------------------------------------- request ---
def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def req_field(data, name):
    value = data.get(name)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
    return value


def req_str(data, name):
    value = req_field(data, name)
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % name)
    return value


def opt_str(data, name, default=None):
    value = data.get(name)
    if value is None:
        return default
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % name)
    return value


def req_int(data, name, minimum=None):
    value = req_field(data, name)
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", 400,
            "Field %s must be >= %d" % (name, minimum))
    return value


def opt_int(data, name, default=None, minimum=None):
    value = data.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", 400,
            "Field %s must be >= %d" % (name, minimum))
    return value


def req_num(data, name):
    value = req_field(data, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a number" % name)
    return value


def req_enum(data, name, values):
    value = req_field(data, name)
    if value not in values:
        err("ERR_INVALID_REQUEST", 400,
            "Field %s must be one of %s" % (name, ", ".join(values)))
    return value


def req_dt(data, name):
    return parse_dt(req_field(data, name), name)


def opt_dt(data, name):
    value = data.get(name)
    if value is None:
        return None
    return parse_dt(value, name)


# ------------------------------------------------------------ pagination ----
def paginate(items):
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "limit and offset must be integers")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset


def list_response(items, serialize):
    page, total, limit, offset = paginate(items)
    return ok_list([serialize(e) for e in page], total, limit, offset)


def apply_filters(items, names):
    out = list(items)
    for name in names:
        value = request.args.get(name)
        if value is not None:
            out = [e for e in out if str(e.get(name)) == value]
    return out
