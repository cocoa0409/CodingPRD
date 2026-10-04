"""Core Banking Platform Conversion API.

In-memory REST API implementing the PRD for a community-institution core
banking conversion. State lives entirely in process memory (dicts keyed by
id); nothing is seeded at startup. A server-maintained logical clock (default
2026-09-01T00:00:00Z) drives all temporal reasoning.
"""

import os
import re
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK = {"now": datetime(2026, 9, 1, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK["now"]


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

DB = {
    "projects": {},
    "product_types": {},
    "accounts": {},
    "gl_accounts": {},
    "mock_runs": {},
    "ancillary_systems": {},
    "training_sessions": {},
    "enrollments": {},
    "staff": {},
    "customer_comms": {},
    "defects": {},
    "service_credits": {},
    "plans": {},
    "tasks": {},
}

# ---------------------------------------------------------------------------
# Roles / errors
# ---------------------------------------------------------------------------

ROLES = {
    "ProjectManager",
    "ConversionEngineer",
    "OperationsLead",
    "Trainer",
    "CommunicationsOfficer",
    "VendorTriageLead",
    "FinanceController",
}

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_OUTSIDE_WINDOW": 409,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_INVARIANT_VIOLATION": 422,
    "ERR_DUPLICATE": 409,
    "ERR_CREDIT_INELIGIBLE": 422,
    "ERR_PHASE_GATE": 409,
    "ERR_FROZEN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_STALE_VERSION": 412,
    "ERR_RUN_IN_PROGRESS": 409,
    "ERR_SESSION_OVERLAP": 409,
    "ERR_FREEZE_CHANNEL_BUSY": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERROR_STATUS[error_id]


def fail(error_id, message):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _request_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": _request_timestamp(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def _handle_500(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth middleware (before_request): priority 1 and 2
# ---------------------------------------------------------------------------

# route key -> allowed roles. route key = (method, canonical path template)
ROUTE_ROLES = {}


def require_auth():
    if request.path.startswith("/api/v1"):
        uid = request.headers.get("X-User-ID")
        role = request.headers.get("X-User-Role")
        if not uid or not role or role not in ROLES:
            fail("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role / X-User-ID headers.")
        # RBAC check resolved in the view via endpoint wrapper
    return None


app.before_request(require_auth)


def role_ctx():
    return {
        "uid": request.headers.get("X-User-ID"),
        "role": request.headers.get("X-User-Role"),
    }


def check_role(allowed):
    ctx = role_ctx()
    if ctx["role"] not in allowed:
        fail("ERR_FORBIDDEN", "Role not permitted to call this endpoint.")
    return ctx


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def validate_body(body, spec):
    """spec: dict field -> (type_tag, required). Unknown fields rejected."""
    for k in body.keys():
        if k not in spec:
            fail("ERR_INVALID_REQUEST", f"Unknown field: {k}")
    for k, (tag, required) in spec.items():
        if k not in body or body[k] is None:
            if required:
                fail("ERR_INVALID_REQUEST", f"Missing required field: {k}")
            continue
        v = body[k]
        if tag == "string" and not isinstance(v, str):
            fail("ERR_INVALID_REQUEST", f"Field {k} must be a string.")
        if tag == "int" and (not isinstance(v, int) or isinstance(v, bool)):
            fail("ERR_INVALID_REQUEST", f"Field {k} must be an integer.")
        if tag == "number" and (
            not isinstance(v, (int, float)) or isinstance(v, bool)
        ):
            fail("ERR_INVALID_REQUEST", f"Field {k} must be a number.")
        if tag == "array" and not isinstance(v, list):
            fail("ERR_INVALID_REQUEST", f"Field {k} must be an array.")
    return body


def validate_enum(value, allowed, field):
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", f"Field {field} has invalid value: {value}")
    return value


def validate_date(value, field):
    try:
        d = date.fromisoformat(value)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", f"Field {field} must be YYYY-MM-DD.")
    return d


def validate_datetime(value, field):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", f"Field {field} must be an ISO8601 datetime.")
    v = value
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        fail("ERR_INVALID_REQUEST", f"Field {field} must be an ISO8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def validate_month(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        fail("ERR_INVALID_REQUEST", f"Field {field} must be YYYY-MM.")
    return value


def month_of(dt):
    return f"{dt.year:04d}-{dt.month:02d}"


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------


def iso_ms(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_common():
    now = clock_now()
    return {
        "id": uuid.uuid4().hex,
        "created_at": iso_ms(now),
        "updated_at": iso_ms(now),
        "version": 1,
    }


def new_light():
    now = clock_now()
    return {"id": uuid.uuid4().hex, "created_at": iso_ms(now)}


def touch(rec):
    rec["updated_at"] = iso_ms(clock_now())
    rec["version"] += 1


def get_or_404(coll, rid):
    rec = DB[coll].get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", f"Resource {rid} not found.")
    return rec


def project_of(rec):
    return get_or_404("projects", rec["project_id"])


def bump_project(project):
    touch(project)


def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "limit and offset must be integers.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items):
    items = sorted(items, key=lambda r: r["created_at"])
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GL recomputation
# ---------------------------------------------------------------------------

GL_STATUSES = {"MAPPED", "EXCEPTION", "CLEARED", "CONVERTED"}


def recompute_gl(gl):
    exp = 0
    conv = 0
    for a in DB["accounts"].values():
        if a.get("gl_account_id") == gl["id"] and a["status"] in GL_STATUSES:
            exp += a["opening_principal_cents"]
            conv += a.get("conversion_balance_cents") or 0
    gl["expected_balance_cents"] = exp
    gl["converted_balance_cents"] = conv
    gl["variance_cents"] = conv - exp
    touch(gl)


def recompute_all_gls(project_id):
    for gl in DB["gl_accounts"].values():
        if gl["project_id"] == project_id:
            recompute_gl(gl)


# ---------------------------------------------------------------------------
# Accrual and fee computations
# ---------------------------------------------------------------------------


def compute_accrual(account, product, comp_date):
    """comp_date is a datetime.date. Returns (daily_cents, accrued_cents,
    conversion_balance_cents)."""
    p = account["opening_principal_cents"]
    rate = Decimal(str(product["rate"]))
    method = product["accrual_method"]
    divisor = Decimal(365) if method == "ACT_365" else Decimal(360)
    daily = (Decimal(p) * rate / divisor).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    daily = int(daily)
    d0 = date.fromisoformat(account["accrual_start_date"])
    if d0 > comp_date:
        days = 0
    elif method == "THIRTY_360":
        days = (
            360 * (comp_date.year - d0.year)
            + 30 * (comp_date.month - d0.month)
            + min(comp_date.day, 30)
            - min(d0.day, 30)
            + 1
        )
    else:
        days = (comp_date - d0).days + 1
    accrued = daily * days
    if account["account_type"] == "DEPOSIT":
        conv = p + accrued
    else:  # LOAN: principal only
        conv = p
    return daily, accrued, conv


def apply_accrual(account, product, comp_date):
    daily, accrued, conv = compute_accrual(account, product, comp_date)
    account["daily_interest_cents"] = daily
    account["cutoff_accrued_interest_cents"] = accrued
    account["conversion_balance_cents"] = conv
    touch(account)


def apply_monthly_fee(account, product):
    if account["account_type"] == "LOAN":
        account["monthly_fee_assessed_cents"] = 0
        return
    threshold = product.get("fee_waiver_threshold_cents")
    if threshold is None:
        account["monthly_fee_assessed_cents"] = product["monthly_fee_cents"]
    elif (account.get("conversion_balance_cents") or 0) >= threshold:
        account["monthly_fee_assessed_cents"] = 0
    else:
        account["monthly_fee_assessed_cents"] = product["monthly_fee_cents"]


# ---------------------------------------------------------------------------
# Freeze-channel exclusion (cross-project)
# ---------------------------------------------------------------------------


def freeze_channel_busy(exclude_project_id, freeze_start):
    """True if freeze_start falls inside [window_start, window_end + 30min]
    of any task of any non-ROLLED_BACK plan of any OTHER project."""
    for plan in DB["plans"].values():
        if plan["project_id"] == exclude_project_id:
            continue
        if plan["status"] == "ROLLED_BACK":
            continue
        for t in DB["tasks"].values():
            if t["parent_plan_id"] != plan["id"]:
                continue
            ws = t["_ws"]
            we = t["_we"]
            if ws <= freeze_start <= we + timedelta(minutes=30):
                return True
    return False


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.post("/api/v1/_clock/set_current_utc")
def set_clock():
    check_role({"ProjectManager"})
    body = validate_body(get_body(), {"current_utc": ("string", True)})
    dt = validate_datetime(body["current_utc"], "current_utc")
    _CLOCK["now"] = dt
    return ok_object({"current_utc": iso_ms(dt)})


# ---------------------------------------------------------------------------
# ConversionProject
# ---------------------------------------------------------------------------

PROJECT_STATUSES = {
    "DISCOVERY",
    "CONFIGURATION",
    "MOCK_CONVERSION",
    "CUTOVER_PLANNED",
    "LIVE",
    "CLOSED",
}
ALL_ROLES = ROLES


def project_view(p):
    return {
        "id": p["id"],
        "institution_name": p["institution_name"],
        "incumbent_core_name": p["incumbent_core_name"],
        "target_core_name": p["target_core_name"],
        "status": p["status"],
        "mock_runs_used": p["mock_runs_used"],
        "cutover_scheduled_date": p["cutover_scheduled_date"],
        "cutoff_business_date": p["cutoff_business_date"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@app.post("/api/v1/conversions")
def create_project():
    check_role({"ProjectManager"})
    body = validate_body(
        get_body(),
        {
            "institution_name": ("string", True),
            "incumbent_core_name": ("string", True),
            "target_core_name": ("string", True),
            "cutover_scheduled_date": ("string", False),
        },
    )
    csd = None
    if body.get("cutover_scheduled_date") is not None:
        d = validate_date(body["cutover_scheduled_date"], "cutover_scheduled_date")
        if not (d > clock_now().date()):
            fail(
                "ERR_INVALID_REQUEST",
                "cutover_scheduled_date must be strictly after the current clock date.",
            )
        csd = body["cutover_scheduled_date"]
    rec = new_common()
    rec.update(
        {
            "institution_name": body["institution_name"],
            "incumbent_core_name": body["incumbent_core_name"],
            "target_core_name": body["target_core_name"],
            "status": "DISCOVERY",
            "mock_runs_used": 0,
            "cutover_scheduled_date": csd,
            "cutoff_business_date": None,
        }
    )
    DB["projects"][rec["id"]] = rec
    return ok_object(project_view(rec), 201)


@app.get("/api/v1/conversions")
def list_projects():
    check_role(ALL_ROLES)
    items = list(DB["projects"].values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response([project_view(p) for p in items])


@app.get("/api/v1/conversions/<pid>")
def get_project(pid):
    check_role(ALL_ROLES)
    p = get_or_404("projects", pid)
    return ok_object(project_view(p))


@app.post("/api/v1/conversions/<pid>/advance")
def advance_project(pid):
    check_role({"ProjectManager"})
    p = get_or_404("projects", pid)
    if p["status"] == "DISCOVERY":
        has_pt = any(pt["project_id"] == pid for pt in DB["product_types"].values())
        has_gl = any(g["project_id"] == pid for g in DB["gl_accounts"].values())
        if not (has_pt and has_gl):
            fail(
                "ERR_PHASE_GATE",
                "Advancing to CONFIGURATION requires at least one product type and one GL account.",
            )
        p["status"] = "CONFIGURATION"
    elif p["status"] == "CONFIGURATION":
        has_active_pt = any(
            pt["project_id"] == pid and pt["status"] == "ACTIVE"
            for pt in DB["product_types"].values()
        )
        has_mapped = any(
            a["project_id"] == pid and a["status"] == "MAPPED"
            for a in DB["accounts"].values()
        )
        if not (has_active_pt and has_mapped):
            fail(
                "ERR_PHASE_GATE",
                "Advancing to MOCK_CONVERSION requires an ACTIVE product type and a MAPPED account.",
            )
        p["status"] = "MOCK_CONVERSION"
    else:
        fail("ERR_INVALID_STATE", f"Project in {p['status']} cannot be advanced.")
    bump_project(p)
    return ok_object(project_view(p))


@app.post("/api/v1/conversions/<pid>/plan-cutover")
def plan_cutover(pid):
    check_role({"ProjectManager"})
    p = get_or_404("projects", pid)
    body = validate_body(
        get_body(),
        {
            "cutover_scheduled_date": ("string", True),
            "file_freeze_start": ("string", True),
            "go_no_go_checkpoint": ("string", True),
            "reopen_target": ("string", True),
        },
    )
    csd_date = validate_date(body["cutover_scheduled_date"], "cutover_scheduled_date")
    ffs = validate_datetime(body["file_freeze_start"], "file_freeze_start")
    gng = validate_datetime(body["go_no_go_checkpoint"], "go_no_go_checkpoint")
    reopen = validate_datetime(body["reopen_target"], "reopen_target")

    if p["status"] != "MOCK_CONVERSION":
        fail("ERR_INVALID_STATE", f"Project in {p['status']} cannot plan a cutover.")

    # Phase gates
    passed_runs = [
        r
        for r in DB["mock_runs"].values()
        if r["project_id"] == pid and r["state"] == "PASSED"
    ]
    any_baseline = any(
        r["project_id"] == pid and r["is_cutover_baseline"]
        for r in DB["mock_runs"].values()
    )
    if not (len(passed_runs) == 1 and not any_baseline):
        fail(
            "ERR_PHASE_GATE",
            "Exactly one PASSED mock run and no existing baseline required.",
        )
    if any(
        a["project_id"] == pid and a["status"] == "EXCEPTION"
        for a in DB["accounts"].values()
    ):
        fail("ERR_PHASE_GATE", "No account may be in EXCEPTION to plan cutover.")
    if not (csd_date > clock_now().date()):
        fail(
            "ERR_PHASE_GATE",
            "cutover_scheduled_date must be strictly after the current clock date.",
        )

    # Cross-project freeze channel
    if freeze_channel_busy(pid, ffs):
        fail(
            "ERR_FREEZE_CHANNEL_BUSY",
            "file_freeze_start falls inside another project's active conversion window plus grace.",
        )

    baseline = passed_runs[0]
    baseline["is_cutover_baseline"] = True
    touch(baseline)

    plan = new_light()
    plan.update(
        {
            "project_id": pid,
            "planned_cutover_date": body["cutover_scheduled_date"],
            "file_freeze_start": iso_ms(ffs),
            "reopen_target": iso_ms(reopen),
            "go_no_go_checkpoint": iso_ms(gng),
            "status": "DRAFT",
            "_ffs": ffs,
            "_gng": gng,
            "_reopen": reopen,
        }
    )
    DB["plans"][plan["id"]] = plan

    for a in DB["accounts"].values():
        if a["project_id"] == pid:
            a["frozen_flag"] = True
            touch(a)

    p["cutover_scheduled_date"] = body["cutover_scheduled_date"]
    p["status"] = "CUTOVER_PLANNED"
    bump_project(p)
    return ok_object(plan_view(plan))


@app.post("/api/v1/conversions/<pid>/go-live")
def go_live(pid):
    check_role({"ProjectManager"})
    p = get_or_404("projects", pid)
    if p["status"] != "CUTOVER_PLANNED":
        fail("ERR_INVALID_STATE", f"Project in {p['status']} cannot go live.")
    plan = next((pl for pl in DB["plans"].values() if pl["project_id"] == pid), None)
    if plan is None or plan["status"] != "GO":
        fail("ERR_PHASE_GATE", "Cutover plan must be in GO status.")
    for t in DB["tasks"].values():
        if t["parent_plan_id"] == plan["id"] and t["status"] not in {
            "COMPLETE",
            "SKIPPED",
        }:
            fail("ERR_PHASE_GATE", "Every cutover task must be COMPLETE or SKIPPED.")
    for s in DB["ancillary_systems"].values():
        if s["project_id"] == pid and s["status"] not in {"VERIFIED", "RETEST_PASSED"}:
            fail(
                "ERR_PHASE_GATE",
                "Every ancillary system must be VERIFIED or RETEST_PASSED.",
            )
    for d in DB["defects"].values():
        if (
            d["project_id"] == pid
            and d["severity"] == "SEV1"
            and d["status"] in {"OPEN", "TRIAGED", "IN_FIX", "REOPENED"}
        ):
            fail("ERR_PHASE_GATE", "An active SEV1 defect blocks go-live.")

    now = clock_now()
    cutoff = now.date()
    p["cutoff_business_date"] = cutoff.isoformat()

    for a in DB["accounts"].values():
        if a["project_id"] != pid:
            continue
        if a["status"] == "CLEARED":
            a["status"] = "CONVERTED"
            product = DB["product_types"].get(a["product_type_id"])
            apply_accrual(a, product, cutoff)
        elif a["status"] == "MAPPED":
            a["status"] = "EXCEPTION"
            a["exception_note"] = "uncleared at go-live"
            touch(a)
    recompute_all_gls(pid)

    for c in DB["customer_comms"].values():
        if (
            c["project_id"] == pid
            and c["status"] == "SCHEDULED"
            and c["_scheduled_send_date"] <= now
        ):
            c["status"] = "SENT"
            touch(c)

    plan["status"] = "LIVE"
    p["status"] = "LIVE"
    bump_project(p)
    return ok_object(project_view(p))


@app.post("/api/v1/conversions/<pid>/close")
def close_project(pid):
    check_role({"ProjectManager"})
    p = get_or_404("projects", pid)
    if p["status"] != "LIVE":
        fail("ERR_INVALID_STATE", f"Project in {p['status']} cannot be closed.")
    for d in DB["defects"].values():
        if d["project_id"] == pid and d["status"] in {
            "OPEN",
            "TRIAGED",
            "IN_FIX",
            "REOPENED",
        }:
            fail("ERR_PHASE_GATE", "An active defect blocks close.")
    for sc in DB["service_credits"].values():
        if sc["project_id"] == pid and sc["claim_status"] == "OPEN":
            fail("ERR_PHASE_GATE", "An OPEN service credit claim blocks close.")
    p["status"] = "CLOSED"
    bump_project(p)
    return ok_object(project_view(p))


# ---------------------------------------------------------------------------
# ProductType
# ---------------------------------------------------------------------------

KINDS = {"DEPOSIT", "LOAN"}
ACCRUAL_METHODS = {"ACT_365", "ACT_360", "THIRTY_360"}
STATEMENT_FREQS = {"MONTHLY", "QUARTERLY"}
PT_STATUSES = {"DRAFT", "ACTIVE", "RETIRED"}


def check_accrual_legality(kind, method, rate):
    """Returns error message or None."""
    if kind == "DEPOSIT" and method == "THIRTY_360":
        return "DEPOSIT products must not use THIRTY_360."
    if kind == "LOAN" and method == "ACT_365":
        return "LOAN products must not use ACT_365."
    if kind == "DEPOSIT" and not (rate >= 0):
        return "DEPOSIT rate must be >= 0."
    if kind == "LOAN" and not (rate > 0):
        return "LOAN rate must be > 0."
    return None


def pt_view(pt):
    return {
        "id": pt["id"],
        "project_id": pt["project_id"],
        "product_code": pt["product_code"],
        "kind": pt["kind"],
        "accrual_method": pt["accrual_method"],
        "rate": pt["rate"],
        "monthly_fee_cents": pt["monthly_fee_cents"],
        "fee_waiver_threshold_cents": pt["fee_waiver_threshold_cents"],
        "minimum_balance_cents": pt["minimum_balance_cents"],
        "statement_frequency": pt["statement_frequency"],
        "status": pt["status"],
        "created_at": pt["created_at"],
        "updated_at": pt["updated_at"],
        "version": pt["version"],
    }


@app.post("/api/v1/product-types")
def create_product_type():
    check_role({"ConversionEngineer"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "product_code": ("string", True),
            "kind": ("string", True),
            "accrual_method": ("string", True),
            "rate": ("number", True),
            "statement_frequency": ("string", True),
            "monthly_fee_cents": ("int", False),
            "fee_waiver_threshold_cents": ("int", False),
            "minimum_balance_cents": ("int", False),
        },
    )
    p = get_or_404("projects", body["project_id"])
    validate_enum(body["kind"], KINDS, "kind")
    validate_enum(body["accrual_method"], ACCRUAL_METHODS, "accrual_method")
    validate_enum(body["statement_frequency"], STATEMENT_FREQS, "statement_frequency")
    rate = body["rate"]
    monthly_fee = body.get("monthly_fee_cents", 0)
    min_balance = body.get("minimum_balance_cents", 0)
    if monthly_fee < 0:
        fail("ERR_INVALID_REQUEST", "monthly_fee_cents must be >= 0.")
    if min_balance < 0:
        fail("ERR_INVALID_REQUEST", "minimum_balance_cents must be >= 0.")

    err = check_accrual_legality(body["kind"], body["accrual_method"], rate)
    if err:
        fail("ERR_INVARIANT_VIOLATION", err)

    for pt in DB["product_types"].values():
        if (
            pt["project_id"] == p["id"]
            and pt["product_code"] == body["product_code"]
        ):
            fail("ERR_DUPLICATE", "product_code must be unique per project.")

    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "product_code": body["product_code"],
            "kind": body["kind"],
            "accrual_method": body["accrual_method"],
            "rate": rate,
            "monthly_fee_cents": monthly_fee,
            "fee_waiver_threshold_cents": body.get("fee_waiver_threshold_cents"),
            "minimum_balance_cents": min_balance,
            "statement_frequency": body["statement_frequency"],
            "status": "DRAFT",
        }
    )
    DB["product_types"][rec["id"]] = rec
    return ok_object(pt_view(rec), 201)


@app.get("/api/v1/product-types")
def list_product_types():
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    items = list(DB["product_types"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [pt for pt in items if pt["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [pt for pt in items if pt["status"] == status]
    return list_response([pt_view(pt) for pt in items])


@app.get("/api/v1/product-types/<ptid>")
def get_product_type(ptid):
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    pt = get_or_404("product_types", ptid)
    return ok_object(pt_view(pt))


@app.post("/api/v1/product-types/<ptid>/activate")
def activate_product_type(ptid):
    check_role({"ConversionEngineer"})
    pt = get_or_404("product_types", ptid)
    if pt["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", f"Product in {pt['status']} cannot be activated.")
    p = project_of(pt)
    if p["status"] not in {"DISCOVERY", "CONFIGURATION"}:
        fail(
            "ERR_PHASE_GATE",
            "Product activation requires project DISCOVERY or CONFIGURATION.",
        )
    err = check_accrual_legality(pt["kind"], pt["accrual_method"], pt["rate"])
    if err:
        fail("ERR_INVARIANT_VIOLATION", err)
    if pt["statement_frequency"] not in STATEMENT_FREQS:
        fail("ERR_INVARIANT_VIOLATION", "statement_frequency must be MONTHLY or QUARTERLY.")
    pt["status"] = "ACTIVE"
    touch(pt)
    return ok_object(pt_view(pt))


@app.post("/api/v1/product-types/<ptid>/deactivate")
def deactivate_product_type(ptid):
    check_role({"ConversionEngineer"})
    pt = get_or_404("product_types", ptid)
    if pt["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", f"Product in {pt['status']} cannot be deactivated.")
    p = project_of(pt)
    if p["status"] not in {"DISCOVERY", "CONFIGURATION"}:
        fail(
            "ERR_PHASE_GATE",
            "Product deactivation requires project DISCOVERY or CONFIGURATION.",
        )
    pt["status"] = "DRAFT"
    touch(pt)
    for a in DB["accounts"].values():
        if a["product_type_id"] == pt["id"] and a["status"] == "MAPPED":
            a["status"] = "EXCEPTION"
            a["exception_note"] = "product deactivated"
            touch(a)
    return ok_object(pt_view(pt))


@app.post("/api/v1/product-types/<ptid>/retire")
def retire_product_type(ptid):
    check_role({"ConversionEngineer"})
    pt = get_or_404("product_types", ptid)
    if pt["status"] not in {"DRAFT", "ACTIVE"}:
        fail("ERR_INVALID_STATE", f"Product in {pt['status']} cannot be retired.")
    for a in DB["accounts"].values():
        if a["product_type_id"] == pt["id"] and a["status"] in {
            "STAGED",
            "MAPPED",
            "EXCEPTION",
            "CLEARED",
        }:
            fail(
                "ERR_INVARIANT_VIOLATION",
                "Accounts still reference this product in an active status.",
            )
    pt["status"] = "RETIRED"
    touch(pt)
    return ok_object(pt_view(pt))


@app.get("/api/v1/product-types/<ptid>/accounts")
def list_accounts_of_product(ptid):
    check_role({"ProjectManager", "ConversionEngineer"})
    pt = get_or_404("product_types", ptid)
    items = [
        a for a in DB["accounts"].values() if a["product_type_id"] == pt["id"]
    ]
    return list_response([account_view(a) for a in items])


# ---------------------------------------------------------------------------
# GLAccount
# ---------------------------------------------------------------------------


def gl_view(gl):
    return {
        "id": gl["id"],
        "project_id": gl["project_id"],
        "gl_code": gl["gl_code"],
        "description": gl["description"],
        "expected_balance_cents": gl["expected_balance_cents"],
        "converted_balance_cents": gl["converted_balance_cents"],
        "variance_cents": gl["variance_cents"],
        "created_at": gl["created_at"],
        "updated_at": gl["updated_at"],
        "version": gl["version"],
    }


@app.post("/api/v1/gl-accounts")
def create_gl_account():
    check_role({"ConversionEngineer"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "gl_code": ("string", True),
            "description": ("string", True),
        },
    )
    p = get_or_404("projects", body["project_id"])
    for gl in DB["gl_accounts"].values():
        if gl["project_id"] == p["id"] and gl["gl_code"] == body["gl_code"]:
            fail("ERR_DUPLICATE", "gl_code must be unique per project.")
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "gl_code": body["gl_code"],
            "description": body["description"],
            "expected_balance_cents": 0,
            "converted_balance_cents": 0,
            "variance_cents": 0,
        }
    )
    DB["gl_accounts"][rec["id"]] = rec
    return ok_object(gl_view(rec), 201)


@app.get("/api/v1/gl-accounts")
def list_gl_accounts():
    check_role({"ProjectManager", "ConversionEngineer", "FinanceController"})
    items = list(DB["gl_accounts"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [g for g in items if g["project_id"] == project_id]
    return list_response([gl_view(g) for g in items])


@app.get("/api/v1/gl-accounts/<gid>")
def get_gl_account(gid):
    check_role({"ProjectManager", "ConversionEngineer", "FinanceController"})
    gl = get_or_404("gl_accounts", gid)
    return ok_object(gl_view(gl))


@app.get("/api/v1/gl-accounts/<gid>/accounts")
def list_accounts_of_gl(gid):
    check_role({"ProjectManager", "ConversionEngineer", "FinanceController"})
    gl = get_or_404("gl_accounts", gid)
    items = [a for a in DB["accounts"].values() if a.get("gl_account_id") == gl["id"]]
    return list_response([account_view(a) for a in items])


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

ACCOUNT_TYPES = {"DEPOSIT", "LOAN"}
ACCOUNT_STATUSES = {"STAGED", "MAPPED", "EXCEPTION", "CLEARED", "CONVERTED", "BLOCKED"}
_account_counter = {"n": 0}


def account_view(a):
    return {
        "id": a["id"],
        "project_id": a["project_id"],
        "legacy_account_number": a["legacy_account_number"],
        "new_account_number": a["new_account_number"],
        "account_type": a["account_type"],
        "product_type_id": a["product_type_id"],
        "status": a["status"],
        "exception_note": a["exception_note"],
        "frozen_flag": a["frozen_flag"],
        "opening_principal_cents": a["opening_principal_cents"],
        "conversion_balance_cents": a["conversion_balance_cents"],
        "cutoff_accrued_interest_cents": a["cutoff_accrued_interest_cents"],
        "daily_interest_cents": a["daily_interest_cents"],
        "monthly_fee_assessed_cents": a["monthly_fee_assessed_cents"],
        "statement_cycle_day": a["statement_cycle_day"],
        "accrual_start_date": a["accrual_start_date"],
        "gl_account_id": a["gl_account_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@app.post("/api/v1/accounts")
def create_account():
    check_role({"ConversionEngineer"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "legacy_account_number": ("string", True),
            "account_type": ("string", True),
            "product_type_id": ("string", True),
            "opening_principal_cents": ("int", True),
            "statement_cycle_day": ("int", True),
            "accrual_start_date": ("string", True),
        },
    )
    p = get_or_404("projects", body["project_id"])
    validate_enum(body["account_type"], ACCOUNT_TYPES, "account_type")
    pt = get_or_404("product_types", body["product_type_id"])
    if body["opening_principal_cents"] < 0:
        fail("ERR_INVALID_REQUEST", "opening_principal_cents must be >= 0.")
    scd = body["statement_cycle_day"]
    if not (1 <= scd <= 28):
        fail("ERR_INVALID_REQUEST", "statement_cycle_day must be in 1..28.")
    validate_date(body["accrual_start_date"], "accrual_start_date")

    if pt["project_id"] != p["id"] or pt["kind"] != body["account_type"]:
        fail(
            "ERR_INVALID_REFERENCE",
            "product_type_id must reference a product of the same project whose kind matches account_type.",
        )

    for a in DB["accounts"].values():
        if (
            a["project_id"] == p["id"]
            and a["legacy_account_number"] == body["legacy_account_number"]
        ):
            fail("ERR_DUPLICATE", "legacy_account_number must be unique per project.")

    _account_counter["n"] += 1
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "legacy_account_number": body["legacy_account_number"],
            "new_account_number": "NEW-" + str(_account_counter["n"]).zfill(10),
            "account_type": body["account_type"],
            "product_type_id": pt["id"],
            "status": "STAGED",
            "exception_note": None,
            "frozen_flag": False,
            "opening_principal_cents": body["opening_principal_cents"],
            "conversion_balance_cents": body["opening_principal_cents"],
            "cutoff_accrued_interest_cents": 0,
            "daily_interest_cents": 0,
            "monthly_fee_assessed_cents": 0,
            "statement_cycle_day": scd,
            "accrual_start_date": body["accrual_start_date"],
            "gl_account_id": None,
        }
    )
    DB["accounts"][rec["id"]] = rec
    return ok_object(account_view(rec), 201)


@app.get("/api/v1/accounts")
def list_accounts():
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead", "FinanceController"})
    items = list(DB["accounts"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [a for a in items if a["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    ptid = request.args.get("product_type_id")
    if ptid is not None:
        items = [a for a in items if a["product_type_id"] == ptid]
    gid = request.args.get("gl_account_id")
    if gid is not None:
        items = [a for a in items if a.get("gl_account_id") == gid]
    return list_response([account_view(a) for a in items])


@app.get("/api/v1/accounts/<aid>")
def get_account(aid):
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead", "FinanceController"})
    a = get_or_404("accounts", aid)
    return ok_object(account_view(a))


@app.post("/api/v1/accounts/<aid>/map")
def map_account(aid):
    check_role({"ConversionEngineer"})
    a = get_or_404("accounts", aid)
    body = validate_body(
        get_body(),
        {
            "gl_account_id": ("string", True),
            "expected_project_version": ("int", True),
        },
    )
    p = project_of(a)
    # OCC check
    if body["expected_project_version"] != p["version"]:
        fail("ERR_STALE_VERSION", "expected_project_version does not match.")
    # state
    if a["status"] != "STAGED":
        fail("ERR_INVALID_STATE", f"Account in {a['status']} cannot be mapped.")
    gl = get_or_404("gl_accounts", body["gl_account_id"])
    # referential
    if gl["project_id"] != p["id"]:
        fail("ERR_INVALID_REFERENCE", "GL account belongs to a different project.")
    pt = DB["product_types"].get(a["product_type_id"])
    if pt is None or pt["status"] != "ACTIVE" or pt["kind"] != a["account_type"]:
        fail(
            "ERR_INVALID_REFERENCE",
            "Product must be ACTIVE and its kind must match account_type.",
        )
    # freeze
    if p["status"] in {"CUTOVER_PLANNED", "LIVE"}:
        fail("ERR_FROZEN", "File freeze in effect.")
    if p["status"] == "CLOSED":
        fail("ERR_INVALID_STATE", "Project is CLOSED.")
    a["gl_account_id"] = gl["id"]
    a["status"] = "MAPPED"
    touch(a)
    recompute_gl(gl)
    bump_project(p)
    return ok_object(account_view(a))


@app.post("/api/v1/accounts/<aid>/flag-exception")
def flag_exception(aid):
    check_role({"ConversionEngineer"})
    a = get_or_404("accounts", aid)
    body = validate_body(get_body(), {"note": ("string", True)})
    p = project_of(a)
    if a["status"] not in {"MAPPED", "CLEARED"}:
        fail("ERR_INVALID_STATE", f"Account in {a['status']} cannot be flagged.")
    if p["status"] != "MOCK_CONVERSION":
        if p["status"] in {"CUTOVER_PLANNED", "LIVE"}:
            fail("ERR_FROZEN", "File freeze in effect.")
        fail("ERR_PHASE_GATE", "Flag exception requires project MOCK_CONVERSION.")
    if a["frozen_flag"]:
        fail("ERR_FROZEN", "Account is frozen.")
    a["status"] = "EXCEPTION"
    a["exception_note"] = body["note"]
    touch(a)
    if a.get("gl_account_id"):
        recompute_gl(DB["gl_accounts"][a["gl_account_id"]])
    return ok_object(account_view(a))


@app.post("/api/v1/accounts/<aid>/clear-exception")
def clear_exception(aid):
    check_role({"ConversionEngineer"})
    a = get_or_404("accounts", aid)
    body = validate_body(get_body(), {"resolution_note": ("string", True)})
    p = project_of(a)
    if a["status"] != "EXCEPTION":
        fail("ERR_INVALID_STATE", f"Account in {a['status']} cannot be cleared.")
    if p["status"] != "MOCK_CONVERSION":
        if p["status"] in {"CUTOVER_PLANNED", "LIVE"}:
            fail("ERR_FROZEN", "File freeze in effect.")
        fail("ERR_PHASE_GATE", "Clear exception requires project MOCK_CONVERSION.")
    if a["frozen_flag"]:
        fail("ERR_FROZEN", "Account is frozen.")
    a["status"] = "CLEARED"
    touch(a)
    if a.get("gl_account_id"):
        recompute_gl(DB["gl_accounts"][a["gl_account_id"]])
    return ok_object(account_view(a))


@app.get("/api/v1/accounts/<aid>/customer-comms")
def list_comms_of_account(aid):
    check_role({"ProjectManager", "CommunicationsOfficer"})
    a = get_or_404("accounts", aid)
    items = [c for c in DB["customer_comms"].values() if c["account_id"] == a["id"]]
    return list_response([comm_view(c) for c in items])


# ---------------------------------------------------------------------------
# MockRun
# ---------------------------------------------------------------------------

MOCK_STATES = {"RUNNING", "FAILED", "PASSED_WITH_EXCEPTIONS", "PASSED"}


def mock_view(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "run_label": r["run_label"],
        "state": r["state"],
        "started_at": r["started_at"],
        "finished_at": r["finished_at"],
        "duration_seconds": r["duration_seconds"],
        "balanced_account_count": r["balanced_account_count"],
        "exception_account_count": r["exception_account_count"],
        "converted_total_cents": r["converted_total_cents"],
        "outcome": r["outcome"],
        "is_cutover_baseline": r["is_cutover_baseline"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@app.post("/api/v1/mock-runs")
def create_mock_run():
    check_role({"ConversionEngineer"})
    body = validate_body(
        get_body(),
        {"project_id": ("string", True), "run_label": ("string", True)},
    )
    p = get_or_404("projects", body["project_id"])
    if p["status"] != "MOCK_CONVERSION":
        fail("ERR_PHASE_GATE", "Mock runs require project MOCK_CONVERSION.")
    for r in DB["mock_runs"].values():
        if r["project_id"] == p["id"] and r["state"] == "RUNNING":
            fail("ERR_RUN_IN_PROGRESS", "Another MockRun is still RUNNING.")
    for r in DB["mock_runs"].values():
        if r["project_id"] == p["id"] and r["run_label"] == body["run_label"]:
            fail("ERR_DUPLICATE", "run_label must be unique per project.")
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "run_label": body["run_label"],
            "state": "RUNNING",
            "started_at": iso_ms(clock_now()),
            "_started": clock_now(),
            "finished_at": None,
            "duration_seconds": None,
            "balanced_account_count": 0,
            "exception_account_count": 0,
            "converted_total_cents": 0,
            "outcome": None,
            "is_cutover_baseline": False,
        }
    )
    DB["mock_runs"][rec["id"]] = rec
    return ok_object(mock_view(rec), 201)


@app.get("/api/v1/mock-runs")
def list_mock_runs():
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    items = list(DB["mock_runs"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [r for r in items if r["project_id"] == project_id]
    state = request.args.get("state")
    if state is not None:
        items = [r for r in items if r["state"] == state]
    return list_response([mock_view(r) for r in items])


@app.get("/api/v1/mock-runs/<rid>")
def get_mock_run(rid):
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    r = get_or_404("mock_runs", rid)
    return ok_object(mock_view(r))


@app.post("/api/v1/mock-runs/<rid>/finalize")
def finalize_mock_run(rid):
    check_role({"ConversionEngineer"})
    r = get_or_404("mock_runs", rid)
    if r["state"] != "RUNNING":
        fail("ERR_INVALID_STATE", f"MockRun in {r['state']} cannot be finalized.")
    p = project_of(r)
    for other in DB["mock_runs"].values():
        if (
            other["project_id"] == p["id"]
            and other["id"] != r["id"]
            and other["state"] == "RUNNING"
        ):
            fail("ERR_RUN_IN_PROGRESS", "Another MockRun is still RUNNING.")
    if p["status"] != "MOCK_CONVERSION":
        fail("ERR_PHASE_GATE", "Finalize requires project MOCK_CONVERSION.")

    now = clock_now()
    comp_date = now.date()
    accounts = [a for a in DB["accounts"].values() if a["project_id"] == p["id"]]
    for a in accounts:
        if a["status"] in {"MAPPED", "EXCEPTION", "CLEARED", "CONVERTED"}:
            product = DB["product_types"].get(a["product_type_id"])
            apply_accrual(a, product, comp_date)
        if a["status"] in {"MAPPED", "EXCEPTION", "CLEARED"}:
            product = DB["product_types"].get(a["product_type_id"])
            apply_monthly_fee(a, product)
    recompute_all_gls(p["id"])

    balanced = sum(
        1 for a in accounts if a["status"] in {"MAPPED", "CLEARED", "BLOCKED"}
    )
    exceptions = sum(1 for a in accounts if a["status"] == "EXCEPTION")
    converted_total = sum(a.get("conversion_balance_cents") or 0 for a in accounts)

    if balanced == 0:
        outcome = "FAILED"
    elif exceptions > 0:
        outcome = "PASSED_WITH_EXCEPTIONS"
    else:
        outcome = "PASSED"

    r["finished_at"] = iso_ms(now)
    r["duration_seconds"] = int((now - r["_started"]).total_seconds())
    r["balanced_account_count"] = balanced
    r["exception_account_count"] = exceptions
    r["converted_total_cents"] = converted_total
    r["outcome"] = outcome
    r["state"] = outcome
    touch(r)

    p["mock_runs_used"] += 1
    touch(p)

    if outcome == "PASSED":
        for a in accounts:
            if a["status"] == "CLEARED":
                a["status"] = "MAPPED"
                touch(a)
        recompute_all_gls(p["id"])

    return ok_object(mock_view(r))


# ---------------------------------------------------------------------------
# AncillarySystem
# ---------------------------------------------------------------------------

ANC_CATEGORIES = {"CARDS", "ONLINE_BANKING", "ITEM_PROCESSING", "REPORTING"}
ANC_STATUSES = {"PENDING", "INTEGRATING", "VERIFIED", "FAILED", "RETEST_PASSED"}


def anc_view(s):
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "name": s["name"],
        "category": s["category"],
        "status": s["status"],
        "interface_version": s["interface_version"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@app.post("/api/v1/ancillary-systems")
def create_ancillary_system():
    check_role({"OperationsLead"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "name": ("string", True),
            "category": ("string", True),
            "interface_version": ("string", True),
        },
    )
    p = get_or_404("projects", body["project_id"])
    validate_enum(body["category"], ANC_CATEGORIES, "category")
    for s in DB["ancillary_systems"].values():
        if s["project_id"] == p["id"] and s["name"] == body["name"]:
            fail("ERR_DUPLICATE", "name must be unique per project.")
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "name": body["name"],
            "category": body["category"],
            "status": "PENDING",
            "interface_version": body["interface_version"],
        }
    )
    DB["ancillary_systems"][rec["id"]] = rec
    return ok_object(anc_view(rec), 201)


@app.get("/api/v1/ancillary-systems")
def list_ancillary_systems():
    check_role({"ProjectManager", "OperationsLead", "VendorTriageLead"})
    items = list(DB["ancillary_systems"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [s for s in items if s["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    category = request.args.get("category")
    if category is not None:
        items = [s for s in items if s["category"] == category]
    return list_response([anc_view(s) for s in items])


@app.get("/api/v1/ancillary-systems/<sid>")
def get_ancillary_system(sid):
    check_role({"ProjectManager", "OperationsLead", "VendorTriageLead"})
    s = get_or_404("ancillary_systems", sid)
    return ok_object(anc_view(s))


@app.post("/api/v1/ancillary-systems/<sid>/start-integration")
def start_integration(sid):
    check_role({"OperationsLead"})
    s = get_or_404("ancillary_systems", sid)
    if s["status"] not in {"PENDING", "FAILED"}:
        fail(
            "ERR_INVALID_STATE",
            f"System in {s['status']} cannot start integration.",
        )
    p = project_of(s)
    if p["status"] not in {"MOCK_CONVERSION", "CUTOVER_PLANNED"}:
        fail(
            "ERR_PHASE_GATE",
            "Integration requires project MOCK_CONVERSION or CUTOVER_PLANNED.",
        )
    s["status"] = "INTEGRATING"
    touch(s)
    return ok_object(anc_view(s))


@app.post("/api/v1/ancillary-systems/<sid>/verify")
def verify_integration(sid):
    check_role({"OperationsLead"})
    s = get_or_404("ancillary_systems", sid)
    if s["status"] != "INTEGRATING":
        fail("ERR_INVALID_STATE", f"System in {s['status']} cannot be verified.")
    p = project_of(s)
    if p["status"] not in {"MOCK_CONVERSION", "CUTOVER_PLANNED"}:
        fail(
            "ERR_PHASE_GATE",
            "Verification requires project MOCK_CONVERSION or CUTOVER_PLANNED.",
        )
    s["status"] = "VERIFIED"
    touch(s)
    return ok_object(anc_view(s))


@app.post("/api/v1/ancillary-systems/<sid>/fail")
def fail_integration(sid):
    check_role({"OperationsLead"})
    s = get_or_404("ancillary_systems", sid)
    if s["status"] != "INTEGRATING":
        fail("ERR_INVALID_STATE", f"System in {s['status']} cannot be failed.")
    s["status"] = "FAILED"
    touch(s)
    return ok_object(anc_view(s))


@app.post("/api/v1/ancillary-systems/<sid>/retest")
def retest_integration(sid):
    check_role({"OperationsLead"})
    s = get_or_404("ancillary_systems", sid)
    if s["status"] != "FAILED":
        fail("ERR_INVALID_STATE", f"System in {s['status']} cannot be retested.")
    s["status"] = "RETEST_PASSED"
    touch(s)
    return ok_object(anc_view(s))


@app.get("/api/v1/ancillary-systems/<sid>/defects")
def list_defects_of_system(sid):
    check_role({"ProjectManager", "OperationsLead", "VendorTriageLead"})
    s = get_or_404("ancillary_systems", sid)
    items = [d for d in DB["defects"].values() if d.get("linked_system_id") == s["id"]]
    return list_response([defect_view(d) for d in items])


# ---------------------------------------------------------------------------
# TrainingSession / Staff / Enrollment
# ---------------------------------------------------------------------------

ROLE_SCOPES = {"TELLER", "LENDER", "OPS", "BRANCH_MANAGER"}
SESSION_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
ENROLLMENT_STATES = {"RESERVED", "ATTENDED", "NO_SHOW", "CANCELLED"}


def session_view(s):
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "branch_name": s["branch_name"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "capacity": s["capacity"],
        "reserved_count": s["reserved_count"],
        "attended_count": s["attended_count"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def staff_view(m):
    return {
        "id": m["id"],
        "project_id": m["project_id"],
        "employee_code": m["employee_code"],
        "full_name": m["full_name"],
        "branch_name": m["branch_name"],
        "role_scope": m["role_scope"],
        "parallel_ops_certified": m["parallel_ops_certified"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def enrollment_view(e):
    return {
        "id": e["id"],
        "parent_session_id": e["parent_session_id"],
        "employee_id": e["employee_id"],
        "state": e["state"],
        "created_at": e["created_at"],
    }


@app.post("/api/v1/training-sessions")
def create_training_session():
    check_role({"Trainer"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "branch_name": ("string", True),
            "scheduled_start": ("string", True),
            "scheduled_end": ("string", True),
            "capacity": ("int", True),
        },
    )
    p = get_or_404("projects", body["project_id"])
    ss = validate_datetime(body["scheduled_start"], "scheduled_start")
    se = validate_datetime(body["scheduled_end"], "scheduled_end")
    if body["capacity"] < 1:
        fail("ERR_INVALID_REQUEST", "capacity must be >= 1.")
    if not (se > ss):
        fail("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")
    # overlap: half-open [ss, se) vs [s2, e2)
    for s in DB["training_sessions"].values():
        if (
            s["branch_name"] == body["branch_name"]
            and s["status"] != "CANCELLED"
            and ss < s["_se"]
            and s["_ss"] < se
        ):
            fail(
                "ERR_SESSION_OVERLAP",
                "Session overlaps an existing non-CANCELLED session of the same branch.",
            )
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "branch_name": body["branch_name"],
            "scheduled_start": iso_ms(ss),
            "scheduled_end": iso_ms(se),
            "_ss": ss,
            "_se": se,
            "capacity": body["capacity"],
            "reserved_count": 0,
            "attended_count": 0,
            "status": "SCHEDULED",
        }
    )
    DB["training_sessions"][rec["id"]] = rec
    return ok_object(session_view(rec), 201)


@app.get("/api/v1/training-sessions")
def list_training_sessions():
    check_role({"ProjectManager", "Trainer", "OperationsLead"})
    items = list(DB["training_sessions"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [s for s in items if s["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    branch = request.args.get("branch_name")
    if branch is not None:
        items = [s for s in items if s["branch_name"] == branch]
    return list_response([session_view(s) for s in items])


@app.get("/api/v1/training-sessions/<tsid>")
def get_training_session(tsid):
    check_role({"ProjectManager", "Trainer", "OperationsLead"})
    s = get_or_404("training_sessions", tsid)
    return ok_object(session_view(s))


def _recompute_session_counts(s):
    reserved = sum(
        1
        for e in DB["enrollments"].values()
        if e["parent_session_id"] == s["id"] and e["state"] == "RESERVED"
    )
    attended = sum(
        1
        for e in DB["enrollments"].values()
        if e["parent_session_id"] == s["id"] and e["state"] == "ATTENDED"
    )
    s["reserved_count"] = reserved
    s["attended_count"] = attended


def _fire_certification(s):
    attended_employees = {
        e["employee_id"]
        for e in DB["enrollments"].values()
        if e["parent_session_id"] == s["id"] and e["state"] == "ATTENDED"
    }
    for emp_id in attended_employees:
        m = DB["staff"].get(emp_id)
        if m is not None and not m["parallel_ops_certified"]:
            m["parallel_ops_certified"] = True
            touch(m)


@app.post("/api/v1/training-sessions/<tsid>/start")
def start_session(tsid):
    check_role({"Trainer"})
    s = get_or_404("training_sessions", tsid)
    if s["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", f"Session in {s['status']} cannot be started.")
    now = clock_now()
    if not (now >= s["_ss"] and now < s["_se"]):
        fail("ERR_OUTSIDE_WINDOW", "Clock is outside the session window.")
    s["status"] = "IN_PROGRESS"
    touch(s)
    return ok_object(session_view(s))


@app.post("/api/v1/training-sessions/<tsid>/complete")
def complete_session(tsid):
    check_role({"Trainer"})
    s = get_or_404("training_sessions", tsid)
    if s["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", f"Session in {s['status']} cannot be completed.")
    now = clock_now()
    if not (now >= s["_se"]):
        fail("ERR_OUTSIDE_WINDOW", "Clock is before scheduled_end.")
    if any(
        e["parent_session_id"] == s["id"] and e["state"] == "RESERVED"
        for e in DB["enrollments"].values()
    ):
        fail("ERR_INVALID_STATE", "Reserved enrollments remain.")
    _recompute_session_counts(s)
    s["status"] = "COMPLETED"
    touch(s)
    _fire_certification(s)
    return ok_object(session_view(s))


@app.post("/api/v1/training-sessions/<tsid>/cancel")
def cancel_session(tsid):
    check_role({"Trainer"})
    s = get_or_404("training_sessions", tsid)
    if s["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", f"Session in {s['status']} cannot be cancelled.")
    for e in DB["enrollments"].values():
        if e["parent_session_id"] == s["id"] and e["state"] == "RESERVED":
            e["state"] = "CANCELLED"
    _recompute_session_counts(s)
    s["status"] = "CANCELLED"
    touch(s)
    return ok_object(session_view(s))


@app.post("/api/v1/staff")
def create_staff():
    check_role({"Trainer"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "employee_code": ("string", True),
            "full_name": ("string", True),
            "branch_name": ("string", True),
            "role_scope": ("string", True),
        },
    )
    p = get_or_404("projects", body["project_id"])
    validate_enum(body["role_scope"], ROLE_SCOPES, "role_scope")
    for m in DB["staff"].values():
        if m["project_id"] == p["id"] and m["employee_code"] == body["employee_code"]:
            fail("ERR_DUPLICATE", "employee_code must be unique per project.")
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "employee_code": body["employee_code"],
            "full_name": body["full_name"],
            "branch_name": body["branch_name"],
            "role_scope": body["role_scope"],
            "parallel_ops_certified": False,
        }
    )
    DB["staff"][rec["id"]] = rec
    return ok_object(staff_view(rec), 201)


@app.get("/api/v1/staff")
def list_staff():
    check_role({"ProjectManager", "Trainer", "OperationsLead"})
    items = list(DB["staff"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [m for m in items if m["project_id"] == project_id]
    rs = request.args.get("role_scope")
    if rs is not None:
        items = [m for m in items if m["role_scope"] == rs]
    branch = request.args.get("branch_name")
    if branch is not None:
        items = [m for m in items if m["branch_name"] == branch]
    return list_response([staff_view(m) for m in items])


@app.get("/api/v1/staff/<smid>")
def get_staff(smid):
    check_role({"ProjectManager", "Trainer", "OperationsLead"})
    m = get_or_404("staff", smid)
    return ok_object(staff_view(m))


@app.get("/api/v1/staff/<smid>/enrollments")
def list_enrollments_of_staff(smid):
    check_role({"ProjectManager", "Trainer"})
    m = get_or_404("staff", smid)
    items = [e for e in DB["enrollments"].values() if e["employee_id"] == m["id"]]
    return list_response([enrollment_view(e) for e in items])


@app.post("/api/v1/enrollments")
def create_enrollment():
    check_role({"Trainer"})
    body = validate_body(
        get_body(),
        {"session_id": ("string", True), "employee_id": ("string", True)},
    )
    s = get_or_404("training_sessions", body["session_id"])
    m = get_or_404("staff", body["employee_id"])
    for e in DB["enrollments"].values():
        if (
            e["parent_session_id"] == s["id"]
            and e["employee_id"] == m["id"]
            and e["state"] != "CANCELLED"
        ):
            fail("ERR_INVARIANT_VIOLATION", "Duplicate enrollment in the same session.")
    active_reserved = sum(
        1
        for e in DB["enrollments"].values()
        if e["parent_session_id"] == s["id"] and e["state"] == "RESERVED"
    )
    if active_reserved >= s["capacity"]:
        fail("ERR_INVARIANT_VIOLATION", "Session capacity exceeded.")
    rec = new_light()
    rec.update(
        {
            "parent_session_id": s["id"],
            "employee_id": m["id"],
            "state": "RESERVED",
        }
    )
    DB["enrollments"][rec["id"]] = rec
    s["reserved_count"] += 1
    touch(s)
    return ok_object(enrollment_view(rec), 201)


@app.get("/api/v1/enrollments")
def list_enrollments():
    check_role({"ProjectManager", "Trainer"})
    items = list(DB["enrollments"].values())
    session_id = request.args.get("session_id")
    if session_id is not None:
        items = [e for e in items if e["parent_session_id"] == session_id]
    state = request.args.get("state")
    if state is not None:
        items = [e for e in items if e["state"] == state]
    emp = request.args.get("employee_id")
    if emp is not None:
        items = [e for e in items if e["employee_id"] == emp]
    return list_response([enrollment_view(e) for e in items])


@app.post("/api/v1/enrollments/<eid>/attend")
def attend_enrollment(eid):
    check_role({"Trainer"})
    e = get_or_404("enrollments", eid)
    if e["state"] != "RESERVED":
        fail("ERR_INVALID_STATE", f"Enrollment in {e['state']} cannot be attended.")
    s = DB["training_sessions"][e["parent_session_id"]]
    if s["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Session is not IN_PROGRESS.")
    e["state"] = "ATTENDED"
    _recompute_session_counts(s)
    touch(s)
    # auto-complete cascade
    now = clock_now()
    if s["reserved_count"] == 0 and now >= s["_se"]:
        s["status"] = "COMPLETED"
        touch(s)
        _fire_certification(s)
    return ok_object(enrollment_view(e))


@app.post("/api/v1/enrollments/<eid>/no-show")
def no_show_enrollment(eid):
    check_role({"Trainer"})
    e = get_or_404("enrollments", eid)
    if e["state"] != "RESERVED":
        fail("ERR_INVALID_STATE", f"Enrollment in {e['state']} cannot be no-showed.")
    s = DB["training_sessions"][e["parent_session_id"]]
    if s["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Session is not IN_PROGRESS.")
    e["state"] = "NO_SHOW"
    _recompute_session_counts(s)
    touch(s)
    return ok_object(enrollment_view(e))


@app.post("/api/v1/enrollments/<eid>/cancel")
def cancel_enrollment(eid):
    check_role({"Trainer"})
    e = get_or_404("enrollments", eid)
    if e["state"] != "RESERVED":
        fail("ERR_INVALID_STATE", f"Enrollment in {e['state']} cannot be cancelled.")
    s = DB["training_sessions"][e["parent_session_id"]]
    e["state"] = "CANCELLED"
    _recompute_session_counts(s)
    touch(s)
    return ok_object(enrollment_view(e))


# ---------------------------------------------------------------------------
# CustomerComm
# ---------------------------------------------------------------------------

COMM_TYPES = {"ACCOUNT_NUMBER_CHANGE", "CARD_REISSUE", "PAYMENT_REDIRECTION"}
COMM_STATUSES = {"DRAFT", "SCHEDULED", "SENT", "DELIVERED", "FAILED", "CANCELLED"}
SECONDS_PER_DAY = 86400
SEND_WINDOW_DAYS = 3


def comm_view(c):
    return {
        "id": c["id"],
        "project_id": c["project_id"],
        "account_id": c["account_id"],
        "comm_type": c["comm_type"],
        "wave": c["wave"],
        "send_after": c["send_after"],
        "send_before": c["send_before"],
        "scheduled_send_date": c["scheduled_send_date"],
        "resend_count": c["resend_count"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@app.post("/api/v1/customer-comms")
def create_comm():
    check_role({"CommunicationsOfficer"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "account_id": ("string", True),
            "comm_type": ("string", True),
            "wave": ("int", True),
        },
    )
    p = get_or_404("projects", body["project_id"])
    a = get_or_404("accounts", body["account_id"])
    validate_enum(body["comm_type"], COMM_TYPES, "comm_type")
    if body["wave"] < 1:
        fail("ERR_INVALID_REQUEST", "wave must be >= 1.")
    # project created_at -> datetime
    created_str = p["created_at"].replace("Z", "+00:00")
    proj_created = datetime.fromisoformat(created_str)
    send_after = proj_created + timedelta(seconds=(body["wave"] - 1) * SECONDS_PER_DAY)
    send_before = send_after + timedelta(seconds=SEND_WINDOW_DAYS * SECONDS_PER_DAY)
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "account_id": a["id"],
            "comm_type": body["comm_type"],
            "wave": body["wave"],
            "send_after": iso_ms(send_after),
            "send_before": iso_ms(send_before),
            "scheduled_send_date": iso_ms(send_after),
            "_send_after": send_after,
            "_send_before": send_before,
            "_scheduled_send_date": send_after,
            "resend_count": 0,
            "status": "DRAFT",
        }
    )
    DB["customer_comms"][rec["id"]] = rec
    return ok_object(comm_view(rec), 201)


@app.get("/api/v1/customer-comms")
def list_comms():
    check_role({"ProjectManager", "CommunicationsOfficer"})
    items = list(DB["customer_comms"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [c for c in items if c["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    wave = request.args.get("wave")
    if wave is not None:
        items = [c for c in items if c["wave"] == int(wave)]
    return list_response([comm_view(c) for c in items])


@app.get("/api/v1/customer-comms/<cid>")
def get_comm(cid):
    check_role({"ProjectManager", "CommunicationsOfficer"})
    c = get_or_404("customer_comms", cid)
    return ok_object(comm_view(c))


@app.post("/api/v1/customer-comms/<cid>/schedule")
def schedule_comm(cid):
    check_role({"CommunicationsOfficer"})
    c = get_or_404("customer_comms", cid)
    body = validate_body(get_body(), {"expected_project_version": ("int", True)})
    p = project_of(c)
    if body["expected_project_version"] != p["version"]:
        fail("ERR_STALE_VERSION", "expected_project_version does not match.")
    if c["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", f"Comm in {c['status']} cannot be scheduled.")
    a = DB["accounts"].get(c["account_id"])
    if a is None or a["status"] not in {"MAPPED", "EXCEPTION", "CLEARED"}:
        fail(
            "ERR_INVALID_STATE",
            "Account must be MAPPED, EXCEPTION, or CLEARED to schedule.",
        )
    if p["status"] in {"CUTOVER_PLANNED", "LIVE"} or a["frozen_flag"]:
        fail("ERR_FROZEN", "File freeze in effect.")
    c["status"] = "SCHEDULED"
    c["_scheduled_send_date"] = c["_send_after"]
    c["scheduled_send_date"] = c["send_after"]
    touch(c)
    bump_project(p)
    return ok_object(comm_view(c))


@app.post("/api/v1/customer-comms/<cid>/send")
def send_comm(cid):
    check_role({"CommunicationsOfficer"})
    c = get_or_404("customer_comms", cid)
    if c["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", f"Comm in {c['status']} cannot be sent.")
    now = clock_now()
    if not (c["_scheduled_send_date"] <= now <= c["_send_before"]):
        fail("ERR_OUTSIDE_WINDOW", "Comm send window not satisfied.")
    c["status"] = "SENT"
    touch(c)
    return ok_object(comm_view(c))


@app.post("/api/v1/customer-comms/<cid>/deliver")
def deliver_comm(cid):
    check_role({"CommunicationsOfficer"})
    c = get_or_404("customer_comms", cid)
    if c["status"] != "SENT":
        fail("ERR_INVALID_STATE", f"Comm in {c['status']} cannot be delivered.")
    c["status"] = "DELIVERED"
    touch(c)
    return ok_object(comm_view(c))


@app.post("/api/v1/customer-comms/<cid>/fail")
def fail_comm(cid):
    check_role({"CommunicationsOfficer"})
    c = get_or_404("customer_comms", cid)
    if c["status"] != "SENT":
        fail("ERR_INVALID_STATE", f"Comm in {c['status']} cannot be failed.")
    c["status"] = "FAILED"
    touch(c)
    return ok_object(comm_view(c))


@app.post("/api/v1/customer-comms/<cid>/resend")
def resend_comm(cid):
    check_role({"CommunicationsOfficer"})
    c = get_or_404("customer_comms", cid)
    if c["status"] != "FAILED":
        fail("ERR_INVALID_STATE", f"Comm in {c['status']} cannot be resent.")
    c["resend_count"] += 1
    new_sched = c["_send_after"] + timedelta(
        seconds=c["resend_count"] * SECONDS_PER_DAY
    )
    c["_scheduled_send_date"] = new_sched
    c["scheduled_send_date"] = iso_ms(new_sched)
    c["status"] = "SENT"
    touch(c)
    return ok_object(comm_view(c))


@app.post("/api/v1/customer-comms/<cid>/cancel")
def cancel_comm(cid):
    check_role({"CommunicationsOfficer"})
    c = get_or_404("customer_comms", cid)
    if c["status"] not in {"DRAFT", "SCHEDULED"}:
        fail("ERR_INVALID_STATE", f"Comm in {c['status']} cannot be cancelled.")
    c["status"] = "CANCELLED"
    touch(c)
    return ok_object(comm_view(c))


# ---------------------------------------------------------------------------
# Defect
# ---------------------------------------------------------------------------

SEVERITIES = {"SEV1", "SEV2", "SEV3"}
SLA_HOURS = {"SEV1": 24, "SEV2": 72, "SEV3": 168}
SEV_WEIGHT = {"SEV1": 100, "SEV2": 50, "SEV3": 20}
DEFECT_STATUSES = {"OPEN", "TRIAGED", "IN_FIX", "RESOLVED", "REOPENED", "CLOSED"}


def defect_view(d):
    return {
        "id": d["id"],
        "project_id": d["project_id"],
        "title": d["title"],
        "severity": d["severity"],
        "linked_system_id": d["linked_system_id"],
        "reported_by": d["reported_by"],
        "status": d["status"],
        "triage_priority": d["triage_priority"],
        "opened_at": d["opened_at"],
        "sla_deadline": d["sla_deadline"],
        "resolved_at": d["resolved_at"],
        "credit_eligible": d["credit_eligible"],
        "reopened_count": d["reopened_count"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@app.post("/api/v1/defects")
def create_defect():
    ctx = check_role({"ProjectManager", "OperationsLead"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "title": ("string", True),
            "severity": ("string", True),
            "linked_system_id": ("string", False),
        },
    )
    p = get_or_404("projects", body["project_id"])
    validate_enum(body["severity"], SEVERITIES, "severity")
    linked = None
    if body.get("linked_system_id") is not None:
        s = get_or_404("ancillary_systems", body["linked_system_id"])
        if s["project_id"] != p["id"]:
            fail("ERR_INVALID_REFERENCE", "Linked system belongs to another project.")
        linked = s["id"]
    now = clock_now()
    deadline = now + timedelta(hours=SLA_HOURS[body["severity"]])
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "title": body["title"],
            "severity": body["severity"],
            "linked_system_id": linked,
            "reported_by": ctx["uid"],
            "status": "OPEN",
            "triage_priority": None,
            "opened_at": iso_ms(now),
            "sla_deadline": iso_ms(deadline),
            "_opened": now,
            "_sla_deadline": deadline,
            "resolved_at": None,
            "_resolved": None,
            "credit_eligible": False,
            "reopened_count": 0,
        }
    )
    DB["defects"][rec["id"]] = rec
    return ok_object(defect_view(rec), 201)


@app.get("/api/v1/defects")
def list_defects():
    check_role({"ProjectManager", "OperationsLead", "VendorTriageLead", "FinanceController"})
    items = list(DB["defects"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [d for d in items if d["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    sev = request.args.get("severity")
    if sev is not None:
        items = [d for d in items if d["severity"] == sev]
    lsi = request.args.get("linked_system_id")
    if lsi is not None:
        items = [d for d in items if d.get("linked_system_id") == lsi]
    return list_response([defect_view(d) for d in items])


@app.get("/api/v1/defects/<did>")
def get_defect(did):
    check_role({"ProjectManager", "OperationsLead", "VendorTriageLead", "FinanceController"})
    d = get_or_404("defects", did)
    return ok_object(defect_view(d))


@app.post("/api/v1/defects/<did>/triage")
def triage_defect(did):
    ctx = check_role({"VendorTriageLead"})
    d = get_or_404("defects", did)
    if d["status"] != "OPEN":
        fail("ERR_INVALID_STATE", f"Defect in {d['status']} cannot be triaged.")
    if d["reported_by"] == ctx["uid"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "Reporter cannot triage the defect.")
    now = clock_now()
    age_hours = int((now - d["_opened"]).total_seconds() // 3600)
    age_weight = min(age_hours // 24, 3) * 10
    score = SEV_WEIGHT[d["severity"]] + age_weight
    if score >= 110:
        prio = 1
    elif score >= 90:
        prio = 2
    elif score >= 60:
        prio = 3
    elif score >= 30:
        prio = 4
    else:
        prio = 5
    d["triage_priority"] = prio
    d["status"] = "TRIAGED"
    touch(d)
    return ok_object(defect_view(d))


@app.post("/api/v1/defects/<did>/start-fix")
def start_fix_defect(did):
    check_role({"VendorTriageLead"})
    d = get_or_404("defects", did)
    if d["status"] != "TRIAGED":
        fail("ERR_INVALID_STATE", f"Defect in {d['status']} cannot start fix.")
    d["status"] = "IN_FIX"
    touch(d)
    return ok_object(defect_view(d))


@app.post("/api/v1/defects/<did>/reject-fix")
def reject_fix_defect(did):
    check_role({"VendorTriageLead"})
    d = get_or_404("defects", did)
    if d["status"] != "IN_FIX":
        fail("ERR_INVALID_STATE", f"Defect in {d['status']} cannot reject fix.")
    d["status"] = "OPEN"
    touch(d)
    return ok_object(defect_view(d))


def _resolve_defect(d):
    now = clock_now()
    d["status"] = "RESOLVED"
    d["_resolved"] = now
    d["resolved_at"] = iso_ms(now)
    d["credit_eligible"] = now > d["_sla_deadline"]
    touch(d)
    if d.get("linked_system_id"):
        s = DB["ancillary_systems"].get(d["linked_system_id"])
        if s is not None:
            if s["status"] == "VERIFIED":
                s["status"] = "INTEGRATING"
                touch(s)
            elif s["status"] == "RETEST_PASSED":
                s["status"] = "FAILED"
                touch(s)


@app.post("/api/v1/defects/<did>/resolve")
def resolve_defect(did):
    check_role({"VendorTriageLead"})
    d = get_or_404("defects", did)
    if d["status"] not in {"OPEN", "TRIAGED", "IN_FIX", "REOPENED"}:
        fail("ERR_INVALID_STATE", f"Defect in {d['status']} cannot be resolved.")
    _resolve_defect(d)
    return ok_object(defect_view(d))


@app.post("/api/v1/defects/<did>/reopen")
def reopen_defect(did):
    check_role({"ProjectManager"})
    d = get_or_404("defects", did)
    if d["status"] != "RESOLVED":
        fail("ERR_INVALID_STATE", f"Defect in {d['status']} cannot be reopened.")
    d["status"] = "REOPENED"
    d["reopened_count"] += 1
    d["_resolved"] = None
    d["resolved_at"] = None
    d["credit_eligible"] = False
    touch(d)
    for sc in DB["service_credits"].values():
        if (
            sc["project_id"] == d["project_id"]
            and sc["claim_status"] == "OPEN"
            and d["id"] in sc["defect_ids"]
        ):
            sc["claim_status"] = "DISPUTED"
            sc["dispute_note"] = "auto: defect reopened"
            touch(sc)
    return ok_object(defect_view(d))


@app.post("/api/v1/defects/<did>/close")
def close_defect(did):
    check_role({"ProjectManager"})
    d = get_or_404("defects", did)
    if d["status"] != "RESOLVED":
        fail("ERR_INVALID_STATE", f"Defect in {d['status']} cannot be closed.")
    for sc in DB["service_credits"].values():
        if (
            sc["project_id"] == d["project_id"]
            and sc["claim_status"] == "OPEN"
            and d["id"] in sc["defect_ids"]
        ):
            fail(
                "ERR_INVALID_STATE",
                "Defect is referenced by an OPEN service credit claim.",
            )
    d["status"] = "CLOSED"
    touch(d)
    return ok_object(defect_view(d))


# ---------------------------------------------------------------------------
# ServiceCredit
# ---------------------------------------------------------------------------

MONTHLY_COVERED_HOURS = 4
RATE_CENTS_PER_HOUR = 25000
MONTHLY_CAP_CENTS = 200000
CLAIM_STATUSES = {"OPEN", "APPROVED", "DISPUTED", "PAID", "REJECTED"}


def sc_view(sc):
    return {
        "id": sc["id"],
        "project_id": sc["project_id"],
        "month": sc["month"],
        "defect_ids": sc["defect_ids"],
        "claim_status": sc["claim_status"],
        "approved_by": sc["approved_by"],
        "breach_hours": sc["breach_hours"],
        "credit_cents": sc["credit_cents"],
        "dispute_note": sc["dispute_note"],
        "created_at": sc["created_at"],
        "updated_at": sc["updated_at"],
        "version": sc["version"],
    }


def compute_credit(defect_ids):
    import math

    breach = []
    for did in defect_ids:
        d = DB["defects"][did]
        secs = (d["_resolved"] - d["_sla_deadline"]).total_seconds()
        breach.append(math.ceil(secs / 3600))
    total = sum(breach)
    uncovered = max(0, total - MONTHLY_COVERED_HOURS)
    raw = uncovered * RATE_CENTS_PER_HOUR
    credit = min(raw, MONTHLY_CAP_CENTS)
    return breach, credit


@app.post("/api/v1/service-credits")
def create_service_credit():
    check_role({"FinanceController"})
    body = validate_body(
        get_body(),
        {
            "project_id": ("string", True),
            "month": ("string", True),
            "defect_ids": ("array", True),
        },
    )
    p = get_or_404("projects", body["project_id"])
    month = validate_month(body["month"], "month")
    defect_ids = body["defect_ids"]
    if len(defect_ids) == 0:
        fail("ERR_INVALID_REQUEST", "defect_ids must be non-empty.")
    for did in defect_ids:
        if not isinstance(did, str):
            fail("ERR_INVALID_REQUEST", "defect_ids must contain strings.")
    defects = []
    for did in defect_ids:
        d = DB["defects"].get(did)
        if d is None:
            fail("ERR_NOT_FOUND", f"Defect {did} not found.")
        defects.append(d)
    # invariant: one OPEN claim per project per month
    for sc in DB["service_credits"].values():
        if (
            sc["project_id"] == p["id"]
            and sc["month"] == month
            and sc["claim_status"] == "OPEN"
        ):
            fail(
                "ERR_INVARIANT_VIOLATION",
                "An OPEN claim already exists for this project and month.",
            )
    # eligibility
    open_claim_defects = set()
    for sc in DB["service_credits"].values():
        if sc["project_id"] == p["id"] and sc["claim_status"] == "OPEN":
            open_claim_defects.update(sc["defect_ids"])
    for d in defects:
        if not d["credit_eligible"]:
            fail("ERR_CREDIT_INELIGIBLE", "A defect is not credit_eligible.")
        if month_of(d["_sla_deadline"]) != month:
            fail(
                "ERR_CREDIT_INELIGIBLE",
                "A defect's sla_deadline month differs from the claim month.",
            )
        if d["id"] in open_claim_defects:
            fail("ERR_CREDIT_INELIGIBLE", "A defect is already in an OPEN claim.")
    breach, credit = compute_credit(defect_ids)
    rec = new_common()
    rec.update(
        {
            "project_id": p["id"],
            "month": month,
            "defect_ids": list(defect_ids),
            "claim_status": "OPEN",
            "approved_by": None,
            "breach_hours": breach,
            "credit_cents": credit,
            "dispute_note": None,
        }
    )
    DB["service_credits"][rec["id"]] = rec
    return ok_object(sc_view(rec), 201)


@app.get("/api/v1/service-credits")
def list_service_credits():
    check_role({"ProjectManager", "VendorTriageLead", "FinanceController"})
    items = list(DB["service_credits"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [s for s in items if s["project_id"] == project_id]
    cs = request.args.get("claim_status")
    if cs is not None:
        items = [s for s in items if s["claim_status"] == cs]
    month = request.args.get("month")
    if month is not None:
        items = [s for s in items if s["month"] == month]
    return list_response([sc_view(s) for s in items])


@app.get("/api/v1/service-credits/<scid>")
def get_service_credit(scid):
    check_role({"ProjectManager", "VendorTriageLead", "FinanceController"})
    sc = get_or_404("service_credits", scid)
    return ok_object(sc_view(sc))


@app.post("/api/v1/service-credits/<scid>/approve")
def approve_service_credit(scid):
    ctx = check_role({"FinanceController"})
    sc = get_or_404("service_credits", scid)
    if sc["claim_status"] != "OPEN":
        fail("ERR_INVALID_STATE", f"Claim in {sc['claim_status']} cannot be approved.")
    for did in sc["defect_ids"]:
        d = DB["defects"][did]
        if d["status"] != "RESOLVED" or not d["credit_eligible"]:
            fail(
                "ERR_CREDIT_INELIGIBLE",
                "A defect is no longer RESOLVED and credit_eligible.",
            )
    sc["claim_status"] = "APPROVED"
    sc["approved_by"] = ctx["uid"]
    touch(sc)
    return ok_object(sc_view(sc))


@app.post("/api/v1/service-credits/<scid>/pay")
def pay_service_credit(scid):
    ctx = check_role({"FinanceController"})
    sc = get_or_404("service_credits", scid)
    if sc["claim_status"] != "APPROVED":
        fail("ERR_INVALID_STATE", f"Claim in {sc['claim_status']} cannot be paid.")
    for did in sc["defect_ids"]:
        d = DB["defects"][did]
        if d["status"] != "RESOLVED":
            fail("ERR_CREDIT_INELIGIBLE", "A defect is no longer RESOLVED.")
    if sc["approved_by"] == ctx["uid"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "Approver cannot pay the claim.")
    sc["claim_status"] = "PAID"
    touch(sc)
    return ok_object(sc_view(sc))


@app.post("/api/v1/service-credits/<scid>/dispute")
def dispute_service_credit(scid):
    check_role({"VendorTriageLead"})
    sc = get_or_404("service_credits", scid)
    body = validate_body(get_body(), {"dispute_note": ("string", True)})
    if sc["claim_status"] not in {"OPEN", "APPROVED"}:
        fail("ERR_INVALID_STATE", f"Claim in {sc['claim_status']} cannot be disputed.")
    sc["claim_status"] = "DISPUTED"
    sc["dispute_note"] = body["dispute_note"]
    touch(sc)
    return ok_object(sc_view(sc))


@app.post("/api/v1/service-credits/<scid>/reopen")
def reopen_service_credit(scid):
    check_role({"FinanceController"})
    sc = get_or_404("service_credits", scid)
    if sc["claim_status"] != "DISPUTED":
        fail("ERR_INVALID_STATE", f"Claim in {sc['claim_status']} cannot be reopened.")
    for did in sc["defect_ids"]:
        d = DB["defects"][did]
        if d["status"] != "RESOLVED" or not d["credit_eligible"]:
            fail(
                "ERR_CREDIT_INELIGIBLE",
                "A defect is not RESOLVED and credit_eligible.",
            )
    breach, credit = compute_credit(sc["defect_ids"])
    sc["breach_hours"] = breach
    sc["credit_cents"] = credit
    sc["claim_status"] = "OPEN"
    touch(sc)
    return ok_object(sc_view(sc))


@app.post("/api/v1/service-credits/<scid>/reject")
def reject_service_credit(scid):
    check_role({"FinanceController"})
    sc = get_or_404("service_credits", scid)
    if sc["claim_status"] != "OPEN":
        fail("ERR_INVALID_STATE", f"Claim in {sc['claim_status']} cannot be rejected.")
    if not any(not DB["defects"][did]["credit_eligible"] for did in sc["defect_ids"]):
        fail(
            "ERR_CREDIT_INELIGIBLE",
            "Reject requires at least one defect no longer credit_eligible.",
        )
    sc["claim_status"] = "REJECTED"
    touch(sc)
    return ok_object(sc_view(sc))


# ---------------------------------------------------------------------------
# CutoverPlan / CutoverTask
# ---------------------------------------------------------------------------

OWNER_ROLES = {"CONVERSION_ENGINEER", "OPERATIONS_LEAD"}
PLAN_STATUSES = {"DRAFT", "SCHEDULED", "GO", "LIVE", "ROLLED_BACK"}
TASK_STATUSES = {"PENDING", "RUNNING", "COMPLETE", "SKIPPED", "FAILED"}


def plan_view(plan):
    return {
        "id": plan["id"],
        "project_id": plan["project_id"],
        "planned_cutover_date": plan["planned_cutover_date"],
        "file_freeze_start": plan["file_freeze_start"],
        "reopen_target": plan["reopen_target"],
        "go_no_go_checkpoint": plan["go_no_go_checkpoint"],
        "status": plan["status"],
        "created_at": plan["created_at"],
    }


def task_view(t):
    return {
        "id": t["id"],
        "parent_plan_id": t["parent_plan_id"],
        "task_name": t["task_name"],
        "sequence": t["sequence"],
        "conversion_window_start": t["conversion_window_start"],
        "conversion_window_end": t["conversion_window_end"],
        "depends_on_task_id": t["depends_on_task_id"],
        "owner_role": t["owner_role"],
        "status": t["status"],
        "duration_minutes": t["duration_minutes"],
        "created_at": t["created_at"],
    }


@app.get("/api/v1/plans")
def list_plans():
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    items = list(DB["plans"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [pl for pl in items if pl["project_id"] == project_id]
    return list_response([plan_view(pl) for pl in items])


@app.get("/api/v1/plans/<pid>")
def get_plan(pid):
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    pl = get_or_404("plans", pid)
    return ok_object(plan_view(pl))


@app.post("/api/v1/tasks")
def create_task():
    check_role({"ProjectManager"})
    body = validate_body(
        get_body(),
        {
            "plan_id": ("string", True),
            "task_name": ("string", True),
            "sequence": ("int", True),
            "conversion_window_start": ("string", True),
            "conversion_window_end": ("string", True),
            "owner_role": ("string", True),
            "depends_on_task_id": ("string", False),
        },
    )
    plan = get_or_404("plans", body["plan_id"])
    validate_enum(body["owner_role"], OWNER_ROLES, "owner_role")
    ws = validate_datetime(body["conversion_window_start"], "conversion_window_start")
    we = validate_datetime(body["conversion_window_end"], "conversion_window_end")
    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", f"Plan in {plan['status']} cannot accept tasks.")
    # window geometry
    if not (ws > plan["_ffs"]):
        fail(
            "ERR_OUTSIDE_WINDOW",
            "conversion_window_start must be strictly after file_freeze_start.",
        )
    if not (we > ws):
        fail(
            "ERR_OUTSIDE_WINDOW",
            "conversion_window_end must be strictly after conversion_window_start.",
        )
    # sequence uniqueness/density
    existing = [
        t for t in DB["tasks"].values() if t["parent_plan_id"] == plan["id"]
    ]
    if any(t["sequence"] == body["sequence"] for t in existing):
        fail("ERR_INVARIANT_VIOLATION", "sequence must be unique within the plan.")
    n = len(existing)
    if not (1 <= body["sequence"] <= n + 1):
        fail("ERR_INVARIANT_VIOLATION", "sequence must be dense (1..N).")
    dep_id = body.get("depends_on_task_id")
    if dep_id is not None:
        dep = DB["tasks"].get(dep_id)
        if dep is None or dep["parent_plan_id"] != plan["id"]:
            fail("ERR_INVALID_REFERENCE", "depends_on_task_id must reference a task of the same plan.")
        if dep["sequence"] >= body["sequence"]:
            fail(
                "ERR_INVALID_REFERENCE",
                "depends_on_task_id must reference a task with a smaller sequence.",
            )
    rec = new_light()
    rec.update(
        {
            "parent_plan_id": plan["id"],
            "task_name": body["task_name"],
            "sequence": body["sequence"],
            "conversion_window_start": iso_ms(ws),
            "conversion_window_end": iso_ms(we),
            "_ws": ws,
            "_we": we,
            "depends_on_task_id": dep_id,
            "owner_role": body["owner_role"],
            "status": "PENDING",
            "duration_minutes": None,
            "_started": None,
        }
    )
    DB["tasks"][rec["id"]] = rec
    return ok_object(task_view(rec), 201)


@app.get("/api/v1/tasks")
def list_tasks():
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    items = list(DB["tasks"].values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [t for t in items if t["parent_plan_id"] == plan_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    dep = request.args.get("depends_on_task_id")
    if dep is not None:
        items = [t for t in items if t.get("depends_on_task_id") == dep]
    items = sorted(items, key=lambda t: t["sequence"])
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return ok_list([task_view(t) for t in page], limit, offset, total)


@app.get("/api/v1/tasks/<tid>")
def get_task(tid):
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    t = get_or_404("tasks", tid)
    return ok_object(task_view(t))


@app.get("/api/v1/tasks/<tid>/dependents")
def list_task_dependents(tid):
    check_role({"ProjectManager", "ConversionEngineer", "OperationsLead"})
    t = get_or_404("tasks", tid)
    items = [
        x for x in DB["tasks"].values() if x.get("depends_on_task_id") == t["id"]
    ]
    items = sorted(items, key=lambda x: x["sequence"])
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return ok_list([task_view(x) for x in page], limit, offset, total)


@app.post("/api/v1/plans/<pid>/schedule")
def schedule_plan(pid):
    check_role({"ProjectManager"})
    plan = get_or_404("plans", pid)
    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", f"Plan in {plan['status']} cannot be scheduled.")
    tasks = [t for t in DB["tasks"].values() if t["parent_plan_id"] == plan["id"]]
    if not tasks:
        fail("ERR_PHASE_GATE", "Plan requires at least one task to schedule.")
    earliest_ws = min(t["_ws"] for t in tasks)
    latest_we = max(t["_we"] for t in tasks)
    if not (plan["_ffs"] < earliest_ws):
        fail("ERR_OUTSIDE_WINDOW", "file_freeze_start must be strictly before the earliest task window.")
    if not (plan["_ffs"] < plan["_gng"] < plan["_reopen"]):
        fail(
            "ERR_OUTSIDE_WINDOW",
            "go_no_go_checkpoint must sit strictly between file_freeze_start and reopen_target.",
        )
    if not (plan["_reopen"] >= latest_we):
        fail("ERR_OUTSIDE_WINDOW", "reopen_target must be at or after the latest window end.")
    if freeze_channel_busy(plan["project_id"], plan["_ffs"]):
        fail("ERR_FREEZE_CHANNEL_BUSY", "Freeze channel busy.")
    plan["status"] = "SCHEDULED"
    return ok_object(plan_view(plan))


@app.post("/api/v1/plans/<pid>/go")
def go_plan(pid):
    check_role({"ProjectManager"})
    plan = get_or_404("plans", pid)
    if plan["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", f"Plan in {plan['status']} cannot be declared GO.")
    now = clock_now()
    if not (now >= plan["_gng"]):
        fail("ERR_OUTSIDE_WINDOW", "Clock is before the go/no-go checkpoint.")
    if any(
        t["parent_plan_id"] == plan["id"] and t["status"] == "FAILED"
        for t in DB["tasks"].values()
    ):
        fail("ERR_PHASE_GATE", "A FAILED task blocks GO.")
    plan["status"] = "GO"
    return ok_object(plan_view(plan))


@app.post("/api/v1/plans/<pid>/rollback")
def rollback_plan(pid):
    check_role({"ProjectManager"})
    plan = get_or_404("plans", pid)
    if plan["status"] not in {"SCHEDULED", "GO"}:
        fail("ERR_INVALID_STATE", f"Plan in {plan['status']} cannot be rolled back.")
    p = get_or_404("projects", plan["project_id"])
    for t in DB["tasks"].values():
        if t["parent_plan_id"] == plan["id"] and t["status"] in {"PENDING", "RUNNING"}:
            t["status"] = "SKIPPED"
    for a in DB["accounts"].values():
        if a["project_id"] == p["id"] and a["status"] in {"MAPPED", "CLEARED", "EXCEPTION"}:
            a["status"] = "BLOCKED"
            touch(a)
    recompute_all_gls(p["id"])
    p["status"] = "MOCK_CONVERSION"
    p["cutover_scheduled_date"] = None
    touch(p)
    for r in DB["mock_runs"].values():
        if r["project_id"] == p["id"] and r["is_cutover_baseline"]:
            r["is_cutover_baseline"] = False
            touch(r)
    plan["status"] = "ROLLED_BACK"
    return ok_object(plan_view(plan))


def _check_task_owner(t):
    ctx = role_ctx()
    required = (
        "ConversionEngineer" if t["owner_role"] == "CONVERSION_ENGINEER" else "OperationsLead"
    )
    if ctx["role"] != required:
        fail("ERR_FORBIDDEN", "Role not permitted to act on this task.")
    return ctx


@app.post("/api/v1/tasks/<tid>/start")
def start_task(tid):
    t = get_or_404("tasks", tid)
    _check_task_owner(t)
    if t["status"] != "PENDING":
        fail("ERR_INVALID_STATE", f"Task in {t['status']} cannot be started.")
    plan = DB["plans"][t["parent_plan_id"]]
    if plan["status"] != "GO":
        fail("ERR_PHASE_GATE", "Plan must be GO to start tasks.")
    now = clock_now()
    if not (now >= t["_ws"] and now < t["_we"]):
        fail("ERR_OUTSIDE_WINDOW", "Clock is outside the task conversion window.")
    if t.get("depends_on_task_id"):
        dep = DB["tasks"].get(t["depends_on_task_id"])
        if dep is None or dep["status"] != "COMPLETE":
            fail("ERR_INVALID_STATE", "Predecessor task is not COMPLETE.")
    t["status"] = "RUNNING"
    t["_started"] = now
    return ok_object(task_view(t))


@app.post("/api/v1/tasks/<tid>/complete")
def complete_task(tid):
    t = get_or_404("tasks", tid)
    _check_task_owner(t)
    if t["status"] != "RUNNING":
        fail("ERR_INVALID_STATE", f"Task in {t['status']} cannot be completed.")
    now = clock_now()
    if not (now <= t["_we"] + timedelta(minutes=30)):
        fail("ERR_OUTSIDE_WINDOW", "Completion grace window expired.")
    t["status"] = "COMPLETE"
    t["duration_minutes"] = int((now - t["_started"]).total_seconds() // 60)
    return ok_object(task_view(t))


@app.post("/api/v1/tasks/<tid>/fail")
def fail_task(tid):
    t = get_or_404("tasks", tid)
    _check_task_owner(t)
    if t["status"] != "RUNNING":
        fail("ERR_INVALID_STATE", f"Task in {t['status']} cannot be failed.")
    t["status"] = "FAILED"
    return ok_object(task_view(t))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
