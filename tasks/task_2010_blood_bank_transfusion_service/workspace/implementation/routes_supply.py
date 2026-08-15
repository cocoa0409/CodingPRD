"""Supply-domain routes: supplier orders (replenishment, receipt) and blood
unit intake/lifecycle actions (PRD 3.2)."""

from flask import Blueprint, request

import errors as E
import logic
from common import (
    endpoint, get_body, req_str, opt_str, req_int, opt_bool, req_enum,
    opt_dt, req_dt, opt_str_list, req_field, as_int,
    supplier_order_by_path, unit_by_path, fk_exists,
)
from constants import ROLES, PRODUCT_TYPES, ABO_TYPES, RH_TYPES, ANTIGENS
from envelope import object_response, list_response
from errors import ApiError
from serializers import ser_supplier_order, ser_unit
from store import DB, new_entity, touch, now
from timeutil import parse_dt

bp = Blueprint("supply", __name__)

ALL = ROLES
COORDINATOR = ["SupplierCoordinator", "BloodBankSupervisor"]


# ---------------------------------------------------------------------------
# Supplier orders (PRD 3.2)
# ---------------------------------------------------------------------------

def _validate_lines(raw):
    if not isinstance(raw, list) or len(raw) == 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field 'lines': must be a non-empty array")
    lines = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Field 'lines[{idx}]': must be an object")
        product_type = req_enum(entry, "product_type", PRODUCT_TYPES)
        abo_type = req_enum(entry, "abo_type", ABO_TYPES)
        rh_type = req_enum(entry, "rh_type", RH_TYPES)
        quantity = req_int(entry, "quantity", min_value=1)
        lines.append({
            "product_type": product_type,
            "abo_type": abo_type,
            "rh_type": rh_type,
            "quantity": quantity,
        })
    return lines


@bp.post("/blood-bank/supplier-orders")
@endpoint(COORDINATOR)
def so_create(user_id, role):
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    lines = _validate_lines(req_field(body, "lines"))
    is_emergency = opt_bool(body, "is_emergency", default=False)
    expected_delivery_at = opt_dt(body, "expected_delivery_at")
    fk_exists(DB.suppliers, supplier_id, "Supplier")
    order = new_entity({
        "supplier_id": supplier_id,
        "is_emergency": is_emergency,
        "lines": lines,
        "expected_delivery_at": expected_delivery_at,
        "status": "DRAFT",
        "estimated_cost_cents": logic.estimate_cost_cents(lines, is_emergency),
        "received_summary": [
            {
                "product_type": line["product_type"],
                "abo_type": line["abo_type"],
                "rh_type": line["rh_type"],
                "received_qty": 0,
            }
            for line in lines
        ],
        "total_units_received": 0,
        "backordered": False,
    })
    DB.supplier_orders[order["id"]] = order
    return object_response(ser_supplier_order(order), status=201)


@bp.get("/blood-bank/supplier-orders")
@endpoint(ALL)
def so_list(user_id, role):
    rows = list(DB.supplier_orders.values())
    supplier_id = request.args.get("supplier_id")
    if supplier_id is not None:
        rows = [o for o in rows if o["supplier_id"] == supplier_id]
    status = request.args.get("status")
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    return list_response(rows, request.args, ser_supplier_order)


@bp.get("/blood-bank/supplier-orders/<oid>")
@endpoint(ALL)
def so_get(oid, user_id, role):
    return object_response(ser_supplier_order(supplier_order_by_path(oid)))


