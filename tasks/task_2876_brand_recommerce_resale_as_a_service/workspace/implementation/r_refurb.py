"""Refurbishment: bay bookings, logged effort, viability and quality control
(PRD 3.5)."""

from flask import Blueprint

import access
import constants as C
import serialize
import services
import store
import validators as V
from envelope import list_response, object_response, paginate
from errors import ApiError

bp = Blueprint("refurb", __name__)


def _bay_of(order):
    return store.get("refurb_bays", order["refurb_bay_id"])


@bp.post("/refurb-orders")
def create_refurb_order():
    V.guard("RefurbTechnician", "ProgramAdmin")
    payload = V.body()
    resale_unit_id = V.id_field(payload, "resale_unit_id")
    refurb_bay_id = V.id_field(payload, "refurb_bay_id")
    window_start_at = V.ts_field(payload, "window_start_at")
    window_end_at = V.ts_field(payload, "window_end_at")
    expected_version = V.int_field(payload, "expected_resale_unit_version")
    if window_end_at <= window_start_at:
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    unit = store.require("resale_units", resale_unit_id)
    bay = store.require("refurb_bays", refurb_bay_id)

    if unit["lifecycle_state"] != "INTAKE":
        raise ApiError("ERR_UNIT_NOT_SCHEDULABLE")
    if expected_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION")
    if bay["status"] != "AVAILABLE":
        raise ApiError("ERR_BAY_OUT_OF_SERVICE")

    trade_in = store.get("trade_ins", unit["trade_in_id"])
    intake_store_id = None if trade_in is None else trade_in.get("store_location_id")
    if intake_store_id is not None and bay["store_location_id"] != intake_store_id:
        raise ApiError("ERR_BAY_STORE_MISMATCH")

    superseded = [
        o
        for o in store.rows("refurb_orders")
        if o["resale_unit_id"] == unit["id"] and o["status"] == "SCHEDULED"
    ]
    superseded_ids = set(o["id"] for o in superseded)
    for other in store.rows("refurb_orders"):
        if other["refurb_bay_id"] != bay["id"]:
            continue
        if other["status"] in C.REFURB_ORDER_TERMINAL:
            continue
        if other["id"] in superseded_ids:
            continue
        if services.closed_window_conflict(
            window_start_at, window_end_at, other["window_start_at"], other["window_end_at"]
        ):
            raise ApiError("ERR_BAY_WINDOW_CONFLICT")

    order = store.create(
        "refurb_orders",
        {
            "resale_unit_id": unit["id"],
            "refurb_bay_id": bay["id"],
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "status": "SCHEDULED",
            "rework_count": 0,
            "logged_cost_minor": 0,
            "viability_ratio_bp": 0,
            "performed_by_user_id": None,
            "qc_by_user_id": None,
            "viability_override_reason": None,
        },
    )
    for other in superseded:
        other["status"] = "SUPERSEDED"
        store.touch(other)
    store.touch(unit)
    return object_response(serialize.out(order), 201)


@bp.get("/refurb-orders/<order_id>")
def get_refurb_order(order_id):
    V.guard("ProgramAdmin", "RefurbTechnician", "MerchandisingManager")
    return object_response(serialize.out(store.require("refurb_orders", order_id)))


