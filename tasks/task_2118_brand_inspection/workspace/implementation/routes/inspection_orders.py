"""Inspection orders: two independent state dimensions on one row."""

from flask import Blueprint, request

from db import base_row, by_created_at, db, insert, now, touch
from errors import ApiError
from middleware import caller_id, caller_role, endpoint, require_assigned_inspector, require_owner
from response import object_response, paginate
from routes import lookup
from services import aggregates, cascades, constants as C
from services.calculations import (
    fee_due_on,
    inspection_fee_assessment,
    occupied_orders,
    same_day_count,
    window_conflict,
)
from validation import (
    INSPECTION_PURPOSES,
    SPECIES_CLASSES,
    body,
    opt_id,
    opt_str,
    req_dt,
    req_enum,
    req_id,
    req_int,
)

bp = Blueprint("inspection_orders", __name__)

READ_ROLES = ("LivestockOwner", "FieldInspector", "BoardAdmin", "FeeAdministrator")


@bp.post("/inspection-orders")
@endpoint("LivestockOwner")
def request_inspection():
    payload = body()
    owner_id = req_id(payload, "owner_id")
    territory_id = req_id(payload, "territory_id")
    inspection_purpose = req_enum(payload, "inspection_purpose", INSPECTION_PURPOSES)
    window_start = req_dt(payload, "requested_window_start_at")
    window_end = req_dt(payload, "requested_window_end_at")
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "requested_window_end_at must be strictly later than the start."
        )

    lookup.owner(owner_id)
    lookup.territory(territory_id)
    require_owner(owner_id)

    row = base_row()
    row.update(
        {
            "owner_id": owner_id,
            "territory_id": territory_id,
            "inspector_id": None,
            "remittance_id": None,
            "inspection_purpose": inspection_purpose,
            "requested_window_start_at": window_start,
            "requested_window_end_at": window_end,
            "scheduled_start_at": None,
            "scheduled_end_at": None,
            "schedule_status": "REQUESTED",
            "fee_status": "UNASSESSED",
            "assessed_fee_cents": 0,
            "fee_due_on": None,
            "hold_flag": False,
            "head_count_presented": 0,
        }
    )
    insert(db.orders, row)
    return object_response(row, 201)


@bp.get("/inspection-orders/<order_id>")
@endpoint(*READ_ROLES)
def read_order(order_id):
    return object_response(lookup.order(order_id))


@bp.get("/inspection-orders")
@endpoint(*READ_ROLES)
def list_orders():
    rows = lookup.filtered(
        db.orders,
        {
            "owner_id": request.args.get("owner_id"),
            "territory_id": request.args.get("territory_id"),
            "inspector_id": request.args.get("inspector_id"),
            "remittance_id": request.args.get("remittance_id"),
            "schedule_status": request.args.get("schedule_status"),
            "fee_status": request.args.get("fee_status"),
        },
    )
    return paginate(by_created_at(rows))


@bp.post("/inspection-orders/<order_id>/schedule")
@endpoint("BoardAdmin")
def schedule_order(order_id):
    payload = body()
    inspector_id = req_id(payload, "inspector_id")
    scheduled_start_at = req_dt(payload, "scheduled_start_at")
    scheduled_end_at = req_dt(payload, "scheduled_end_at")
    expected_inspector_version = req_int(payload, "expected_inspector_version")
    if scheduled_end_at <= scheduled_start_at:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_end_at must be strictly later than the start.")

    order = lookup.order(order_id)

    if (
        scheduled_start_at < order["requested_window_start_at"]
        or scheduled_end_at > order["requested_window_end_at"]
    ):
        raise ApiError("ERR_INVALID_REQUEST", "The assigned window must sit inside the requested window.")

    inspector = lookup.inspector(inspector_id)

    if order["schedule_status"] != "REQUESTED":
        raise ApiError("ERR_ORDER_NOT_SCHEDULABLE", "The order is no longer schedulable.")

    if expected_inspector_version != inspector["version"]:
        raise ApiError("ERR_STALE_INSPECTOR_VERSION", "The inspector version has advanced.")

    if inspector["status"] != "ACTIVE" or inspector["certification_expires_on"] <= scheduled_end_at:
        raise ApiError("ERR_INSPECTOR_UNAVAILABLE", "The commission is not available for this window.")

    occupied = occupied_orders(inspector["id"], order["id"])
    if window_conflict(occupied, order["territory_id"], scheduled_start_at, scheduled_end_at):
        raise ApiError("ERR_INSPECTOR_WINDOW_CONFLICT", "The proposed window collides with held work.")

    if same_day_count(occupied, scheduled_start_at) >= inspector["max_daily_assignments"]:
        raise ApiError("ERR_INSPECTOR_DAILY_LIMIT", "The inspector is at the daily assignment ceiling.")

    home_territory = db.territories.get(inspector["home_territory_id"])
    order_territory = db.territories.get(order["territory_id"])
    if (
        home_territory is None
        or order_territory is None
        or home_territory["state_code"] != order_territory["state_code"]
    ):
        raise ApiError("ERR_TERRITORY_MISMATCH", "The inspector is commissioned in another state.")

    owner = db.owners.get(order["owner_id"])
    if owner is not None and owner["standing"] == "SUSPENDED":
        raise ApiError("ERR_OWNER_STANDING_SUSPENDED", "The order owner is in arrears.")

    order["schedule_status"] = "SCHEDULED"
    order["inspector_id"] = inspector["id"]
    order["scheduled_start_at"] = scheduled_start_at
    order["scheduled_end_at"] = scheduled_end_at
    touch(order)
    aggregates.recompute_inspector_assignments(inspector, bump=True)
    return object_response(order)


