"""Brewer maintenance, descale discipline and loaner circulation (PRD 3.6).

Two independent dimensions live on one row: `wo_status` (the service dimension,
cyclic between IN_PROGRESS and AWAITING_PARTS) and `loaner_status` (the substitute
brewer). Neither constrains the other except at resolution, where an outstanding
loaner blocks sign-off.
"""
from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                   ROLE_ROUTE_TECHNICIAN, authenticate, require_route_owner)
from envelope import created, ok
from errors import ApiError
from store import bump, db, insert, now
from timeutil import UTC

bp = Blueprint("workorders", __name__)

WO_TYPES = ("PREVENTIVE", "DESCALE", "REPAIR")
WO_STATUSES = ("OPEN", "IN_PROGRESS", "AWAITING_PARTS", "RESOLVED")
DECLARED_TRANSITIONS = (
    ("OPEN", "IN_PROGRESS"),
    ("IN_PROGRESS", "AWAITING_PARTS"),
    ("AWAITING_PARTS", "IN_PROGRESS"),
    ("IN_PROGRESS", "RESOLVED"),
)
AWAITING_PARTS_CAP = 3
SETTLED_LOANER_STATUSES = ("NONE", "RETURNED", "WRITTEN_OFF")
SWAPPABLE_WO_STATUSES = ("OPEN", "IN_PROGRESS", "AWAITING_PARTS")
RETURNABLE_LOANER_STATUSES = ("OUT", "OVERDUE")


def _route_of_work_order(work_order):
    site = db.sites.get(work_order["site_id"])
    return site["route_id"] if site is not None else None


READ_ROLES = (ROLE_ROUTE_TECHNICIAN, ROLE_PROGRAM_ADMIN, ROLE_ACCOUNT_MANAGER,
              ROLE_BILLING_SPECIALIST)


@bp.post("/ocs/maintenance-work-orders")
def create_work_order():
    actor = authenticate((ROLE_ROUTE_TECHNICIAN, ROLE_PROGRAM_ADMIN))
    fields = shape.fields()
    asset_id = fields.string("asset_id", min_len=1)
    wo_type = fields.enum("wo_type", WO_TYPES)

    asset = lookup.equipment_asset(asset_id)
    # site_id is copied from the site of the asset's ACTIVE placement, never supplied.
    placement = calc.active_placement_of_asset(asset["id"])
    if placement is None:
        raise ApiError("ERR_ASSET_NOT_AVAILABLE",
                       "The asset has no active placement to open a work order against.")
    site = db.sites.get(placement["site_id"])
    require_route_owner(actor, site["route_id"] if site is not None else None)

    row = insert(db.work_orders, {
        "asset_id": asset["id"],
        "site_id": placement["site_id"],
        "wo_type": wo_type,
        "wo_status": "OPEN",
        "parts_eta": None,
        "awaiting_parts_cycles": 0,
        "resolution_note": None,
        "loaner_asset_id": None,
        "loaner_out_date": None,
        "loaner_due_back_date": None,
        "loaner_returned_on": None,
        "loaner_status": "NONE",
    })
    return created(serializers.work_order(row))


@bp.get("/ocs/maintenance-work-orders")
def list_work_orders():
    authenticate(READ_ROLES)
    rows = lookup.eq_filter(list(db.work_orders.values()), "asset_id")
    rows = lookup.eq_filter(rows, "site_id")
    rows = lookup.eq_filter(rows, "loaner_asset_id")
    rows = lookup.eq_filter(rows, "wo_status")
    rows = lookup.eq_filter(rows, "loaner_status")
    rows = lookup.eq_filter(rows, "wo_type")
    return lookup.listing(rows, serializers.work_order)


@bp.get("/ocs/maintenance-work-orders/<work_order_id>")
def read_work_order(work_order_id):
    authenticate(READ_ROLES)
    return ok(serializers.work_order(lookup.work_order(work_order_id)))


@bp.post("/ocs/maintenance-work-orders/<work_order_id>/advance")
def advance_work_order(work_order_id):
    actor = authenticate((ROLE_ROUTE_TECHNICIAN,))
    fields = shape.fields()
    to_status = fields.enum("to_status", WO_STATUSES)
    parts_eta = fields.instant("parts_eta", required=False)
    resolution_note = fields.string("resolution_note", required=False, min_len=1)

    work_order = lookup.work_order(work_order_id)
    require_route_owner(actor, _route_of_work_order(work_order))

    # Rung 16: only four transitions are declared, and nothing leaves RESOLVED.
    if (work_order["wo_status"], to_status) not in DECLARED_TRANSITIONS:
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID",
                       "Transition %s -> %s is not declared."
                       % (work_order["wo_status"], to_status))

    asset = db.equipment_assets.get(work_order["asset_id"])
    if to_status == "RESOLVED":
        # Rung 17: the loaner dimension must be settled before the service dimension
        # may close.
        if work_order["loaner_status"] not in SETTLED_LOANER_STATUSES:
            raise ApiError("ERR_LOANER_STATE_INVALID",
                           "A substitute brewer is still out on this work order.")
        # Rung 22: only a PREVENTIVE order carries the descale gate.
        if work_order["wo_type"] == "PREVENTIVE" and asset is not None \
                and calc.descale_past_interval(asset):
            raise ApiError("ERR_DESCALE_OVERDUE",
                           "The brewer is past its descale interval; resolve a DESCALE "
                           "work order first.")
    if to_status == "AWAITING_PARTS":
        # Rung 39: at most three entries into AWAITING_PARTS.
        if work_order["awaiting_parts_cycles"] >= AWAITING_PARTS_CAP:
            raise ApiError("ERR_AWAITING_PARTS_LIMIT_REACHED",
                           "This work order has already waited for parts %d times."
                           % AWAITING_PARTS_CAP)

    # Rung 51: the conditionally-required fields are checked last of all.
    if to_status == "AWAITING_PARTS" and parts_eta is None:
        raise ApiError("ERR_MISSING_TRANSITION_FIELD",
                       "parts_eta is required to enter AWAITING_PARTS.")
    if to_status == "RESOLVED" and resolution_note is None:
        raise ApiError("ERR_MISSING_TRANSITION_FIELD",
                       "resolution_note is required to resolve a work order.")

    work_order["wo_status"] = to_status
    if to_status == "AWAITING_PARTS":
        # Recorded afresh on each entry, so it always reflects the current wait.
        work_order["parts_eta"] = parts_eta
        work_order["awaiting_parts_cycles"] += 1
    if to_status == "RESOLVED":
        work_order["resolution_note"] = resolution_note
        if work_order["wo_type"] == "DESCALE" and asset is not None:
            # The only way the descale clock is ever reset.
            asset["last_descale_at"] = now()
            bump(asset)
    bump(work_order)

    if to_status == "RESOLVED":
        # Clearing an overdue descale removes 15.0 points, which can walk the site
        # back to ACTIVE and the account out of AT_RISK.
        site = db.sites.get(work_order["site_id"])
        if site is not None:
            cascade.apply_site_posture(site)
    return ok(serializers.work_order(work_order))


