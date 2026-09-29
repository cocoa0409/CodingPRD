"""Suppliers, plant lines and plant audits."""
from flask import Blueprint

import calculations as calc
import serializers as ser
from db import db, now
from domain import (
    LIVE_RUN_STATUSES,
    composite_for_window,
    cost_models_of_supplier,
    get_audit,
    get_program,
    get_supplier,
    guard_program_open,
    hold_runs_for_supplier,
    new_row,
    program_of_supplier,
    refresh_cached_composite,
    refresh_landed_costs,
    refresh_supplier_counters,
    reinstate_supplier_items,
    release_held_runs_for_supplier,
    rolling_window_start,
    runs_of_supplier,
    suspend_supplier_items,
    touch,
)
from errors import fail
from listing import (
    AUDIT_RESULT_SET,
    AUDIT_STATUS_SET,
    AUDIT_TYPE_SET,
    QUALIFICATION_SET,
    no_query,
    paginate,
)
from middleware import (
    ALL_ROLES,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_QUALITY_AUDITOR,
    ROLE_SOURCING_MANAGER,
    ROLE_SUPPLIER_USER,
    Field,
    authenticate,
    validate_body,
)
from response import object_response
from serializers import num

bp = Blueprint("suppliers", __name__)

DEFAULT_CHANGEOVER_BUFFER_MINUTES = 120


@bp.post("/private-label/suppliers")
def create_supplier():
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body(
        {
            "program_id": Field("string", required=True),
            "legal_name": Field("string", required=True),
            "plant_country": Field(
                "string",
                required=True,
                check=lambda v: len(v) == 2 and v.isalpha(),
                detail="must be a two-letter ISO 3166-1 alpha-2 country code",
            ),
            "gfsi_certificate_expiry": Field("datetime", required=True),
        }
    )
    program = get_program(body["program_id"])
    guard_program_open(program)
    row = new_row(
        {
            "program_id": program["id"],
            "legal_name": body["legal_name"],
            "plant_country": body["plant_country"],
            "gfsi_certificate_expiry": body["gfsi_certificate_expiry"],
            "qualification_status": "PROSPECT",
            "qualified_at": None,
            "composite_score_cached": None,
            "probation_item_count": 0,
            "weighted_complaint_points": 0,
        }
    )
    db.suppliers[row["id"]] = row
    return object_response(ser.supplier_out(row), 201)


@bp.get("/private-label/suppliers/<supplier_id>")
def read_supplier(supplier_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.supplier_out(get_supplier(supplier_id)))


@bp.get("/private-label/suppliers")
def list_suppliers():
    authenticate(ALL_ROLES)
    return paginate(
        db.suppliers,
        {"program_id": "string", "qualification_status": QUALIFICATION_SET},
        ser.supplier_out,
    )


@bp.get("/private-label/suppliers/<supplier_id>/scorecard")
def read_scorecard(supplier_id):
    user_id, role = authenticate(ALL_ROLES)
    no_query()
    supplier = get_supplier(supplier_id)
    if role == ROLE_SUPPLIER_USER and user_id != supplier["id"]:
        fail("ERR_SUPPLIER_SCOPE_VIOLATION", "A SupplierUser may read only its own scorecard.")
    rolling = composite_for_window(supplier, rolling_window_start())
    period = composite_for_window(supplier, supplier["qualified_at"])
    from db import iso

    return object_response(
        {
            "supplier_id": supplier["id"],
            "rolling_12m_composite_score": num(rolling["composite"]),
            "rolling_12m_audit_component": num(rolling["audit_component"]),
            "rolling_12m_complaint_component": num(rolling["complaint_component"]),
            "rolling_12m_delivery_component": num(rolling["delivery_component"]),
            "rolling_12m_window_start": iso(rolling["window_start"]),
            "period_to_date_composite_score": num(period["composite"]),
            "period_to_date_audit_component": num(period["audit_component"]),
            "period_to_date_complaint_component": num(period["complaint_component"]),
            "period_to_date_delivery_component": num(period["delivery_component"]),
            "period_to_date_window_start": iso(period["window_start"]),
        }
    )


DECISION_ADMITS = {
    "QUALIFY": ("PROSPECT", "QUALIFIED", "CONDITIONAL"),
    "CONDITIONAL": ("PROSPECT",),
    "SUSPEND": ("QUALIFIED", "CONDITIONAL"),
    "REINSTATE": ("SUSPENDED",),
    "DISQUALIFY": ("SUSPENDED",),
}
BASIS_RESULTS = {
    "QUALIFY": ("PASS",),
    "CONDITIONAL": ("PASS", "CONDITIONAL"),
    "REINSTATE": ("PASS", "CONDITIONAL"),
}


