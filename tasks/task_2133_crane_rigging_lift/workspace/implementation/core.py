"""Foundation: logical clock, in-memory store, rounding, error type, envelope."""
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from flask import jsonify

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = ["Dispatcher", "LiftDirector", "Engineer", "Operator",
         "SafetyManager", "BillingClerk", "Customer"]

# ------------------------------------------------------------------ errors ---
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_NOT_ASSIGNED_OPERATOR": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_CRANE_NOT_FOUND": 404,
    "ERR_PERSONNEL_NOT_FOUND": 404,
    "ERR_GEAR_NOT_FOUND": 404,
    "ERR_LIFT_PLAN_NOT_FOUND": 404,
    "ERR_GEAR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_STANDBY_EVENT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_GEAR_VERSION": 412,
    "ERR_INVALID_PLAN_STATE": 409,
    "ERR_INVALID_FIELD_STATE": 409,
    "ERR_INVALID_GEAR_STATE": 409,
    "ERR_INVALID_REVIEW_STATE": 409,
    "ERR_INVALID_PERMIT_STATE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_CRANE_OUT_OF_SERVICE": 409,
    "ERR_GEAR_NOT_SERVICEABLE": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_PLAN_NOT_PENDING_ENGINEERING": 409,
    "ERR_PERSONNEL_ROLE_MISMATCH": 422,
    "ERR_OPERATOR_CERT_EXPIRED": 422,
    "ERR_OPERATOR_ENDORSEMENT_INSUFFICIENT": 422,
    "ERR_RIGGER_QUALIFICATION_INSUFFICIENT": 422,
    "ERR_NO_RIGGING_ASSIGNED": 422,
    "ERR_LOAD_CHART_NO_ROW": 422,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_SLING_WLL_EXCEEDED": 422,
    "ERR_WIND_BELOW_HOLD_THRESHOLD": 422,
    "ERR_CRANE_WINDOW_CONFLICT": 409,
    "ERR_OPERATOR_HOURS_EXCEEDED": 409,
    "ERR_DUPLICATE_GEAR_TAG": 409,
    "ERR_DUPLICATE_CHART_ROW": 409,
    "ERR_DUPLICATE_GEAR_ASSIGNMENT": 409,
    "ERR_JURISDICTION_MISMATCH": 422,
    "ERR_PERMIT_LEAD_TIME_SHORT": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_CUSTOMER_CREDIT_HOLD": 402,
    "ERR_LUMP_SUM_REQUIRED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ----------------------------------------------------------------- rounding --
def _dec(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(value, places=0):
    """Round half up; returns Decimal."""
    q = Decimal(1).scaleb(-places)
    return _dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def rhu_f(value, places):
    return float(rhu(value, places))


def dfloor(value):
    return int(_dec(value).to_integral_value(rounding=ROUND_FLOOR))


def dceil(value):
    return int(_dec(value).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------- datetimes --
def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hours_between(a, b):
    return Decimal((b - a).total_seconds()) / Decimal(3600)


# -------------------------------------------------------------------- store --
class Store(object):
    COLLECTIONS = ["customers", "sites", "cranes", "load_chart_entries", "personnel",
                   "rigging_gear", "gear_inspections", "lift_plans", "gear_assignments",
                   "engineering_reviews", "permits", "standby_events", "invoices"]

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.now = CLOCK_START

    def seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())

    def now_iso(self):
        return fmt_dt(self.now)


store = Store()


def ordered(collection, key=None):
    rows = list(collection.values())
    if key:
        rows = [r for r in rows if key(r)]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def wall_now():
    """created_at / updated_at are wall-clock stamps; the logical clock drives comparisons."""
    return fmt_dt(datetime.now(timezone.utc))


def new_record(extra=None, common=True):
    rec = {"id": store.new_id(), "created_at": wall_now(), "_seq": store.seq()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    rec["updated_at"] = wall_now()
    rec["version"] = rec.get("version", 1) + 1


# ----------------------------------------------------------------- envelope --
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def respond_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_error(error_id, message, status):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status
