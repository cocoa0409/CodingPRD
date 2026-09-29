"""Food-bank donation pickup and manifest endpoints."""
from flask import Blueprint

import calc
import services
from db import db, ordered
from errors import ApiError
from middleware import (ROLE_ADMIN, ROLE_AUDITOR, ROLE_CLERK, ROLE_MANAGER,
                        ROLE_PARTNER, actor, authenticate, is_partner,
                        require_pickup_ownership)
from records import (assignment_by_id, assignments_of_pickup,
                     department_of_lot, item_of_lot, lot_by_id, new_record,
                     partner_by_id, pickup_by_id, store_by_id, touch)
from response import created, ok, public
from routes.common import (ASSIGNMENT_STATUSES, LOGISTICS_STATUSES,
                           MANIFEST_STATUSES, listing, matches)
from util import (DOCK_BUFFER_MINUTES, DONATION_WINDOW_HOURS, add_seconds,
                  fmt_instant, parse_instant)
from validate import (field_instant, field_int, field_string, json_body,
                      query_enum, query_string)

bp = Blueprint("donations", __name__)

READ_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK, ROLE_AUDITOR, ROLE_PARTNER)
LIVE_LOGISTICS = ("SCHEDULED", "CONFIRMED")


# --- reads -----------------------------------------------------------------
@bp.get("/fresh/donation-pickups/<pickup_id>")
def get_pickup(pickup_id):
    authenticate(*READ_ROLES)
    pickup = pickup_by_id(pickup_id)
    require_pickup_ownership(pickup)
    return ok(public(pickup))


@bp.get("/fresh/donation-pickups")
def list_pickups():
    authenticate(*READ_ROLES)
    store_id = query_string("store_id")
    partner_id = query_string("partner_id")
    logistics = query_enum("logistics_status", LOGISTICS_STATUSES)
    manifest = query_enum("manifest_status", MANIFEST_STATUSES)
    dock = query_string("dock_door_code")
    rows = [
        p for p in db.pickups.values()
        if matches(p, "store_id", store_id)
        and matches(p, "partner_id", partner_id)
        and matches(p, "logistics_status", logistics)
        and matches(p, "manifest_status", manifest)
        and matches(p, "dock_door_code", dock)
    ]
    if is_partner():
        rows = [p for p in rows if p["partner_id"] == actor()]
    return listing(rows)


@bp.get("/fresh/donation-assignments/<assignment_id>")
def get_assignment(assignment_id):
    authenticate(*READ_ROLES)
    return ok(public(assignment_by_id(assignment_id)))


@bp.get("/fresh/donation-assignments")
def list_assignments():
    authenticate(*READ_ROLES)
    pickup_id = query_string("pickup_id")
    lot_id = query_string("lot_id")
    status = query_enum("status", ASSIGNMENT_STATUSES)
    rows = [
        a for a in db.assignments.values()
        if matches(a, "pickup_id", pickup_id)
        and matches(a, "lot_id", lot_id)
        and matches(a, "status", status)
    ]
    return listing(rows)


# --- scheduling ------------------------------------------------------------
@bp.post("/fresh/donation-pickups")
def create_pickup():
    authenticate(ROLE_ADMIN, ROLE_MANAGER)
    body = json_body()
    store_id = field_string(body, "store_id", required=True, max_len=200)
    partner_id = field_string(body, "partner_id", required=True, max_len=200)
    dock = field_string(body, "dock_door_code", required=True, min_len=1,
                        max_len=8)
    start = field_instant(body, "scheduled_window_start", required=True)
    end = field_instant(body, "scheduled_window_end", required=True)
    if end <= start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "scheduled_window_end must be strictly after "
            "scheduled_window_start",
            400,
        )
    store = store_by_id(store_id)
    partner = partner_by_id(partner_id)
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ACTIVE",
                       "The food-bank partner is not ACTIVE")
    if partner["service_region_code"] != store["region_code"]:
        raise ApiError(
            "ERR_PARTNER_REGION_MISMATCH",
            "The partner does not serve this store's region",
        )
    if store["status"] != "ACTIVE" or not store["donation_program_enabled"]:
        raise ApiError(
            "ERR_DONATION_PROGRAM_DISABLED",
            "This store may not schedule food-bank donation pickups",
        )
    if dock not in store["dock_door_codes"]:
        raise ApiError("ERR_DOCK_DOOR_UNKNOWN",
                       "dock_door_code is not one of the store's dock doors")
    buffer_seconds = DOCK_BUFFER_MINUTES * 60
    for other in db.pickups.values():
        if other["store_id"] != store["id"]:
            continue
        if other["dock_door_code"] != dock:
            continue
        if other["logistics_status"] not in LIVE_LOGISTICS:
            continue
        other_start = parse_instant(other["scheduled_window_start"])
        other_end = parse_instant(other["scheduled_window_end"])
        if start <= add_seconds(other_end, buffer_seconds) and \
                other_start <= add_seconds(end, buffer_seconds):
            raise ApiError(
                "ERR_DOCK_WINDOW_OVERLAP",
                "Another live pickup already occupies this dock window",
            )
    pickup = new_record(db.pickups, {
        "store_id": store["id"],
        "partner_id": partner["id"],
        "dock_door_code": dock,
        "scheduled_window_start": fmt_instant(start),
        "scheduled_window_end": fmt_instant(end),
        "logistics_status": "SCHEDULED",
        "manifest_status": "DRAFT",
        "assignment_count": 0,
        "provisional_value_cents": 0,
        "credit_rate_pct": 0,
        "manifest_credit_cents": 0,
        "units_picked_up_total": 0,
        "completed_at": None,
    })
    return created(public(pickup))