@bp.post("/inspection-orders/<order_id>/begin")
@endpoint("FieldInspector")
def begin_order(order_id):
    order = lookup.order(order_id)
    require_assigned_inspector(order)
    if order["schedule_status"] != "SCHEDULED":
        raise ApiError("ERR_ORDER_INVALID_STATE", "The order is not awaiting field work.")
    inspector = db.inspectors.get(order["inspector_id"])
    if inspector is None or inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_UNAVAILABLE", "The commission is not ACTIVE.")
    order["schedule_status"] = "IN_FIELD"
    touch(order)
    return object_response(order)


@bp.post("/inspection-orders/<order_id>/lots")
@endpoint("FieldInspector")
def record_lot(order_id):
    payload = body()
    species_class = req_enum(payload, "species_class", SPECIES_CLASSES)
    head_count = req_int(payload, "head_count", minimum=1)
    brand_registration_id = opt_id(payload, "brand_registration_id")
    bill_of_sale_id = opt_id(payload, "bill_of_sale_id")
    earmark_code = opt_str(payload, "earmark_code")

    order = lookup.order(order_id)
    if brand_registration_id is not None:
        lookup.registration(brand_registration_id)
    if bill_of_sale_id is not None:
        lookup.bill_of_sale(bill_of_sale_id)

    require_assigned_inspector(order)

    if order["schedule_status"] != "IN_FIELD":
        raise ApiError("ERR_ORDER_INVALID_STATE", "Lots may only be recorded while the order is IN_FIELD.")

    row = base_row()
    row.update(
        {
            "inspection_order_id": order["id"],
            "brand_registration_id": brand_registration_id,
            "bill_of_sale_id": bill_of_sale_id,
            "species_class": species_class,
            "head_count": head_count,
            "earmark_code": earmark_code,
            "lot_status": "PRESENTED",
            "match_status": "UNCHECKED",
            "disposition": "NONE",
        }
    )
    insert(db.lots, row)

    if aggregates.recompute_head_count_presented(order):
        touch(order)
    return object_response(row, 201)


@bp.post("/inspection-orders/<order_id>/complete")
@endpoint("FieldInspector")
def complete_order(order_id):
    order = lookup.order(order_id)
    require_assigned_inspector(order)

    if order["schedule_status"] != "IN_FIELD":
        raise ApiError("ERR_ORDER_INVALID_STATE", "The order is not in the field.")

    for lot in db.lots.values():
        if lot["inspection_order_id"] != order["id"]:
            continue
        if lot["lot_status"] != "VOIDED" and lot["match_status"] == "UNCHECKED":
            raise ApiError("ERR_ORDER_INVALID_STATE", "A presented lot still carries no finding.")

    order["schedule_status"] = "COMPLETED"
    aggregates.recompute_head_count_presented(order)
    if order["fee_status"] == "UNASSESSED":
        order["assessed_fee_cents"] = inspection_fee_assessment(order)
        order["fee_due_on"] = fee_due_on()
        order["fee_status"] = "ASSESSED"
    touch(order)
    inspector = db.inspectors.get(order["inspector_id"])
    if inspector is not None:
        aggregates.recompute_inspector_assignments(inspector)
    aggregates.recompute_owner_by_id(order["owner_id"])
    return object_response(order)


@bp.post("/inspection-orders/<order_id>/cancel")
@endpoint("LivestockOwner", "BoardAdmin")
def cancel_order(order_id):
    order = lookup.order(order_id)
    if caller_role() == "LivestockOwner":
        require_owner(order["owner_id"])

    if order["schedule_status"] not in ("REQUESTED", "SCHEDULED"):
        raise ApiError("ERR_ORDER_INVALID_STATE", "The order can no longer be withdrawn.")

    was_scheduled = order["schedule_status"] == "SCHEDULED"
    inspector = db.inspectors.get(order["inspector_id"]) if was_scheduled else None

    order["schedule_status"] = "CANCELLED"
    if was_scheduled:
        order["inspector_id"] = None
        order["scheduled_start_at"] = None
        order["scheduled_end_at"] = None

    for lot in by_created_at([l for l in db.lots.values() if l["inspection_order_id"] == order["id"]]):
        if lot["lot_status"] != "VOIDED":
            lot["lot_status"] = "VOIDED"
            touch(lot)

    aggregates.recompute_head_count_presented(order)
    touch(order)

    if inspector is not None:
        aggregates.recompute_inspector_assignments(inspector, bump=True)
    return object_response(order)


def _fee_operation_guards(order):
    if order["fee_status"] not in C.OPEN_FEE_STATUSES:
        raise ApiError("ERR_FEE_INVALID_STATE", "The fee dimension does not permit this operation.")
    if order["hold_flag"]:
        raise ApiError("ERR_ORDER_HOLD_ACTIVE", "A theft hold is active on this order.")


@bp.post("/inspection-orders/<order_id>/waive-fee")
@endpoint("FeeAdministrator")
def waive_fee(order_id):
    order = lookup.order(order_id)
    _fee_operation_guards(order)
    order["fee_status"] = "WAIVED"
    touch(order)
    aggregates.recompute_owner_by_id(order["owner_id"])
    return object_response(order)


@bp.post("/inspection-orders/<order_id>/void-assessment")
@endpoint("FeeAdministrator")
def void_assessment(order_id):
    order = lookup.order(order_id)
    _fee_operation_guards(order)
    order["fee_status"] = "UNASSESSED"
    order["assessed_fee_cents"] = 0
    order["fee_due_on"] = None
    touch(order)
    aggregates.recompute_owner_by_id(order["owner_id"])
    return object_response(order)