@bp.post("/blood-bank/supplier-orders/<oid>/submit")
@endpoint(COORDINATOR)
def so_submit(oid, user_id, role):
    order = supplier_order_by_path(oid)
    if order["status"] != "DRAFT":
        raise ApiError(E.ERR_SO_NOT_SUBMITTABLE, 409, "submit requires DRAFT")
    supplier = DB.suppliers.get(order["supplier_id"])
    if supplier is None or supplier["status"] != "ACTIVE":
        raise ApiError(E.ERR_SUPPLIER_SUSPENDED, 409, "Supplier must be ACTIVE to submit")
    # Wastage review gate: SupplierCoordinator only (Supervisor exempt),
    # non-emergency orders, any line's bucket at rate >= 0.05.
    if role == "SupplierCoordinator" and not order["is_emergency"]:
        for line in order["lines"]:
            if logic.bucket_excessive_wastage(line["product_type"], line["abo_type"], line["rh_type"]):
                raise ApiError(
                    E.ERR_WASTAGE_REVIEW_REQUIRED, 409,
                    "A line's bucket carries a rolling wastage rate >= 0.05; supervisor review required",
                )
    order["status"] = "ACKNOWLEDGED" if order["is_emergency"] else "SUBMITTED"
    touch(order)
    return object_response(ser_supplier_order(order))


@bp.post("/blood-bank/supplier-orders/<oid>/acknowledge")
@endpoint(COORDINATOR)
def so_acknowledge(oid, user_id, role):
    order = supplier_order_by_path(oid)
    if order["status"] != "SUBMITTED":
        raise ApiError(E.ERR_SO_NOT_ACKNOWLEDGEABLE, 409, "acknowledge requires SUBMITTED")
    order["status"] = "ACKNOWLEDGED"
    touch(order)
    return object_response(ser_supplier_order(order))


def _validate_unit_descriptor(entry, idx):
    if not isinstance(entry, dict):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Field 'units[{idx}]': must be an object")
    return {
        "unit_number": req_str(entry, "unit_number"),
        "donor_id": req_str(entry, "donor_id"),
        "lot_number": req_str(entry, "lot_number"),
        "product_type": req_enum(entry, "product_type", PRODUCT_TYPES),
        "abo_type": req_enum(entry, "abo_type", ABO_TYPES),
        "rh_type": req_enum(entry, "rh_type", RH_TYPES),
        "volume_ml": req_int(entry, "volume_ml", min_value=1),
        "collected_at": req_dt(entry, "collected_at"),
        "thawed_at": opt_dt(entry, "thawed_at"),
        "pooled_at": opt_dt(entry, "pooled_at"),
        "antigen_negative": opt_str_list(entry, "antigen_negative", allowed=ANTIGENS),
        "irradiated": opt_bool(entry, "irradiated", default=False),
        "cmv_negative": opt_bool(entry, "cmv_negative", default=False),
        "washed": opt_bool(entry, "washed", default=False),
        "derived_from_unit_id": opt_str(entry, "derived_from_unit_id"),
    }


