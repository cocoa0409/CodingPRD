"""Core runtime for the Municipal Water Utility O&M Contract Delivery API.

In-memory only.  Nothing is persisted, nothing is seeded: a freshly booted
process serves empty collections and every entity is built by the caller
through the declared API surface.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, g

PREFIX = "/water-om"

# PRD 2.5: the server starts at a fixed default logical instant and never reads
# wall-clock time.  Every deadline, grace window and rate transition evaluates
# against this instant.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

ROLES = ("PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin", "Employee")

TABLES = (
    "municipalities", "contracts", "standards", "measurements", "staffing",
    "employees", "assets", "assessments", "permits", "allocations",
    "work_orders", "pm_schedules", "emergencies", "proposals", "obligations",
)

# PRD 5: error catalogue with HTTP status codes.
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ACTOR_NOT_FOUND": 401,
    "ERR_ROLE_FORBIDDEN": 403,
    "ERR_CROSS_TENANT_DENIED": 403,
    "ERR_SELF_SERVICE_OWNER_MISMATCH": 403,
    "ERR_MUNICIPALITY_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_STANDARD_NOT_FOUND": 404,
    "ERR_MEASUREMENT_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_STAFFING_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_PM_SCHEDULE_NOT_FOUND": 404,
    "ERR_EMERGENCY_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_PROPOSAL_NOT_FOUND": 404,
    "ERR_OBLIGATION_NOT_FOUND": 404,
    "ERR_CONTRACT_INVALID_STATE": 409,
    "ERR_ASSET_INVALID_STATE": 409,
    "ERR_WORK_ORDER_INVALID_STATE": 409,
    "ERR_PM_SCHEDULE_INVALID_STATE": 409,
    "ERR_EMERGENCY_INVALID_STATE": 409,
    "ERR_ALLOCATION_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_BASELINE_FROZEN": 409,
    "ERR_OPEN_BREACH_BLOCKS": 409,
    "ERR_OPEN_WORK_ORDER_BLOCKS": 409,
    "ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE": 403,
    "ERR_INVALID_DATE_WINDOW": 400,
    "ERR_NOTIFICATION_WINDOW_CLOSED": 409,
    "ERR_CONTAINMENT_WINDOW_EXCEEDED": 409,
    "ERR_PM_WINDOW_EXPIRED": 409,
    "ERR_REPORTAGE_PERIOD_OPEN": 409,
    "ERR_PM_WINDOW_TOO_FAR": 409,
    "ERR_OBLIGATION_DUE_BEFORE_HANDOFF": 400,
    "ERR_BACKDATED_RECORD_REJECTED": 400,
    "ERR_MEASUREMENT_PERIOD_OVERLAP": 409,
    "ERR_PM_OCCUPATION_OVERLAP": 409,
    "ERR_DUPLICATE_STANDARD_CODE": 409,
    "ERR_DUPLICATE_ASSET_TAG": 409,
    "ERR_BASELINE_ALREADY_FROZEN": 409,
    "ERR_DUPLICATE_ROUND_PROPOSAL": 409,
    "ERR_DUPLICATE_ACTIVE_PERMIT_TYPE": 409,
    "ERR_THRESHOLD_DIRECTION_INVALID": 400,
    "ERR_RENEWAL_ROUND_MISMATCH": 409,
    "ERR_CLOSED_WORK_ORDER_IMMUTABLE": 409,
    "ERR_EXPENSE_CLASS_UNRESOLVED": 409,
    "ERR_BENCHMARK_RATIO_EXCEEDED": 422,
    "ERR_BREACH_UNRESOLVED_AT_RENEWAL": 409,
    "ERR_PENALTY_ALLOCATION_NOT_CONSERVED": 422,
    "ERR_NEGATIVE_SETTLEMENT": 422,
    "ERR_PENALTY_CAP_EXCEEDED": 409,
    "ERR_CAPITAL_THRESHOLD_NOT_MET": 422,
    "ERR_ASSET_BASELINE_UNRESOLVED": 409,
    "ERR_CRITICAL_OBLIGATIONS_OUTSTANDING": 409,
    "ERR_PERMIT_ACTION_UNRESOLVED": 409,
    "ERR_ASSET_CONTRACT_MISMATCH": 409,
    "ERR_CRITICAL_ACKNOWLEDGEMENT_MISSING": 422,
    "ERR_EMERGENCY_STAFFING_FLOOR": 409,
    "ERR_OVERFLOW_CONTAINMENT_REQUIRED": 409,
    "ERR_REPORTING_FREQUENCY_VIOLATION": 422,
    "ERR_CONTAMINATION_CONTAINMENT_REQUIRED": 409,
    "ERR_WORK_ORDER_DOCUMENTATION_INCOMPLETE": 409,
    "ERR_STALE_VERSION": 412,
}

ERROR_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required on every request.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not one of the declared roles.",
    "ERR_ACTOR_NOT_FOUND": "X-User-ID does not identify an instance of the entity the role is bound to.",
    "ERR_ROLE_FORBIDDEN": "The acting role is not permitted for this operation.",
    "ERR_CROSS_TENANT_DENIED": "The acting party may not perform the opposing party's step on this record.",
    "ERR_SELF_SERVICE_OWNER_MISMATCH": "An Employee self-service call must carry the employee's own id.",
    "ERR_MUNICIPALITY_NOT_FOUND": "No municipality matches the supplied id.",
    "ERR_CONTRACT_NOT_FOUND": "No contract matches the supplied id.",
    "ERR_PERMIT_NOT_FOUND": "No permit matches the supplied id.",
    "ERR_STANDARD_NOT_FOUND": "No performance standard matches the supplied id.",
    "ERR_MEASUREMENT_NOT_FOUND": "No performance measurement matches the supplied id.",
    "ERR_ASSET_NOT_FOUND": "No asset matches the supplied id.",
    "ERR_ASSESSMENT_NOT_FOUND": "No asset condition assessment matches the supplied id.",
    "ERR_EMPLOYEE_NOT_FOUND": "No employee matches the supplied id.",
    "ERR_STAFFING_NOT_FOUND": "No staffing commitment matches the supplied id.",
    "ERR_WORK_ORDER_NOT_FOUND": "No work order matches the supplied id.",
    "ERR_PM_SCHEDULE_NOT_FOUND": "No preventive maintenance schedule matches the supplied id.",
    "ERR_EMERGENCY_NOT_FOUND": "No emergency event matches the supplied id.",
    "ERR_ALLOCATION_NOT_FOUND": "No penalty allocation matches the supplied id.",
    "ERR_PROPOSAL_NOT_FOUND": "No renewal proposal matches the supplied id.",
    "ERR_OBLIGATION_NOT_FOUND": "No transition obligation matches the supplied id.",
    "ERR_CONTRACT_INVALID_STATE": "The contract is not in the from-state required by this transition.",
    "ERR_ASSET_INVALID_STATE": "The asset is not in the from-state required by this transition.",
    "ERR_WORK_ORDER_INVALID_STATE": "The work order is not in the from-state required by this transition.",
    "ERR_PM_SCHEDULE_INVALID_STATE": "The preventive maintenance schedule is not in the from-state required by this transition.",
    "ERR_EMERGENCY_INVALID_STATE": "The emergency event is not in the from-state required by this transition.",
    "ERR_ALLOCATION_INVALID_STATE": "The penalty allocation is not in a state that accepts an adjustment.",
    "ERR_ALREADY_TERMINAL": "The target resource is already in a terminal state for this operation.",
    "ERR_BASELINE_FROZEN": "The contract-start baseline is frozen and can no longer be amended or disputed.",
    "ERR_OPEN_BREACH_BLOCKS": "A breaching performance standard blocks the contract from returning to operation.",
    "ERR_OPEN_WORK_ORDER_BLOCKS": "An open work order blocks the asset from leaving service.",
    "ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE": "A critical transition-back obligation cannot be waived.",
    "ERR_INVALID_DATE_WINDOW": "The supplied instants violate their required ordering.",
    "ERR_NOTIFICATION_WINDOW_CLOSED": "The emergency notification window has closed.",
    "ERR_CONTAINMENT_WINDOW_EXCEEDED": "The containment instant precedes the event or exceeds the critical containment window.",
    "ERR_PM_WINDOW_EXPIRED": "The preventive maintenance grace window has closed.",
    "ERR_REPORTAGE_PERIOD_OPEN": "The municipality's five day reportage period has not elapsed.",
    "ERR_PM_WINDOW_TOO_FAR": "The scheduled maintenance occupation extends beyond the 30 day scheduling horizon.",
    "ERR_OBLIGATION_DUE_BEFORE_HANDOFF": "A transition-back obligation is due before the hand-back started.",
    "ERR_BACKDATED_RECORD_REJECTED": "An ingested record is dated more than 7 days before the current logical clock.",
    "ERR_MEASUREMENT_PERIOD_OVERLAP": "The measurement period overlaps an existing period on the same standard.",
    "ERR_PM_OCCUPATION_OVERLAP": "The maintenance occupation overlaps an existing schedule or open preventive work order on the same asset.",
    "ERR_DUPLICATE_STANDARD_CODE": "A performance standard with this code already exists on the contract.",
    "ERR_DUPLICATE_ASSET_TAG": "An asset with this tag already exists on the contract.",
    "ERR_BASELINE_ALREADY_FROZEN": "An accepted baseline already exists for the asset.",
    "ERR_DUPLICATE_ROUND_PROPOSAL": "A proposal for this negotiation round already exists.",
    "ERR_DUPLICATE_ACTIVE_PERMIT_TYPE": "A non-expired permit of this type already exists on the contract.",
    "ERR_THRESHOLD_DIRECTION_INVALID": "The threshold direction is inconsistent with the metric type.",
    "ERR_RENEWAL_ROUND_MISMATCH": "The proposal round number does not follow the contract's renewal round.",
    "ERR_CLOSED_WORK_ORDER_IMMUTABLE": "A closed work order cannot be amended.",
    "ERR_EXPENSE_CLASS_UNRESOLVED": "A work order whose expense class is unresolved cannot be closed.",
    "ERR_BENCHMARK_RATIO_EXCEEDED": "The renewal proposal's benchmark ratio exceeds 1.25.",
    "ERR_BREACH_UNRESOLVED_AT_RENEWAL": "A breaching standard remains on the contract when renewal is proposed.",
    "ERR_PENALTY_ALLOCATION_NOT_CONSERVED": "Operator and municipality shares do not sum to the regulator's total penalty.",
    "ERR_NEGATIVE_SETTLEMENT": "The computed net settlement is negative.",
    "ERR_PENALTY_CAP_EXCEEDED": "Aggregate breach penalties would exceed the annual fee.",
    "ERR_CAPITAL_THRESHOLD_NOT_MET": "A capital classification is offered before the asset has reached the required proportion of its useful life.",
    "ERR_ASSET_BASELINE_UNRESOLVED": "An asset cannot be placed in service without exactly one frozen baseline assessment.",
    "ERR_CRITICAL_OBLIGATIONS_OUTSTANDING": "Critical transition-back obligations remain unsatisfied.",
    "ERR_PERMIT_ACTION_UNRESOLVED": "An unresolved regulatory action blocks wind-down.",
    "ERR_ASSET_CONTRACT_MISMATCH": "The supplied asset does not belong to the path's contract.",
    "ERR_CRITICAL_ACKNOWLEDGEMENT_MISSING": "A critical emergency lacks the required operator acknowledgements.",
    "ERR_EMERGENCY_STAFFING_FLOOR": "Staffing would be reduced below the committed floor while an emergency is open.",
    "ERR_OVERFLOW_CONTAINMENT_REQUIRED": "A sanitary overflow has no containment record.",
    "ERR_REPORTING_FREQUENCY_VIOLATION": "The measurement interval is shorter than the permit's reporting frequency.",
    "ERR_CONTAMINATION_CONTAINMENT_REQUIRED": "A contamination event has no containment instant before the notification is filed.",
    "ERR_WORK_ORDER_DOCUMENTATION_INCOMPLETE": "A work order is completed with incomplete mandatory documentation.",
    "ERR_STALE_VERSION": "The supplied expected contract version does not match the contract's current version.",
}

DB = {t: {} for t in TABLES}
CLOCK = {"now": None}
SEQ = {"n": 0}

app = Flask(__name__)
app.url_map.strict_slashes = False


class ApiError(Exception):
    def __init__(self, error_id, message=None, http=None, extra=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or ERROR_MESSAGE.get(error_id, error_id)
        self.http = http or ERROR_HTTP.get(error_id, 400)
        self.extra = extra


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------
def _parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset_clock():
    CLOCK["now"] = _parse_iso(DEFAULT_CLOCK_ISO)


reset_clock()


def now():
    return CLOCK["now"]


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(now())


def parse_dt(value):
    """Parse a client supplied instant; ApiError when unusable."""
    dt = _parse_iso(value)
    if dt is None:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "A supplied instant could not be parsed.")
    return dt


def parse_dt_opt(value):
    return _parse_iso(value)


def dt_of(rec, field):
    return _parse_iso(rec.get(field))


# --------------------------------------------------------------------------
# numeric helpers — round half up everywhere, never float money
# --------------------------------------------------------------------------
def dec(value, default="0"):
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    try:
        return Decimal(str(value).strip())
    except Exception:
        return Decimal(default)


def rhu(value, places):
    """round-half-up to `places` decimal places, returns Decimal."""
    d = dec(value)
    quantum = Decimal(1).scaleb(-places)
    return d.quantize(quantum, rounding=ROUND_HALF_UP)


def f4(value):
    return float(rhu(value, 4))


def f2(value):
    return float(rhu(value, 2))


def icents(value):
    return int(rhu(value, 0))


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def create(table, **fields):
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_t": table,
        "_seq": next_seq(),
    }
    rec.update(fields)
    if "status" in rec and "status_changed_at" not in rec:
        rec["status_changed_at"] = rec["created_at"]
    DB[table][rec["id"]] = rec
    return rec


CONTRACT_TRACKED = (
    "status", "annual_fee_cents", "renewal_round", "baseline_frozen",
    "staffing_floor_fte", "total_operator_penalty_cents", "baseline_asset_count",
    "contract_end_date",
)


def apply(rec, **changes):
    """Mutate a record; refresh updated_at and bump version per PRD 2.4/2.8."""
    before = None
    if rec["_t"] == "contracts":
        before = tuple(rec.get(k) for k in CONTRACT_TRACKED)
    rec.update(changes)
    rec["updated_at"] = now_iso()
    if rec["_t"] == "contracts":
        if tuple(rec.get(k) for k in CONTRACT_TRACKED) != before:
            rec["version"] += 1
    else:
        rec["version"] += 1
    return rec


def set_status(rec, status, **changes):
    changes["status"] = status
    changes["status_changed_at"] = now_iso()
    return apply(rec, **changes)


def bump(rec):
    """Force a version increment on an operation the PRD names as version-bumping."""
    rec["version"] = int(rec.get("version") or 1) + 1
    rec["updated_at"] = now_iso()
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get(table, ident, error_id):
    rec = DB[table].get(ident)
    if rec is None:
        raise ApiError(error_id)
    return rec


def rows(table, **filters):
    out = []
    for rec in DB[table].values():
        ok = True
        for key, value in filters.items():
            if value is None:
                continue
            if rec.get(key) != value:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def ordered(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def body():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def field(data, name, required=True):
    if name in data and data[name] is not None:
        return data[name]
    if required:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Missing required field '%s'." % name)
    return None


def str_field(data, name, required=True, allow_empty=False):
    value = field(data, name, required=required)
    if value is None:
        return None
    value = str(value)
    if not allow_empty and required and not value.strip():
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Field '%s' must be non-empty." % name)
    return value


# --------------------------------------------------------------------------
# pagination — PRD 2.3
# --------------------------------------------------------------------------
class Page(list):
    def __init__(self, items, total, limit, offset):
        super().__init__(items)
        self.total = total
        self.limit = limit
        self.offset = offset


def paginate(items):
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = 10 if raw_limit is None or raw_limit == "" else int(raw_limit)
        offset = 0 if raw_offset is None or raw_offset == "" else int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION", "limit and offset must be integers.", http=400)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.", http=400)
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be zero or greater.", http=400)
    total = len(items)
    return Page(items[offset:offset + limit], total, limit, offset)


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def arg_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return str(value).strip().lower() in ("true", "1", "yes")


# --------------------------------------------------------------------------
# response envelope — PRD 2.2
# --------------------------------------------------------------------------
def new_request_id():
    return "req_" + uuid.uuid4().hex[:16].upper()


def _meta_base():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def success(data, status=200, extra_data=None):
    meta = _meta_base()
    if isinstance(data, Page):
        meta["limit"] = data.limit
        meta["offset"] = data.offset
        meta["total_count"] = data.total
        meta["has_more"] = (data.offset + len(data)) < data.total
        payload = [public(r) for r in data]
        rtype = "array"
    elif isinstance(data, list):
        payload = [public(r) for r in data]
        rtype = "array"
    elif data is None:
        payload = {}
        rtype = "object"
    else:
        payload = public(data)
        rtype = "object"
    if extra_data:
        payload = dict(payload)
        payload.update(extra_data)
    return app.response_class(
        _dumps({"meta": meta, "response_type": rtype, "data": payload}),
        status=status,
        mimetype="application/json",
    )


def failure(error):
    meta = _meta_base()
    data = {"error_id": error.error_id, "message": error.message}
    if error.extra:
        data.update(error.extra)
    return app.response_class(
        _dumps({"meta": meta, "response_type": "error", "data": data}),
        status=error.http,
        mimetype="application/json",
    )


def _dumps(obj):
    import json
    return json.dumps(obj, default=str)


# --------------------------------------------------------------------------
# auth / RBAC — PRD 2.1, 2.9, 2.10
# --------------------------------------------------------------------------
def _actor_entity(role):
    if role == "MunicipalityAdmin":
        return "municipalities", "ERR_ACTOR_NOT_FOUND"
    if role == "OperatorAdmin":
        return "contracts", "ERR_ACTOR_NOT_FOUND"
    if role == "Employee":
        return "employees", "ERR_ACTOR_NOT_FOUND"
    return None, None


def authenticate(roles, self_service=False):
    """Priority 1-6 auth chain, then bind the actor onto flask.g."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or uid is None or not str(role).strip() or not str(uid).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    uid = str(uid).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    table, _ = _actor_entity(role)
    if table is not None and uid not in DB[table]:
        raise ApiError("ERR_ACTOR_NOT_FOUND")
    if role not in roles:
        raise ApiError("ERR_ROLE_FORBIDDEN")
    g.actor_role = role
    g.actor_id = uid
    if self_service and role == "Employee" and request.view_args:
        target = request.view_args.get("id")
        if target is not None and target != uid:
            raise ApiError("ERR_SELF_SERVICE_OWNER_MISMATCH")


