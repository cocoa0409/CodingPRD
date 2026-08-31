"""Shared infrastructure: in-memory store, envelope, auth, validation helpers."""
import random
import re
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from functools import wraps

from flask import request, jsonify, g

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "DesignLead",
    "PlanChecker",
    "ProjectManager",
    "Homeowner",
    "BuildingInspector",
    "FinanceAdvisor",
)
ALL_ROLES = ROLES

# --------------------------------------------------------------------------
# Error catalogue
# --------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_PROJECT_OWNER": 403,
    "ERR_NOT_ASSIGNED_INSPECTOR": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 422,
    "ERR_EMPTY_CHANGE_ORDER": 422,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_SCREENING_NOT_FOUND": 404,
    "ERR_SUBMITTAL_NOT_FOUND": 404,
    "ERR_CORRECTION_ITEM_NOT_FOUND": 404,
    "ERR_UTILITY_CONNECTION_NOT_FOUND": 404,
    "ERR_FINANCING_SCENARIO_NOT_FOUND": 404,
    "ERR_CHANGE_ORDER_NOT_FOUND": 404,
    "ERR_PHASE_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_STALE_PROPERTY_VERSION": 412,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_PROJECT_PHASE_INVALID": 409,
    "ERR_SUBMITTAL_STATE_INVALID": 409,
    "ERR_CORRECTION_ITEM_STATE_INVALID": 409,
    "ERR_UTILITY_STATE_INVALID": 409,
    "ERR_SCENARIO_STATE_INVALID": 409,
    "ERR_CHANGE_ORDER_STATE_INVALID": 409,
    "ERR_PHASE_STATE_INVALID": 409,
    "ERR_APPOINTMENT_STATE_INVALID": 409,
    "ERR_PATHWAY_NOT_SELECTED": 409,
    "ERR_FEASIBILITY_FAILED": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_INSPECTOR_NOT_CERTIFIED": 409,
    "ERR_INSPECTOR_INACTIVE": 409,
    "ERR_OCCUPIED_HABITABILITY_VIOLATION": 409,
    "ERR_PHASE_DEPENDENCY_INCOMPLETE": 409,
    "ERR_OPEN_INSPECTIONS_REMAIN": 409,
    "ERR_DUPLICATE_JURISDICTION_CODE": 409,
    "ERR_DUPLICATE_UTILITY_SERVICE": 409,
    "ERR_PHASE_WINDOW_CONFLICT": 409,
    "ERR_INSPECTOR_SLOT_CONFLICT": 409,
    "ERR_INSPECTOR_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_CORRECTION_WINDOW_EXPIRED": 409,
    "ERR_NO_CORRECTIONS_ON_RECORD": 409,
    "ERR_BLOCKING_CORRECTIONS_OPEN": 409,
    "ERR_UTILITY_DECISION_PENDING": 409,
    "ERR_TITLE24_MISSING": 409,
    "ERR_CHANGE_CAP_EXCEEDED": 409,
    "ERR_FUNDING_GAP_OPEN": 409,
    "ERR_CERTIFICATE_ALREADY_ISSUED": 409,
    "ERR_UTILITY_NOT_ENERGIZED": 409,
    "ERR_PHASES_INCOMPLETE": 409,
    "ERR_FINAL_INSPECTION_MISSING": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# In-memory store
# --------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.inspectors = {}
        self.properties = {}
        self.projects = {}
        self.screenings = {}
        self.utilities = {}
        self.submittals = {}
        self.corrections = {}
        self.scenarios = {}
        self.change_orders = {}
        self.phases = {}
        self.appointments = {}
        self.certificates = {}
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.last_dt = None


DB = Store()


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    dt = datetime.now(timezone.utc)
    if DB.last_dt is not None and dt <= DB.last_dt:
        dt = DB.last_dt + timedelta(milliseconds=1)
    DB.last_dt = dt
    return fmt_dt(dt)


def clock_dt():
    return DB.clock


def clock_date():
    return DB.clock.astimezone(timezone.utc).date().isoformat()


def new_row(common=True):
    DB.seq += 1
    ts = now_iso()
    row = {"id": str(uuid.uuid4()), "_seq": DB.seq, "created_at": ts}
    if common:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1


def ser(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_list(rows, limit, offset, total):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(rows)) < total,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authorize(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or str(uid).strip() == "" or role is None or str(role).strip() == "":
                fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role headers are required.")
            if role not in ROLES:
                fail("ERR_UNAUTHENTICATED", "Unrecognized role.")
            if role not in roles:
                fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


# --------------------------------------------------------------------------
# Body / query validation helpers
# --------------------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


_MISSING = object()


def _present(body, key):
    return key in body and body[key] is not None


def v_str(body, key, required=True, default=None, allow_empty=True):
    if not _present(body, key):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % key)
        return default
    val = body[key]
    if not isinstance(val, str):
        fail("ERR_VALIDATION", "Field '%s' must be a string." % key)
    if not allow_empty and val == "":
        fail("ERR_VALIDATION", "Field '%s' must not be empty." % key)
    return val


