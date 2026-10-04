"""Suppliers and supplier capacity commitments (PRD 3.3)."""
from flask import Blueprint, g

import calc
import svc
from core import (
    ALL_ROLES,
    ApiError,
    body,
    db,
    endpoint,
    f_int,
    f_month,
    f_str,
    logical_month,
    month_add,
    new_row,
    paginate,
    parse_month,
    q_enum,
    q_str,
    raw_int,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("suppliers", __name__, url_prefix="/api")

COMMITMENT_STATUSES = ("DRAFT", "CONFIRMED", "ORDERED", "AT_RISK", "CANCELLED")


def _own_commitment(commitment):
    """Entity-backed ownership: the acting SupplierManager's X-User-ID must equal
    the commitment's supplier_id (PRD 2.1)."""
    if g.user_id != commitment["supplier_id"]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
@bp.post("/suppliers")
@endpoint("ProgramAdmin")
def create_supplier():
    payload = body()
    candidate = payload.get("supplier_code")
    if isinstance(candidate, str) and any(
        s["supplier_code"] == candidate for s in db.suppliers.values()
    ):
        raise ApiError("ERR_DUPLICATE_CODE")
    supplier_code = f_str(payload, "supplier_code")
    name = f_str(payload, "name")
    region = f_str(payload, "region")
    supplier = new_row(
        "Supplier", supplier_code=supplier_code, name=name, region=region
    )
    db.suppliers[supplier["id"]] = supplier
    return respond_object(svc.dump_supplier(supplier), 201)


@bp.get("/suppliers/<supplier_id>")
@endpoint(*ALL_ROLES)
def get_supplier(supplier_id):
    return respond_object(svc.dump_supplier(svc.need_supplier(supplier_id)))


# ---------------------------------------------------------------------------
# Capacity commitments
# ---------------------------------------------------------------------------
@bp.post("/suppliers/<supplier_id>/capacity-commitments")
@endpoint("SupplierManager")
def create_commitment(supplier_id):
    supplier = svc.need_supplier(supplier_id)
    if g.user_id != supplier["id"]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    payload = body()
    # Body-referenced FK existence: program_id must resolve.
    referenced = payload.get("program_id")
    if isinstance(referenced, str):
        svc.need_program(referenced)
    program_id = f_str(payload, "program_id")
    component_code = f_str(payload, "component_code")
    committed_rate_per_month = f_int(payload, "committed_rate_per_month", minimum=1)
    lead_time_months = f_int(payload, "lead_time_months", minimum=1)
    unit_price_cents = f_int(payload, "unit_price_cents", minimum=1)
    commitment = new_row(
        "SupplierCapacityCommitment",
        supplier_id=supplier["id"],
        program_id=program_id,
        component_code=component_code,
        committed_rate_per_month=committed_rate_per_month,
        lead_time_months=lead_time_months,
        unit_price_cents=unit_price_cents,
        ordered_quantity=0,
        cancelled_quantity=0,
        assumed_rate_at_order=None,
        cancellation_penalty_cents=0,
        status="DRAFT",
    )
    db.commitments[commitment["id"]] = commitment
    return respond_object(svc.dump_commitment(commitment), 201)


@bp.get("/suppliers/<supplier_id>/capacity-commitments")
@endpoint("ProgramAdmin", "ProductionPlanner", "SupplierManager")
def list_supplier_commitments(supplier_id):
    svc.need_supplier(supplier_id)
    status = q_enum("status", COMMITMENT_STATUSES)
    rows = [c for c in db.commitments.values() if c["supplier_id"] == supplier_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return paginate(sort_created(rows), svc.dump_commitment)


@bp.get("/programs/<program_id>/capacity-commitments")
@endpoint("ProgramAdmin", "ProductionPlanner", "SupplierManager")
def list_program_commitments(program_id):
    svc.need_program(program_id)
    status = q_enum("status", COMMITMENT_STATUSES)
    component_code = q_str("component_code")
    rows = [c for c in db.commitments.values() if c["program_id"] == program_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if component_code is not None:
        rows = [c for c in rows if c["component_code"] == component_code]
    return paginate(sort_created(rows), svc.dump_commitment)


@bp.post("/capacity-commitments/<commitment_id>/confirm")
@endpoint("SupplierManager")
def confirm_commitment(commitment_id):
    commitment = svc.need_commitment(commitment_id)
    _own_commitment(commitment)
    if commitment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_TRANSITION")
    commitment["status"] = "CONFIRMED"
    touch(commitment)
    return respond_object(svc.dump_commitment(commitment))


@bp.post("/capacity-commitments/<commitment_id>/place-order")
@endpoint("SupplierManager")
def place_order(commitment_id):
    commitment = svc.need_commitment(commitment_id)
    _own_commitment(commitment)
    payload = body()
    # rung 5 -- state gate
    if commitment["status"] not in ("CONFIRMED", "ORDERED", "AT_RISK"):
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 7 -- required_by_month at least lead_time_months beyond the logical month
    required_by = parse_month(payload.get("required_by_month"))
    if required_by is not None and required_by < month_add(
        logical_month(), commitment["lead_time_months"]
    ):
        raise ApiError("ERR_LEAD_TIME_VIOLATION")
    # rung 9 -- quantity within 1..committed_rate_per_month * lead_time_months
    quantity_raw = payload.get("quantity")
    if raw_int(quantity_raw):
        ceiling = commitment["committed_rate_per_month"] * commitment["lead_time_months"]
        if quantity_raw < 1 or quantity_raw > ceiling:
            raise ApiError("ERR_ORDER_EXCEEDS_COMMITMENT")
    # rung 10 -- body shape
    quantity = f_int(payload, "quantity")
    assumed_rate_per_month = f_int(payload, "assumed_rate_per_month", minimum=1)
    f_month(payload, "required_by_month")
    commitment["ordered_quantity"] += quantity
    commitment["assumed_rate_at_order"] = assumed_rate_per_month
    commitment["status"] = "ORDERED"
    touch(commitment)
    return respond_object(svc.dump_commitment(commitment))


@bp.post("/capacity-commitments/<commitment_id>/cancel")
@endpoint("SupplierManager")
def cancel_commitment(commitment_id):
    commitment = svc.need_commitment(commitment_id)
    _own_commitment(commitment)
    payload = body()
    # rung 5 -- state gate (CANCELLED is terminal)
    if commitment["status"] not in ("CONFIRMED", "ORDERED", "AT_RISK"):
        raise ApiError("ERR_INVALID_TRANSITION")
    active = commitment["ordered_quantity"] - commitment["cancelled_quantity"]
    # rung 9 -- all-or-nothing: a provided cancel_quantity must equal the active set
    cancel_raw = payload.get("cancel_quantity")
    if raw_int(cancel_raw) and cancel_raw != active:
        raise ApiError("ERR_CANCEL_QUANTITY_INVALID")
    # rung 10 -- body shape
    cancel_quantity = f_int(payload, "cancel_quantity", required=False)
    quantity = cancel_quantity if cancel_quantity is not None else active
    commitment["cancelled_quantity"] += quantity
    commitment["cancellation_penalty_cents"] = calc.cancellation_penalty(
        quantity, commitment["unit_price_cents"]
    )
    commitment["status"] = "CANCELLED"
    touch(commitment)
    # program.cancellation_reserve_cents recomputes live over the mutated set.
    return respond_object(svc.dump_commitment(commitment))