def owner_contract(rec):
    """The Contract id a record belongs to, following the parent chain."""
    table = rec["_t"]
    if table == "contracts":
        return rec["id"]
    if rec.get("contract_id"):
        return rec["contract_id"]
    if table == "measurements":
        std = DB["standards"].get(rec.get("performance_standard_id"))
        return std.get("contract_id") if std else None
    if table == "assessments":
        asset = DB["assets"].get(rec.get("asset_id"))
        return asset.get("contract_id") if asset else None
    if table == "allocations":
        permit = DB["permits"].get(rec.get("permit_id"))
        return permit.get("contract_id") if permit else None
    return None


def owner_municipality(rec):
    if rec["_t"] == "municipalities":
        return rec["id"]
    cid = owner_contract(rec)
    if cid:
        contract = DB["contracts"].get(cid)
        if contract:
            return contract.get("municipality_id")
    return None


def own(rec):
    """Ownership gate: the acting party must own the record it addresses."""
    if rec is None:
        return
    role = g.actor_role
    uid = g.actor_id
    if role == "MunicipalityAdmin":
        mid = owner_municipality(rec)
        if mid is not None and mid != uid:
            raise ApiError("ERR_CROSS_TENANT_DENIED")
    elif role == "OperatorAdmin":
        cid = owner_contract(rec)
        if cid is not None and cid != uid:
            raise ApiError("ERR_CROSS_TENANT_DENIED")


def endpoint(rule, methods, roles, status=200, self_service=False):
    """Register a view: auth chain -> handler -> success envelope."""
    def deco(fn):
        @wraps(fn)
        def view(**kwargs):
            authenticate(roles, self_service=self_service)
            result = fn(**kwargs)
            if isinstance(result, app.response_class):
                return result
            if isinstance(result, tuple) and len(result) == 3:
                return success(result[0], result[1], extra_data=result[2])
            if isinstance(result, tuple) and len(result) == 2:
                return success(result[0], result[1])
            return success(result, status)

        view.__name__ = fn.__name__
        app.add_url_rule(PREFIX + rule, endpoint=fn.__name__, view_func=view,
                         methods=methods)
        return view
    return deco


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return failure(error)


@app.errorhandler(404)
def _handle_404(error):
    return failure(ApiError("ERR_NOT_FOUND", "No route matches this request.", http=404))


@app.errorhandler(405)
def _handle_405(error):
    return failure(ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", http=405))


@app.errorhandler(Exception)
def _handle_unexpected(error):
    if isinstance(error, ApiError):
        return failure(error)
    import sys
    import traceback
    traceback.print_exc(file=sys.stderr)
    return failure(ApiError("ERR_INTERNAL", "Unexpected server error.", http=500))