@bp.post("/ocs/maintenance-work-orders/<work_order_id>/loaner-swap")
def loaner_swap(work_order_id):
    actor = authenticate((ROLE_ROUTE_TECHNICIAN,))
    fields = shape.fields()
    loaner_asset_id = fields.string("loaner_asset_id", min_len=1)
    loaner_out = fields.instant("loaner_out_date")
    loaner_due_back = fields.instant("loaner_due_back_date")

    work_order = lookup.work_order(work_order_id)
    loaner = lookup.equipment_asset(loaner_asset_id)
    require_route_owner(actor, _route_of_work_order(work_order))

    if work_order["wo_status"] not in SWAPPABLE_WO_STATUSES:
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID",
                       "A loaner swap is not meaningful on a %s work order."
                       % work_order["wo_status"])
    if work_order["loaner_status"] != "NONE":
        raise ApiError("ERR_LOANER_STATE_INVALID",
                       "This work order already has a loaner history (%s)."
                       % work_order["loaner_status"])
    # Rung 21 before rung 23: a RECONDITIONING asset carrying the wrong role surfaces
    # the sanitation hold, not the role mismatch.
    if loaner["asset_status"] == "RECONDITIONING" \
            and loaner.get("reconditioning_until") is not None \
            and loaner["reconditioning_until"] > now():
        raise ApiError("ERR_ASSET_UNDER_SANITATION_HOLD",
                       "The requested loaner is under sanitation hold.")
    if loaner["asset_role"] != "LOANER":
        raise ApiError("ERR_ASSET_ROLE_MISMATCH",
                       "Only a LOANER asset may be swapped in.")

    out_date = loaner_out.astimezone(UTC).date()
    due_back_date = loaner_due_back.astimezone(UTC).date()
    if due_back_date < out_date:
        raise ApiError("ERR_LOANER_NOT_AVAILABLE",
                       "loaner_due_back_date precedes loaner_out_date.")
    if calc.loaner_window_conflict(loaner["id"], out_date, due_back_date,
                                   exclude_wo_id=work_order["id"]):
        raise ApiError("ERR_LOANER_NOT_AVAILABLE",
                       "The loaner is already committed over that closed date interval.")

    # Passing lazily through IN_STOCK first when the hold has expired.
    cascade.lazy_release_reconditioning(loaner)
    work_order["loaner_asset_id"] = loaner["id"]
    work_order["loaner_out_date"] = loaner_out
    work_order["loaner_due_back_date"] = loaner_due_back
    work_order["loaner_status"] = "OUT"
    bump(work_order)
    loaner["asset_status"] = "ON_LOAN"
    bump(loaner)
    return ok(serializers.work_order(work_order))


@bp.post("/ocs/maintenance-work-orders/<work_order_id>/loaner-return")
def loaner_return(work_order_id):
    actor = authenticate((ROLE_ROUTE_TECHNICIAN,))
    fields = shape.fields()
    returned_on = fields.instant("returned_on")

    work_order = lookup.work_order(work_order_id)
    require_route_owner(actor, _route_of_work_order(work_order))
    if work_order["loaner_status"] not in RETURNABLE_LOANER_STATUSES:
        raise ApiError("ERR_LOANER_STATE_INVALID",
                       "Loaner state %s cannot be returned." % work_order["loaner_status"])
    if returned_on.astimezone(UTC).date() < \
            work_order["loaner_out_date"].astimezone(UTC).date():
        raise ApiError("ERR_VALIDATION", "returned_on precedes loaner_out_date.")

    # Lazy promotion first, so a late return still lands in RETURNED by way of OVERDUE.
    if work_order["loaner_status"] == "OUT" and \
            now().astimezone(UTC).date() > \
            work_order["loaner_due_back_date"].astimezone(UTC).date():
        work_order["loaner_status"] = "OVERDUE"

    work_order["loaner_returned_on"] = returned_on
    work_order["loaner_status"] = "RETURNED"
    bump(work_order)
    loaner = db.equipment_assets.get(work_order["loaner_asset_id"])
    if loaner is not None:
        loaner["asset_status"] = "RECONDITIONING"
        loaner["reconditioning_until"] = returned_on + timedelta(
            days=calc.RECONDITIONING_DAYS)
        bump(loaner)
    return ok(serializers.work_order(work_order))
