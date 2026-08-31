"""Cash gifts, restrictions and purchase orders."""
from flask import Blueprint

import calc
import derive
import find
import response as resp
import validators as v
from db import base_record, db, sort_records, touch
from errors import ApiError
from middleware import (ALL_ROLES, DONOR_RELATIONS, PROGRAM_DIRECTOR,
                        WAREHOUSE_LEAD, auth)

bp = Blueprint("cash", __name__)


@bp.post("/cash-donations")
def create_donation():
    auth([DONOR_RELATIONS])
    data = v.body()
    cycle_id = v.req_id(data, "drive_cycle_id")
    donor_name = v.req_str(data, "donor_name")
    amount_cents = v.req_int(data, "amount_cents", minimum=1)
    restriction_type = v.req_enum(data, "restriction_type", v.RESTRICTIONS)
    restricted_item_id = v.opt_id(data, "restricted_supply_item_id")
    restricted_school_id = v.opt_id(data, "restricted_school_id")

    cycle = find.cycle(cycle_id)
    if restricted_item_id is not None:
        find.supply_item(restricted_item_id)
    if restricted_school_id is not None:
        find.school(restricted_school_id)

    if restriction_type == "ITEM_RESTRICTED":
        if restricted_item_id is None or restricted_school_id is not None:
            raise ApiError("ERR_CASH_RESTRICTION_VIOLATION")
    elif restriction_type == "SCHOOL_RESTRICTED":
        if restricted_school_id is None or restricted_item_id is not None:
            raise ApiError("ERR_CASH_RESTRICTION_VIOLATION")
    else:
        if restricted_item_id is not None or restricted_school_id is not None:
            raise ApiError("ERR_CASH_RESTRICTION_VIOLATION")

    rec = base_record()
    rec.update({
        "drive_cycle_id": cycle["id"],
        "donor_name": donor_name,
        "amount_cents": amount_cents,
        "restriction_type": restriction_type,
        "restricted_supply_item_id": restricted_item_id,
        "restricted_school_id": restricted_school_id,
        "allocated_cents": 0,
        "available_cents": amount_cents,
        "status": "RECEIVED",
    })
    db.cash_donations[rec["id"]] = rec

    derive.recompute_cycle_cash(cycle)
    touch(cycle)
    return resp.ok(rec, 201)


@bp.get("/cash-donations/<donation_id>")
def read_donation(donation_id):
    auth(ALL_ROLES)
    return resp.ok(find.donation(donation_id))


@bp.get("/cash-donations")
def list_donations():
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    cycle_id = v.query_id("drive_cycle_id")
    school_id = v.query_id("restricted_school_id")
    item_id = v.query_id("restricted_supply_item_id")
    restriction = v.query_enum("restriction_type", v.RESTRICTIONS)
    rows = list(db.cash_donations.values())
    if cycle_id:
        rows = [r for r in rows if r["drive_cycle_id"] == cycle_id]
    if school_id:
        rows = [r for r in rows if r["restricted_school_id"] == school_id]
    if item_id:
        rows = [r for r in rows if r["restricted_supply_item_id"] == item_id]
    if restriction:
        rows = [r for r in rows if r["restriction_type"] == restriction]
    return resp.listing(sort_records(rows), limit, offset)