@bp.get("/refurb-orders")
def list_refurb_orders():
    V.guard("ProgramAdmin", "RefurbTechnician", "MerchandisingManager")
    limit, offset = V.pagination()
    status = V.enum_query("status", C.REFURB_ORDER_STATUSES)
    resale_unit_id = V.id_query("resale_unit_id")
    refurb_bay_id = V.id_query("refurb_bay_id")
    if resale_unit_id is not None:
        store.require("resale_units", resale_unit_id)
    if refurb_bay_id is not None:
        store.require("refurb_bays", refurb_bay_id)
    rows = store.rows("refurb_orders")
    if resale_unit_id is not None:
        rows = [o for o in rows if o["resale_unit_id"] == resale_unit_id]
    if refurb_bay_id is not None:
        rows = [o for o in rows if o["refurb_bay_id"] == refurb_bay_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.post("/refurb-orders/<order_id>/tasks")
def log_refurb_task(order_id):
    user_id, _role = V.guard("RefurbTechnician")
    payload = V.body()
    task_type = V.enum_field(payload, "task_type", C.TASK_TYPES)
    labor_minutes = V.int_field(payload, "labor_minutes")
    parts_cost_minor = V.int_field(payload, "parts_cost_minor")
    order = store.require("refurb_orders", order_id)
    if order["status"] != "IN_PROGRESS":
        raise ApiError("ERR_REFURB_ORDER_NOT_LOGGABLE")
    bay = _bay_of(order)
    cost_minor = services.task_line_cost(bay, labor_minutes, parts_cost_minor)
    sequence_no = len(services.order_task_lines(order["id"])) + 1
    line = store.create(
        "refurb_tasks",
        {
            "refurb_order_id": order["id"],
            "task_type": task_type,
            "labor_minutes": labor_minutes,
            "parts_cost_minor": parts_cost_minor,
            "cost_minor": cost_minor,
            "sequence_no": sequence_no,
            "logged_by_user_id": user_id,
        },
        versioned=False,
    )
    services.rematerialize_order(order)
    store.touch(order)
    return object_response(serialize.out(line), 201)


@bp.get("/refurb-orders/<order_id>/tasks")
def list_refurb_tasks(order_id):
    V.guard("ProgramAdmin", "RefurbTechnician", "MerchandisingManager")
    limit, offset = V.pagination()
    task_type = V.enum_query("task_type", C.TASK_TYPES)
    order = store.require("refurb_orders", order_id)
    rows = services.order_task_lines(order["id"])
    if task_type is not None:
        rows = [t for t in rows if t["task_type"] == task_type]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.post("/refurb-orders/<order_id>/start")
def start_refurb_order(order_id):
    user_id, _role = V.guard("RefurbTechnician")
    order = store.require("refurb_orders", order_id)
    if order["status"] not in ("SCHEDULED", "QC_FAILED"):
        raise ApiError("ERR_REFURB_ORDER_NOT_STARTABLE")
    if order["status"] == "QC_FAILED" and order["rework_count"] >= C.REWORK_LIMIT:
        raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")
    bay = _bay_of(order)
    if bay is not None and bay["status"] != "AVAILABLE":
        raise ApiError("ERR_BAY_OUT_OF_SERVICE")
    from_scheduled = order["status"] == "SCHEDULED"
    if not from_scheduled:
        order["rework_count"] += 1
    order["status"] = "IN_PROGRESS"
    order["performed_by_user_id"] = user_id
    store.touch(order)
    if from_scheduled:
        unit = store.get("resale_units", order["resale_unit_id"])
        if unit is not None:
            unit["lifecycle_state"] = "IN_REFURB"
            store.touch(unit)
    return object_response(serialize.out(order))


@bp.post("/refurb-orders/<order_id>/submit-qc")
def submit_qc(order_id):
    V.guard("RefurbTechnician")
    order = store.require("refurb_orders", order_id)
    if order["status"] != "IN_PROGRESS":
        raise ApiError("ERR_REFURB_ORDER_NOT_QC_SUBMITTABLE")
    services.rematerialize_order(order)
    order["status"] = "QC_PENDING"
    store.touch(order)
    return object_response(serialize.out(order))


@bp.post("/refurb-orders/<order_id>/qc-decision")
def qc_decision(order_id):
    user_id, role = V.guard("RefurbTechnician", "ProgramAdmin")
    payload = V.body()
    decision = V.enum_field(payload, "decision", C.QC_DECISIONS)
    override_reason = V.str_field(
        payload, "viability_override_reason", required=False, allow_blank=True
    )
    order = store.require("refurb_orders", order_id)
    if order["status"] != "QC_PENDING":
        raise ApiError("ERR_REFURB_ORDER_NOT_QC_DECIDABLE")
    if order.get("performed_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    unit = store.get("resale_units", order["resale_unit_id"])
    grade_policy = services.grade_policy_or_error(
        unit["product_category"], unit["condition_grade"]
    )

    if decision == "FAIL":
        if order["rework_count"] >= C.REWORK_LIMIT:
            raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")
        order["status"] = "QC_FAILED"
        order["qc_by_user_id"] = user_id
        store.touch(order)
        return object_response(serialize.out(order))

    if decision == "PASS":
        cap = grade_policy["refurb_budget_cap_pct_bp"]
        if order["viability_ratio_bp"] > cap and override_reason is None:
            raise ApiError("ERR_REFURB_NOT_VIABLE")
        if override_reason is not None and role != "ProgramAdmin":
            raise ApiError("ERR_OVERRIDE_ROLE_REQUIRED")
        if override_reason is not None:
            order["viability_override_reason"] = override_reason
        order["status"] = "COMPLETED"
        order["qc_by_user_id"] = user_id
        store.touch(order)
        unit["lifecycle_state"] = "READY"
        if unit["ownership_treatment"] == "OWNED_INVENTORY":
            unit["accounting_state"] = "CAPITALIZED"
            unit["capitalized_cost_minor"] = services.capitalized_cost(unit, order)
        store.touch(unit)
        return object_response(serialize.out(order))

    # SALVAGE: the unit is written off and leaves the diverted bucket.
    if override_reason is not None and role != "ProgramAdmin":
        raise ApiError("ERR_OVERRIDE_ROLE_REQUIRED")
    order["status"] = "SALVAGED"
    order["qc_by_user_id"] = user_id
    if override_reason is not None:
        order["viability_override_reason"] = override_reason
    store.touch(order)
    unit["lifecycle_state"] = "SALVAGED"
    if unit["ownership_treatment"] == "OWNED_INVENTORY":
        unit["accounting_state"] = "EXPENSED"
    store.touch(unit)
    customer_id = access.unit_customer_id(unit)
    services.recompute_customer(store.get("customers", customer_id), diverted=True)
    return object_response(serialize.out(order))