# --- manifest lines --------------------------------------------------------
@bp.post("/fresh/donation-pickups/<pickup_id>/assignments")
def create_assignment(pickup_id):
    authenticate(ROLE_CLERK, ROLE_MANAGER)
    body = json_body()
    lot_id = field_string(body, "lot_id", required=True, max_len=200)
    quantity = field_int(body, "quantity_units", required=True, minimum=1)
    pickup = pickup_by_id(pickup_id)
    lot = lot_by_id(lot_id)
    item = item_of_lot(lot)
    if lot["status"] not in ("FRESH", "MARKED_DOWN") \
            or lot["quantity_on_hand"] <= 0 \
            or not item["donation_eligible"]:
        raise ApiError("ERR_LOT_NOT_PRICEABLE",
                       "This lot may not be pledged to a food bank")
    if pickup["manifest_status"] != "DRAFT":
        raise ApiError("ERR_MANIFEST_SEALED",
                       "The manifest is no longer DRAFT")
    department = department_of_lot(lot)
    if department["compliance_status"] == "BLOCKED":
        raise ApiError("ERR_DEPARTMENT_COMPLIANCE_BLOCKED",
                       "The lot's department is BLOCKED by an escalated audit")
    partner = db.partners[pickup["partner_id"]]
    sell_by = parse_instant(lot["sell_by_at"])
    now = db.now()
    if now >= sell_by:
        raise ApiError("ERR_PAST_DATE_NOT_DONATABLE",
                       "Product at or past its date code may not be donated")
    if department["code"] in ("MEAT", "SEAFOOD") and \
            not partner["cold_chain_certified"]:
        raise ApiError("ERR_COLD_CHAIN_NOT_CERTIFIED",
                       "The partner holds no cold-chain certification")
    if department["code"] not in partner["accepted_department_codes"]:
        raise ApiError(
            "ERR_PARTNER_DEPARTMENT_NOT_ACCEPTED",
            "The partner does not accept product from this department",
        )
    if now < add_seconds(sell_by, -DONATION_WINDOW_HOURS * 3600):
        raise ApiError("ERR_DONATION_WINDOW_CLOSED",
                       "The 48-hour donation window has not opened yet")
    if quantity > lot["quantity_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_UNITS",
                       "The pledge exceeds the units on hand")
    for line in assignments_of_pickup(pickup["id"]):
        if line["lot_id"] == lot["id"] and line["status"] in (
                "ASSIGNED", "PICKED_UP"):
            raise ApiError(
                "ERR_DUPLICATE_LOT_ASSIGNMENT",
                "This lot already appears on the pickup's manifest",
            )
    snapshot = lot["current_price_cents"]
    assignment = new_record(db.assignments, {
        "pickup_id": pickup["id"],
        "lot_id": lot["id"],
        "quantity_units": quantity,
        "unit_price_cents_snapshot": snapshot,
        "line_value_cents": quantity * snapshot,
        "line_credit_cents": 0,
        "status": "ASSIGNED",
    })
    lot["status"] = "DONATION_PENDING"
    touch(lot)
    services.recompute_pickup_rollups(pickup)
    services.revalue_manifest(pickup, "ASSIGNED", write_lines=False)
    services.recompute_liability(department)
    return created(public(assignment))