# --------------------------------------------------------------------------
# PurchaseOrder
# --------------------------------------------------------------------------
@bp.post("/purchase-orders")
def create_order():
    auth([WAREHOUSE_LEAD])
    data = v.body()
    cycle_id = v.req_id(data, "drive_cycle_id")
    item_id = v.req_id(data, "supply_item_id")
    requested_unit_gap = v.req_int(data, "requested_unit_gap", minimum=1)

    cycle = find.cycle(cycle_id)
    item = find.supply_item(item_id)
    if not item["catalog_active"]:
        raise ApiError("ERR_ITEM_INACTIVE")

    costing = calc.purchase_costing(requested_unit_gap, item["bulk_pack_size"],
                                    item["unit_cost_cents"])
    rec = base_record()
    rec.update({
        "drive_cycle_id": cycle["id"],
        "supply_item_id": item["id"],
        "requested_unit_gap": requested_unit_gap,
        "ordered_qty": costing["ordered_qty"],
        "line_subtotal_cents": costing["line_subtotal_cents"],
        "admin_fee_cents": costing["admin_fee_cents"],
        "total_cost_cents": costing["total_cost_cents"],
        "funding_allocations": [],
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
    })
    db.purchase_orders[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/purchase-orders/<order_id>")
def read_order(order_id):
    auth(ALL_ROLES)
    return resp.ok(find.order(order_id))


@bp.get("/purchase-orders")
def list_orders():
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    cycle_id = v.query_id("drive_cycle_id")
    item_id = v.query_id("supply_item_id")
    status = v.query_enum("status", v.ORDER_STATUSES)
    rows = list(db.purchase_orders.values())
    if cycle_id:
        rows = [r for r in rows if r["drive_cycle_id"] == cycle_id]
    if item_id:
        rows = [r for r in rows if r["supply_item_id"] == item_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return resp.listing(sort_records(rows), limit, offset)


def _waterfall(order, cycle):
    """purchase_funding_waterfall — bucket 1 then bucket 2, oldest gift first."""
    donations = derive.donations_of_cycle(cycle["id"])
    bucket1 = [d for d in donations
               if d["restriction_type"] == "ITEM_RESTRICTED"
               and d["restricted_supply_item_id"] == order["supply_item_id"]
               and d["available_cents"] > 0]
    bucket2 = [d for d in donations
               if d["restriction_type"] == "UNRESTRICTED"
               and d["available_cents"] > 0]
    remaining = order["total_cost_cents"]
    plan = []
    for bucket in (bucket1, bucket2):
        for donation in bucket:
            if remaining == 0:
                break
            take = min(remaining, donation["available_cents"])
            if take <= 0:
                continue
            plan.append((donation, take))
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        return None
    return plan


@bp.post("/purchase-orders/<order_id>/transitions")
def move_order(order_id):
    user_id, role = auth([WAREHOUSE_LEAD, PROGRAM_DIRECTOR])
    data = v.body()
    target = v.target_status(data)
    if target == "APPROVED" and role != PROGRAM_DIRECTOR:
        raise ApiError("ERR_UNAUTHORIZED")
    if target == "RECEIVED" and role != WAREHOUSE_LEAD:
        raise ApiError("ERR_UNAUTHORIZED")
    expected_version = v.req_int(data, "expected_drive_cycle_version")

    order = find.order(order_id)
    cycle = db.drive_cycles.get(order["drive_cycle_id"])
    current = order["status"]

    # 8 — segregation of duties on approval.
    if target == "APPROVED" and order["submitted_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # 9 — from-state legality.
    if target not in v.ORDER_STATUSES:
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if target == "SUBMITTED":
        if current != "DRAFT":
            raise ApiError("ERR_INVALID_ORDER_STATE")
    elif target == "APPROVED":
        if current != "SUBMITTED":
            raise ApiError("ERR_INVALID_ORDER_STATE")
    elif target == "RECEIVED":
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_ORDER_STATE")
    elif target == "CANCELLED":
        if current not in ("DRAFT", "SUBMITTED", "APPROVED"):
            raise ApiError("ERR_INVALID_ORDER_STATE")
    else:
        raise ApiError("ERR_INVALID_ORDER_STATE")

    # 10 — optimistic concurrency on the governing drive cycle.
    if cycle is None or expected_version != cycle["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION")

    item_id = order["supply_item_id"]

    if target == "SUBMITTED":
        # 16 — cycle phase.
        if cycle["status"] not in ("COLLECTING", "SORTING", "DISTRIBUTION"):
            raise ApiError("ERR_CYCLE_PHASE_INVALID")
        # 30 — funding coverage; nothing is written when it fails.
        plan = _waterfall(order, cycle)
        if plan is None:
            raise ApiError("ERR_INSUFFICIENT_FUNDS")
        allocations = []
        for donation, take in plan:
            donation["allocated_cents"] += take
            derive.recompute_donation_status(donation)
            touch(donation)
            allocations.append({"cash_donation_id": donation["id"],
                                "amount_cents": take})
        order["funding_allocations"] = allocations
        order["submitted_by_user_id"] = user_id
        order["status"] = "SUBMITTED"
        derive.recompute_cycle_cash(cycle)
        derive.refresh_in_transit(cycle["id"], item_id)
        derive.refresh_events_for_item(cycle["id"], item_id)
        touch(cycle)
        touch(order)
    elif target == "APPROVED":
        order["status"] = "APPROVED"
        order["approved_by_user_id"] = user_id
        touch(cycle)
        touch(order)
    elif target == "RECEIVED":
        order["status"] = "RECEIVED"
        pos = derive.get_position(cycle["id"], item_id, create=True)
        pos["on_hand_qty"] += order["ordered_qty"]
        pos["purchased_received_qty"] += order["ordered_qty"]
        pos["in_transit_qty"] = derive.compute_in_transit(cycle["id"], item_id)
        touch(pos)
        derive.recompute_cycle_inventory(cycle)
        derive.refresh_events_for_item(cycle["id"], item_id, promote=True)
        derive.recompute_cycle_inventory(cycle)
        touch(cycle)
        touch(order)
    else:  # CANCELLED
        for entry in reversed(order["funding_allocations"]):
            donation = db.cash_donations.get(entry["cash_donation_id"])
            if donation is None:
                continue
            donation["allocated_cents"] -= entry["amount_cents"]
            derive.recompute_donation_status(donation)
            touch(donation)
        order["funding_allocations"] = []
        order["status"] = "CANCELLED"
        derive.recompute_cycle_cash(cycle)
        derive.refresh_in_transit(cycle["id"], item_id)
        derive.refresh_events_for_item(cycle["id"], item_id)
        touch(cycle)
        touch(order)

    return resp.ok(order)