def v_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % key)
        return default
    val = body[key]
    if not isinstance(val, bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % key)
    return val


def v_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % key)
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        fail("ERR_VALIDATION", "Field '%s' must be an integer." % key)
    if minimum is not None and val < minimum:
        fail("ERR_VALIDATION", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and val > maximum:
        fail("ERR_VALIDATION", "Field '%s' must be <= %s." % (key, maximum))
    return val


def v_num(body, key, required=True, default=None, minimum=None, maximum=None,
          exclusive_min=None, allowed=None):
    if not _present(body, key):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % key)
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        fail("ERR_VALIDATION", "Field '%s' must be a number." % key)
    if minimum is not None and val < minimum:
        fail("ERR_VALIDATION", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and val > maximum:
        fail("ERR_VALIDATION", "Field '%s' must be <= %s." % (key, maximum))
    if exclusive_min is not None and val <= exclusive_min:
        fail("ERR_VALIDATION", "Field '%s' must be > %s." % (key, exclusive_min))
    if allowed is not None and float(val) not in [float(a) for a in allowed]:
        fail("ERR_VALIDATION", "Field '%s' must be one of %s." % (key, allowed))
    return val


def v_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % key)
        return default
    val = body[key]
    if not isinstance(val, str) or val not in allowed:
        fail("ERR_VALIDATION", "Field '%s' must be one of %s." % (key, sorted(allowed)))
    return val


def v_array(body, key, required=True, default=None, item_type=None, non_empty=False):
    if not _present(body, key):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % key)
        return default
    val = body[key]
    if not isinstance(val, list):
        fail("ERR_VALIDATION", "Field '%s' must be an array." % key)
    if non_empty and len(val) == 0:
        fail("ERR_VALIDATION", "Field '%s' must not be empty." % key)
    if item_type is not None:
        for item in val:
            if not isinstance(item, item_type):
                fail("ERR_VALIDATION", "Field '%s' has an element of the wrong type." % key)
    return val


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def v_date(body, key, required=True, default=None):
    val = v_str(body, key, required=required, default=default)
    if val is None:
        return None
    if not DATE_RE.match(val):
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date." % key)
    try:
        date.fromisoformat(val)
    except ValueError:
        fail("ERR_VALIDATION", "Field '%s' must be a valid calendar date." % key)
    return val


def parse_iso_dt(value, key):
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 datetime string." % key)
    text = value.strip()
    normalized = text
    if normalized.endswith("Z") or normalized.endswith("z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 datetime string." % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def v_datetime(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % key)
        return default, None
    raw = body[key]
    dt = parse_iso_dt(raw, key)
    return raw, dt


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total


def listing(rows, serializer=ser):
    limit, offset = pagination()
    rows = by_seq(rows)
    window, total = paginate(rows, limit, offset)
    return ok_list([serializer(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def get_or_404(table, key, error_id):
    row = table.get(key)
    if row is None:
        fail(error_id, "Resource not found.")
    return row


def get_jurisdiction(jid):
    return get_or_404(DB.jurisdictions, jid, "ERR_JURISDICTION_NOT_FOUND")


def get_inspector(iid):
    return get_or_404(DB.inspectors, iid, "ERR_INSPECTOR_NOT_FOUND")


def get_property(pid):
    return get_or_404(DB.properties, pid, "ERR_PROPERTY_NOT_FOUND")


def get_project(pid):
    return get_or_404(DB.projects, pid, "ERR_PROJECT_NOT_FOUND")


def get_submittal(sid):
    return get_or_404(DB.submittals, sid, "ERR_SUBMITTAL_NOT_FOUND")


def get_correction(cid):
    return get_or_404(DB.corrections, cid, "ERR_CORRECTION_ITEM_NOT_FOUND")


def get_utility(uid):
    return get_or_404(DB.utilities, uid, "ERR_UTILITY_CONNECTION_NOT_FOUND")


def get_scenario(sid):
    return get_or_404(DB.scenarios, sid, "ERR_FINANCING_SCENARIO_NOT_FOUND")


def get_change_order(cid):
    return get_or_404(DB.change_orders, cid, "ERR_CHANGE_ORDER_NOT_FOUND")


def get_phase(pid):
    return get_or_404(DB.phases, pid, "ERR_PHASE_NOT_FOUND")


def get_appointment(aid):
    return get_or_404(DB.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")


def project_context(project):
    prop = DB.properties.get(project["property_id"])
    jur = DB.jurisdictions.get(prop["jurisdiction_id"]) if prop else None
    return prop, jur


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
def D(value):
    return Decimal(str(value))


def round_half_up(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return float(D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def trunc_toward_zero(value):
    return int(D(value).to_integral_value(rounding=ROUND_DOWN))