@bp.post("/private-label/suppliers/<supplier_id>/qualification-decision")
def qualification_decision(supplier_id):
    authenticate((ROLE_PROGRAM_DIRECTOR,))
    body = validate_body(
        {
            "decision": Field("string", required=True, enum=frozenset(DECISION_ADMITS.keys())),
            "basis_audit_id": Field("string"),
        }
    )
    supplier = get_supplier(supplier_id)
    basis = get_audit(body["basis_audit_id"]) if body["basis_audit_id"] is not None else None
    guard_program_open(program_of_supplier(supplier))
    decision = body["decision"]
    if supplier["qualification_status"] not in DECISION_ADMITS[decision]:
        fail("ERR_SUPPLIER_STATE_INVALID")
    if decision in ("QUALIFY", "CONDITIONAL"):
        if supplier["gfsi_certificate_expiry"] <= now():
            fail("ERR_GFSI_CERTIFICATE_EXPIRED")
    if decision in BASIS_RESULTS:
        needs_freshness = decision == "REINSTATE" or (
            decision == "QUALIFY" and supplier["qualification_status"] in ("QUALIFIED", "CONDITIONAL")
        )
        if basis is None:
            fail("ERR_AUDIT_BASIS_INVALID", "A basis_audit_id is required for this decision.")
        if (
            basis["supplier_id"] != supplier["id"]
            or basis["audit_type"] != "CAPABILITY"
            or basis["status"] != "FINALIZED"
            or basis["result"] not in BASIS_RESULTS[decision]
        ):
            fail("ERR_AUDIT_BASIS_INVALID")
        if needs_freshness:
            if supplier["qualified_at"] is None or basis["window_end"] <= supplier["qualified_at"]:
                fail("ERR_AUDIT_BASIS_INVALID", "The cited audit is not fresher than qualified_at.")
    if decision == "DISQUALIFY":
        live = [row for row in runs_of_supplier(supplier["id"]) if row["status"] in LIVE_RUN_STATUSES]
        if live:
            fail("ERR_ACTIVE_RUNS_PRESENT")

    if decision == "QUALIFY":
        was_conditional = supplier["qualification_status"] == "CONDITIONAL"
        supplier["qualification_status"] = "QUALIFIED"
        supplier["qualified_at"] = now()
        if was_conditional:
            release_held_runs_for_supplier(supplier)
        refresh_supplier_counters(supplier)
        refresh_cached_composite(supplier)
    elif decision == "CONDITIONAL":
        supplier["qualification_status"] = "CONDITIONAL"
        supplier["qualified_at"] = now()
        hold_runs_for_supplier(supplier, "SUPPLIER_CONDITIONAL")
    elif decision == "SUSPEND":
        supplier["qualification_status"] = "SUSPENDED"
        suspend_supplier_items(supplier)
        hold_runs_for_supplier(supplier, "SUPPLIER_SUSPENDED")
        refresh_supplier_counters(supplier)
    elif decision == "REINSTATE":
        supplier["qualification_status"] = "CONDITIONAL"
        supplier["qualified_at"] = now()
        reinstate_supplier_items(supplier)
        refresh_supplier_counters(supplier)
    else:
        supplier["qualification_status"] = "DISQUALIFIED"
    touch(supplier)
    return object_response(ser.supplier_out(supplier))


@bp.post("/private-label/plant-lines")
def create_plant_line():
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body(
        {
            "supplier_id": Field("string", required=True),
            "line_code": Field("string", required=True),
            "daily_capacity_units": Field(
                "integer", required=True, check=lambda v: v > 0, detail="must be strictly greater than zero"
            ),
            "changeover_buffer_minutes": Field(
                "number", check=lambda v: v >= 0, detail="must not be negative"
            ),
        }
    )
    supplier = get_supplier(body["supplier_id"])
    guard_program_open(program_of_supplier(supplier))
    for row in db.plant_lines.values():
        if row["supplier_id"] == supplier["id"] and row["line_code"] == body["line_code"]:
            fail("ERR_DUPLICATE_LINE_CODE")
    buffer_minutes = body["changeover_buffer_minutes"]
    if "changeover_buffer_minutes" not in body["_supplied"]:
        buffer_minutes = DEFAULT_CHANGEOVER_BUFFER_MINUTES
    row = new_row(
        {
            "supplier_id": supplier["id"],
            "line_code": body["line_code"],
            "daily_capacity_units": body["daily_capacity_units"],
            "changeover_buffer_minutes": buffer_minutes,
        }
    )
    db.plant_lines[row["id"]] = row
    return object_response(ser.plant_line_out(row), 201)