@bp.post("/blood-bank/supplier-orders/<oid>/receive")
@endpoint(COORDINATOR)
def so_receive(oid, user_id, role):
    order = supplier_order_by_path(oid)
    body = get_body()
    raw_units = req_field(body, "units")
    if not isinstance(raw_units, list) or len(raw_units) == 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field 'units': must be a non-empty array")
    descriptors = [_validate_unit_descriptor(entry, idx) for idx, entry in enumerate(raw_units)]

    if order["status"] not in ("ACKNOWLEDGED", "RECEIVING"):
        raise ApiError(E.ERR_SO_NOT_RECEIVABLE, 409, "receive requires ACKNOWLEDGED or RECEIVING")

    # No collected/thawed/pooled timestamp may lie in the future (priority 13).
    current = now()
    for d in descriptors:
        for field in ("collected_at", "thawed_at", "pooled_at"):
            if d[field] is not None and d[field] > current:
                raise ApiError(
                    E.ERR_SPECIMEN_TIME_INVALID, 400,
                    f"{field} must not be in the future",
                )

    # Line matching and cumulative over-receipt (priority 24). Atomic: the
    # whole batch is validated before any unit is created.
    ordered_qty = {}
    for line in order["lines"]:
        key = (line["product_type"], line["abo_type"], line["rh_type"])
        ordered_qty[key] = ordered_qty.get(key, 0) + line["quantity"]
    received_qty = {}
    for entry in order["received_summary"]:
        key = (entry["product_type"], entry["abo_type"], entry["rh_type"])
        received_qty[key] = received_qty.get(key, 0) + entry["received_qty"]
    batch_qty = {}
    for d in descriptors:
        key = (d["product_type"], d["abo_type"], d["rh_type"])
        if key not in ordered_qty:
            raise ApiError(
                E.ERR_OVER_RECEIPT, 422,
                f"Received unit matches no line on the order: {key[0]}:{key[1]}:{key[2]}",
            )
        batch_qty[key] = batch_qty.get(key, 0) + 1
    for key, count in batch_qty.items():
        if received_qty.get(key, 0) + count > ordered_qty[key]:
            raise ApiError(
                E.ERR_OVER_RECEIPT, 422,
                f"Cumulative receipt for line {key[0]}:{key[1]}:{key[2]} exceeds ordered quantity",
            )

    # unit_number global uniqueness, including within the batch (priority 25).
    seen = set()
    for d in descriptors:
        if d["unit_number"] in seen:
            raise ApiError(E.ERR_DUPLICATE_UNIT_NUMBER, 409, f"unit_number {d['unit_number']} is duplicated in this manifest")
        seen.add(d["unit_number"])
        if any(u["unit_number"] == d["unit_number"] for u in DB.units.values()):
            raise ApiError(E.ERR_DUPLICATE_UNIT_NUMBER, 409, f"unit_number {d['unit_number']} already exists")

    # Commit: one QUARANTINED BloodUnit per descriptor.
    for d in descriptors:
        unit = new_entity({
            "unit_number": d["unit_number"],
            "supplier_order_id": order["id"],
            "supplier_id": order["supplier_id"],
            "donor_id": d["donor_id"],
            "lot_number": d["lot_number"],
            "product_type": d["product_type"],
            "abo_type": d["abo_type"],
            "rh_type": d["rh_type"],
            "volume_ml": d["volume_ml"],
            "collected_at": d["collected_at"],
            "thawed_at": d["thawed_at"],
            "pooled_at": d["pooled_at"],
            "expires_at": logic.unit_expiration(
                d["product_type"], d["collected_at"], d["thawed_at"], d["pooled_at"]
            ),
            "antigen_negative": d["antigen_negative"],
            "irradiated": d["irradiated"],
            "cmv_negative": d["cmv_negative"],
            "washed": d["washed"],
            "derived_from_unit_id": d["derived_from_unit_id"],
            "status": "QUARANTINED",
            "hold_origin_state": None,
            "hold_reason": None,
            "intake_reject_reason": None,
        })
        DB.units[unit["id"]] = unit

    # received_summary / total_units_received; first receipt -> RECEIVING;
    # auto-close when every line stands fully received.
    remaining = dict(batch_qty)
    for idx, line in enumerate(order["lines"]):
        key = (line["product_type"], line["abo_type"], line["rh_type"])
        if remaining.get(key):
            entry = order["received_summary"][idx]
            room = line["quantity"] - entry["received_qty"]
            applied = min(room, remaining[key])
            entry["received_qty"] += applied
            remaining[key] -= applied
    order["total_units_received"] += len(descriptors)
    if order["status"] == "ACKNOWLEDGED":
        order["status"] = "RECEIVING"
    if all(
        order["received_summary"][idx]["received_qty"] == line["quantity"]
        for idx, line in enumerate(order["lines"])
    ):
        order["status"] = "CLOSED"
    touch(order)
    return object_response(ser_supplier_order(order))


@bp.post("/blood-bank/supplier-orders/<oid>/close")
@endpoint(COORDINATOR)
def so_close(oid, user_id, role):
    order = supplier_order_by_path(oid)
    if order["status"] != "RECEIVING":
        raise ApiError(E.ERR_SO_NOT_CLOSABLE, 409, "manual close requires RECEIVING")
    order["status"] = "CLOSED"
    order["backordered"] = any(
        order["received_summary"][idx]["received_qty"] < line["quantity"]
        for idx, line in enumerate(order["lines"])
    )
    touch(order)
    return object_response(ser_supplier_order(order))