# --- manifest and truck transitions ---------------------------------------
@bp.post("/fresh/donation-pickups/<pickup_id>/seal")
def seal(pickup_id):
    authenticate(ROLE_MANAGER)
    json_body()
    pickup = pickup_by_id(pickup_id)
    if pickup["manifest_status"] != "DRAFT":
        raise ApiError("ERR_MANIFEST_SEALED",
                       "The manifest has already been sealed")
    if pickup["logistics_status"] not in LIVE_LOGISTICS:
        raise ApiError("ERR_PICKUP_NOT_COMPLETABLE",
                       "The pickup's logistics dimension is already closed")
    if pickup["assignment_count"] < 1:
        raise ApiError("ERR_EMPTY_MANIFEST",
                       "An empty manifest may not be sealed")
    pickup["manifest_status"] = "SEALED"
    services.revalue_manifest(pickup, "ASSIGNED")
    touch(pickup)
    return ok(public(pickup))


@bp.post("/fresh/donation-pickups/<pickup_id>/confirm")
def confirm(pickup_id):
    authenticate(ROLE_PARTNER)
    json_body()
    pickup = pickup_by_id(pickup_id)
    require_pickup_ownership(pickup)
    if pickup["logistics_status"] != "SCHEDULED":
        raise ApiError("ERR_PICKUP_NOT_CONFIRMABLE",
                       "Only a SCHEDULED pickup may be confirmed")
    partner = db.partners[pickup["partner_id"]]
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ACTIVE",
                       "The food-bank partner is not ACTIVE")
    pickup["logistics_status"] = "CONFIRMED"
    touch(pickup)
    return ok(public(pickup))


@bp.post("/fresh/donation-pickups/<pickup_id>/complete")
def complete(pickup_id):
    authenticate(ROLE_PARTNER)
    json_body()
    pickup = pickup_by_id(pickup_id)
    require_pickup_ownership(pickup)
    if pickup["logistics_status"] != "CONFIRMED":
        raise ApiError("ERR_PICKUP_NOT_COMPLETABLE",
                       "Only a CONFIRMED pickup may be completed")
    if pickup["manifest_status"] != "SEALED":
        raise ApiError("ERR_MANIFEST_NOT_SEALED",
                       "The manifest must be SEALED before completion")
    departments = {}
    for line in ordered(assignments_of_pickup(pickup["id"])):
        if line["status"] != "ASSIGNED":
            continue
        line["status"] = "PICKED_UP"
        touch(line)
        lot = db.lots[line["lot_id"]]
        quantity = line["quantity_units"]
        lot["units_donated"] = lot["units_donated"] + quantity
        lot["quantity_on_hand"] = max(0, lot["quantity_on_hand"] - quantity)
        if lot["quantity_on_hand"] == 0:
            lot["status"] = "DONATED"
            services.void_open_labels(lot)
            touch(lot)
        else:
            services.unwind_from_donation(lot)
        services.refresh_expected_sell_through(lot)
        department = department_of_lot(lot)
        departments[department["id"]] = department
    pickup["logistics_status"] = "COMPLETED"
    pickup["completed_at"] = fmt_instant(db.now())
    services.recompute_pickup_rollups(pickup)
    touch(pickup)
    services.recompute_partner_rollups(db.partners[pickup["partner_id"]])
    for department in departments.values():
        services.recompute_liability(department)
        services.recompute_shrink_ratio(department)
        services.recompute_posture(department)
    return ok(public(pickup))


@bp.post("/fresh/donation-pickups/<pickup_id>/cancel")
def cancel(pickup_id):
    authenticate(ROLE_MANAGER, ROLE_PARTNER)
    body = json_body()
    field_string(body, "cancel_reason", default=None, nullable=True,
                 min_len=1, max_len=240)
    pickup = pickup_by_id(pickup_id)
    require_pickup_ownership(pickup)
    if pickup["logistics_status"] not in LIVE_LOGISTICS:
        raise ApiError("ERR_PICKUP_NOT_COMPLETABLE",
                       "Only a SCHEDULED or CONFIRMED pickup may be cancelled")
    departments = services.reject_open_lines(pickup)
    pickup["logistics_status"] = "CANCELLED"
    touch(pickup)
    for department in departments.values():
        services.recompute_liability(department)
    return ok(public(pickup))


@bp.post("/fresh/donation-pickups/<pickup_id>/reconcile")
def reconcile(pickup_id):
    authenticate(ROLE_MANAGER)
    json_body()
    pickup = pickup_by_id(pickup_id)
    if pickup["manifest_status"] != "SEALED":
        raise ApiError("ERR_MANIFEST_NOT_SEALED",
                       "Only a SEALED manifest may be reconciled")
    if pickup["logistics_status"] not in ("COMPLETED", "CANCELLED", "MISSED"):
        raise ApiError(
            "ERR_PICKUP_NOT_RECONCILABLE",
            "The truck outcome is not known yet",
        )
    pickup["manifest_status"] = "RECONCILED"
    services.revalue_manifest(pickup, "PICKED_UP")
    touch(pickup)
    return ok(public(pickup))