@bp.get("/private-label/plant-lines/<plant_line_id>")
def read_plant_line(plant_line_id):
    from domain import get_plant_line

    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.plant_line_out(get_plant_line(plant_line_id)))


@bp.get("/private-label/plant-lines")
def list_plant_lines():
    authenticate(ALL_ROLES)
    return paginate(db.plant_lines, {"supplier_id": "string"}, ser.plant_line_out)


def _audit_capacity_exceeded(supplier_id, start, end):
    """No instant of the new half-open window may already be covered twice."""
    existing = [row for row in db.plant_audits.values() if row["supplier_id"] == supplier_id]
    probes = [start]
    for row in existing:
        if start < row["window_start"] < end:
            probes.append(row["window_start"])
    for probe in probes:
        covering = 0
        for row in existing:
            if row["window_start"] <= probe < row["window_end"]:
                covering += 1
        if covering >= 2:
            return True
    return False


@bp.post("/private-label/plant-audits")
def create_plant_audit():
    authenticate((ROLE_QUALITY_AUDITOR,))
    body = validate_body(
        {
            "supplier_id": Field("string", required=True),
            "audit_type": Field("string", required=True, enum=AUDIT_TYPE_SET),
            "window_start": Field("datetime", required=True),
            "window_end": Field("datetime", required=True),
        }
    )
    supplier = get_supplier(body["supplier_id"])
    guard_program_open(program_of_supplier(supplier))
    if body["window_end"] <= body["window_start"]:
        fail("ERR_WINDOW_INVALID")
    if _audit_capacity_exceeded(supplier["id"], body["window_start"], body["window_end"]):
        fail("ERR_AUDIT_CAPACITY_EXCEEDED")
    row = new_row(
        {
            "supplier_id": supplier["id"],
            "audit_type": body["audit_type"],
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "food_safety_score": None,
            "sanitation_score": None,
            "capacity_score": None,
            "traceability_score": None,
            "audited_yield_pct": None,
            "result": None,
            "status": "SCHEDULED",
        }
    )
    db.plant_audits[row["id"]] = row
    return object_response(ser.plant_audit_out(row), 201)


@bp.get("/private-label/plant-audits/<plant_audit_id>")
def read_plant_audit(plant_audit_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.plant_audit_out(get_audit(plant_audit_id)))


@bp.get("/private-label/plant-audits")
def list_plant_audits():
    authenticate(ALL_ROLES)
    return paginate(
        db.plant_audits,
        {
            "supplier_id": "string",
            "audit_type": AUDIT_TYPE_SET,
            "result": AUDIT_RESULT_SET,
            "status": AUDIT_STATUS_SET,
        },
        ser.plant_audit_out,
    )


def _pillar(name):
    return Field(
        "integer",
        required=True,
        check=lambda v: 0 <= v <= 100,
        detail="must be a whole number from 0 through 100 inclusive",
    )


@bp.post("/private-label/plant-audits/<plant_audit_id>/finalize")
def finalize_plant_audit(plant_audit_id):
    authenticate((ROLE_QUALITY_AUDITOR,))
    body = validate_body(
        {
            "food_safety_score": _pillar("food_safety_score"),
            "sanitation_score": _pillar("sanitation_score"),
            "capacity_score": _pillar("capacity_score"),
            "traceability_score": _pillar("traceability_score"),
            "audited_yield_pct": Field(
                "number",
                required=True,
                check=lambda v: 0.0 < v <= 100.0,
                detail="must be strictly greater than 0.0 and no more than 100.0",
            ),
        }
    )
    audit = get_audit(plant_audit_id)
    supplier = get_supplier(audit["supplier_id"])
    guard_program_open(program_of_supplier(supplier))
    if audit["status"] != "SCHEDULED":
        fail("ERR_AUDIT_NOT_SCHEDULED")
    audit["food_safety_score"] = body["food_safety_score"]
    audit["sanitation_score"] = body["sanitation_score"]
    audit["capacity_score"] = body["capacity_score"]
    audit["traceability_score"] = body["traceability_score"]
    audit["audited_yield_pct"] = body["audited_yield_pct"]
    audit["result"] = calc.audit_result(
        body["food_safety_score"],
        body["sanitation_score"],
        body["capacity_score"],
        body["traceability_score"],
    )
    audit["status"] = "FINALIZED"
    touch(audit)
    for cost_model in cost_models_of_supplier(supplier["id"]):
        if cost_model["status"] in ("SUBMITTED", "ACCEPTED"):
            refresh_landed_costs(cost_model)
            touch(cost_model)
    refresh_supplier_counters(supplier)
    refresh_cached_composite(supplier)
    touch(supplier)
    return object_response(ser.plant_audit_out(audit))
