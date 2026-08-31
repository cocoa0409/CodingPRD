"""Foundation: logical clock, in-memory store, response envelope, errors, auth ladder."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------- roles
ROLE_FIRM = "FirmRecallOfficer"
ROLE_COORD = "RecallCoordinator"
ROLE_PANEL = "HealthHazardPanel"
ROLE_FIELD = "FieldInvestigator"
ROLE_ADJ = "InsuranceAdjuster"
ALL_ROLES = [ROLE_FIRM, ROLE_COORD, ROLE_PANEL, ROLE_FIELD, ROLE_ADJ]
ROLE_SET = set(ALL_ROLES)

# ---------------------------------------------------------------- errors
ERROR_HTTP = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_FIRM_NOT_FOUND": 404,
    "ERR_RECALL_NOT_FOUND": 404,
    "ERR_CONSIGNEE_NOT_FOUND": 404,
    "ERR_SUBRESOURCE_NOT_FOUND": 404,
    "ERR_FIRM_SCOPE_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_RECALL_VERSION": 412,
    "ERR_STALE_CONSIGNEE_VERSION": 412,
    "ERR_INVALID_RECALL_STATE": 409,
    "ERR_INVALID_EVALUATION_STATE": 409,
    "ERR_INVALID_WARNING_STATE": 409,
    "ERR_INVALID_DISPOSITION_STATE": 409,
    "ERR_INVALID_NOTIFICATION_STATE": 409,
    "ERR_INVALID_ACCOUNTING_STATE": 409,
    "ERR_INVALID_REPORT_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_COST_ENTRY_STATE": 409,
    "ERR_NO_RATIFIED_EVALUATION": 409,
    "ERR_PUBLIC_WARNING_NOT_WARRANTED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CONSIGNEE_NOT_ON_DISTRIBUTION_LIST": 422,
    "ERR_DISTRIBUTION_LIST_INCOMPLETE": 409,
    "ERR_NOTIFICATION_COOLING_OFF": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_ACTIVE_NOTIFICATION": 409,
    "ERR_OPEN_DISPOSITION_ORDERS": 409,
    "ERR_CONSIGNEE_TIER_LIMIT": 422,
    "ERR_QUANTITY_EXCEEDS_SHIPPED": 422,
    "ERR_DISPOSITION_EXCEEDS_ACCOUNTED_UNITS": 422,
    "ERR_EFFECTIVENESS_BELOW_TERMINATION_THRESHOLD": 422,
    "ERR_CLAIM_EXCEEDS_POLICY_AGGREGATE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------- clock / time
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- store
class Store:
    """Pure in-memory store. Starts completely empty on every boot."""

    def __init__(self):
        self.firms = {}
        self.recalls = {}
        self.hazard_evaluations = {}
        self.consignees = {}
        self.distribution_records = {}
        self.notifications = {}
        self.retrieval_receipts = {}
        self.public_warnings = {}
        self.disposition_orders = {}
        self.status_reports = {}
        self.cost_entries = {}
        self.insurance_claims = {}
        self.seq = 0
        self.clock = CLOCK_DEFAULT


db = Store()


def now():
    return db.clock


def now_iso():
    return iso(db.clock)


def new_row(collection, **fields):
    db.seq += 1
    stamp = now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.seq,
    }
    row.update(fields)
    collection[row["id"]] = row
    fresh = getattr(g, "fresh_rows", None)
    if fresh is None:
        fresh = set()
        g.fresh_rows = fresh
    fresh.add(id(row))
    return row


# ---------------------------------------------------------------- dirty tracking
def _dirty_map():
    d = getattr(g, "dirty_rows", None)
    if d is None:
        d = {}
        g.dirty_rows = d
    return d


def mark_dirty(row):
    if row is not None:
        _dirty_map()[id(row)] = row


def upd(row, **fields):
    """Assign fields; mark the row dirty only when something actually changed."""
    changed = False
    for key, value in fields.items():
        if row.get(key, "\0__missing__") != value:
            row[key] = value
            changed = True
    if changed:
        mark_dirty(row)
    return changed


def flush():
    rows = _dirty_map()
    if not rows:
        return
    stamp = now_iso()
    fresh = getattr(g, "fresh_rows", None) or set()
    for key, row in rows.items():
        if key in fresh:
            continue  # rows created during this request stay at version 1
        row["version"] = int(row.get("version", 1)) + 1
        row["updated_at"] = stamp
    g.dirty_rows = {}


# ---------------------------------------------------------------- envelope
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
    real = datetime.now(timezone.utc)
    return {"api_request_id": rid, "api_request_timestamp": iso(real)}


def public(row):
    """Serialize a row for the response. Flushes pending version bumps first so the
    payload always reflects the post-mutation `version` and `updated_at`."""
    flush()
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    flush()
    payload = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(payload), status


def created(data):
    return ok(data, 201)


def listing(rows, total, limit, offset):
    flush()
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(rows)) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(error_id, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), ERROR_HTTP.get(error_id, 400)


# ---------------------------------------------------------------- rung 1 + 2
def auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        err("ERR_MISSING_AUTH_HEADER", "X-User-ID header is required")
    if not role or role not in ROLE_SET:
        err("ERR_MISSING_AUTH_HEADER", "X-User-Role header must be one of the five declared roles")
    if role not in allowed_roles:
        err("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


# ---------------------------------------------------------------- body helpers
def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


MISSING = object()


def req_str(data, key, allow_empty=False):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        err("ERR_INVALID_REQUEST", "%s is required" % key)
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "%s must be a string" % key)
    if not allow_empty and not value.strip():
        err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % key)
    return value


def opt_str(data, key, default=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "%s must be a string" % key)
    return value


def req_enum(data, key, allowed):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        err("ERR_INVALID_REQUEST", "%s is required" % key)
    if not isinstance(value, str) or value not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, sorted(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, sorted(allowed)))
    return value


def _as_int(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    return value


def req_int(data, key, minimum=None, exclusive_min=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        err("ERR_INVALID_REQUEST", "%s is required" % key)
    value = _as_int(value, key)
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", "%s must be >= %s" % (key, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        err("ERR_INVALID_REQUEST", "%s must be > %s" % (key, exclusive_min))
    return value


def opt_int(data, key, default=None, minimum=None, exclusive_min=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        return default
    value = _as_int(value, key)
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", "%s must be >= %s" % (key, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        err("ERR_INVALID_REQUEST", "%s must be > %s" % (key, exclusive_min))
    return value


def opt_bool(data, key, default=False):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, bool):
        err("ERR_INVALID_REQUEST", "%s must be a boolean" % key)
    return value


def req_datetime(data, key):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        err("ERR_INVALID_REQUEST", "%s is required" % key)
    parsed = parse_iso(value)
    if parsed is None:
        err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant" % key)
    return value, parsed


# ---------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def paginate(rows):
    limit, offset = pagination()
    rows = sorted(rows, key=sort_key)
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([public(r) for r in page], total, limit, offset)


def filter_exact(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if str(r.get(field)) == str(value)]


# ---------------------------------------------------------------- rounding
def rhu(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    return int(rhu(Decimal(value), 0))


def pct(value):
    return float(rhu(Decimal(value), 2))


def ceil_div(numerator, denominator):
    return -((-int(numerator)) // int(denominator))


def add_days(dt, days):
    return dt + timedelta(days=days)