@bp.post("/blood-bank/supplier-orders/<oid>/cancel")
@endpoint(COORDINATOR)
def so_cancel(oid, user_id, role):
    order = supplier_order_by_path(oid)
    if order["status"] not in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED"):
        raise ApiError(E.ERR_SO_NOT_CANCELLABLE, 409, "cancel requires DRAFT, SUBMITTED or ACKNOWLEDGED")
    order["status"] = "CANCELLED"
    touch(order)
    return object_response(ser_supplier_order(order))


# ---------------------------------------------------------------------------
# Blood units (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.get("/blood-bank/blood-units")
@endpoint(ALL)
def unit_list(user_id, role):
    rows = list(DB.units.values())
    for param, field in (
        ("status", "status"), ("product_type", "product_type"), ("abo_type", "abo_type"),
        ("rh_type", "rh_type"), ("supplier_id", "supplier_id"),
        ("supplier_order_id", "supplier_order_id"), ("donor_id", "donor_id"),
        ("lot_number", "lot_number"), ("derived_from_unit_id", "derived_from_unit_id"),
        ("unit_number", "unit_number"),
    ):
        value = request.args.get(param)
        if value is not None:
            rows = [u for u in rows if u[field] == value]
    expires_before = request.args.get("expires_before")
    if expires_before is not None:
        cutoff = parse_dt(expires_before)
        if cutoff is None:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Query parameter 'expires_before' must be an ISO-8601 timestamp")
        rows = [u for u in rows if u["expires_at"] < cutoff]
    return list_response(rows, request.args, ser_unit)


@bp.get("/blood-bank/blood-units/<uid>")
@endpoint(ALL)
def unit_get(uid, user_id, role):
    return object_response(ser_unit(unit_by_path(uid)))


@bp.post("/blood-bank/blood-units/<uid>/release-from-quarantine")
@endpoint(["BloodBankTechnologist"])
def unit_release(uid, user_id, role):
    unit = unit_by_path(uid)
    if unit["status"] != "QUARANTINED":
        raise ApiError(E.ERR_UNIT_NOT_RELEASABLE, 409, "release-from-quarantine requires status QUARANTINED")
    supplier = DB.suppliers.get(unit["supplier_id"])
    if supplier is None or supplier["status"] != "ACTIVE":
        raise ApiError(E.ERR_SUPPLIER_SUSPENDED, 409, "Supplier must be ACTIVE to release units")
    unit["status"] = "AVAILABLE"
    touch(unit)
    return object_response(ser_unit(unit))


@bp.post("/blood-bank/blood-units/<uid>/reject-intake")
@endpoint(["BloodBankTechnologist"])
def unit_reject(uid, user_id, role):
    unit = unit_by_path(uid)
    body = get_body()
    reason = req_str(body, "reason")
    if unit["status"] != "QUARANTINED":
        raise ApiError(E.ERR_UNIT_NOT_REJECTABLE, 409, "reject-intake requires status QUARANTINED")
    unit["status"] = "REJECTED"
    unit["intake_reject_reason"] = reason
    touch(unit)
    return object_response(ser_unit(unit))


@bp.post("/blood-bank/blood-units/<uid>/discard")
@endpoint(["BloodBankSupervisor"])
def unit_discard(uid, user_id, role):
    unit = unit_by_path(uid)
    body = get_body()
    note = opt_str(body, "note", default=None, allow_empty=True)
    if unit["status"] not in ("AVAILABLE", "QUARANTINED", "QUARANTINED_HOLD"):
        raise ApiError(E.ERR_UNIT_NOT_DISCARDABLE, 409, "discard requires AVAILABLE, QUARANTINED or QUARANTINED_HOLD")
    unit["status"] = "DISCARDED"
    unit["hold_origin_state"] = None
    unit["hold_reason"] = None
    touch(unit)
    logic.add_wastage(unit, "MANUAL", user_id, note=note)
    return object_response(ser_unit(unit))
