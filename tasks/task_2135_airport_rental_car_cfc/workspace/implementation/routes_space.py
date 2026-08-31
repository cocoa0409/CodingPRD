"""Counter/ready-return occupancy and fleet parking allocation."""

from flask import Blueprint

import calc
import serializers as ser
from domain import agreement_or_404, bump, check_owner, rows_of
from errors import ApiError
from store import all_rows, clock_date, db, get, new_row
from validation import (ALL_ROLES, body, endpoint, opt_bool, pagination, paginate,
                        q_enum, q_str, req_date, req_int, req_str, to_date)
import response as resp

bp = Blueprint("space", __name__)

ASSIGNMENT_STATUSES = ("ALLOCATED", "ACTIVE", "RELEASED")
ALLOCATION_STATUSES = ("ALLOCATED", "RELEASED")


# --------------------------------------------------------------------------
# CounterAssignment
# --------------------------------------------------------------------------

@bp.route("/rac/counter-assignments", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def create_counter_assignment():
    data = body()
    agreement_id = req_str(data, "agreement_id")
    counter_space_id = req_str(data, "counter_space_id")
    start_date = req_date(data, "effective_start_date")
    end_date = req_date(data, "effective_end_date")
    expected_agreement_version = req_int(data, "expected_agreement_version")

    agreement = agreement_or_404(agreement_id)
    space = get("counter_spaces", counter_space_id, "ERR_COUNTER_SPACE_NOT_FOUND")

    check_owner(agreement)

    if expected_agreement_version != agreement["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if to_date(start_date) >= to_date(end_date):
        raise ApiError("ERR_INVALID_DATE_RANGE")

    if start_date < agreement["term_start_date"] or end_date > agreement["term_end_date"]:
        raise ApiError("ERR_OUTSIDE_AGREEMENT_TERM")

    for existing in all_rows("counter_assignments"):
        if existing["counter_space_id"] != space["id"]:
            continue
        if existing["status"] not in ("ALLOCATED", "ACTIVE"):
            continue
        if start_date < existing["effective_end_date"] and \
                existing["effective_start_date"] < end_date:
            raise ApiError("ERR_COUNTER_SPACE_OCCUPIED")

    row = new_row("counter_assignments", {
        "agreement_id": agreement["id"],
        "counter_space_id": space["id"],
        "effective_start_date": start_date,
        "effective_end_date": end_date,
        "status": "ALLOCATED",
        "released_on_date": None,
    })
    space["assignment_count"] += 1
    bump(space)
    agreement["counter_units_assigned"] += 1
    bump(agreement)
    return resp.created(ser.counter_assignment(row))


@bp.route("/rac/counter-assignments/<counter_assignment_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_counter_assignment(counter_assignment_id):
    row = get("counter_assignments", counter_assignment_id,
              "ERR_COUNTER_ASSIGNMENT_NOT_FOUND")
    return resp.ok(ser.counter_assignment(row))


@bp.route("/rac/counter-assignments", methods=["GET"])
@endpoint(ALL_ROLES)
def list_counter_assignments():
    limit, offset = pagination()
    rows = rows_of("counter_assignments",
                   agreement_id=q_str("agreement_id"),
                   counter_space_id=q_str("counter_space_id"),
                   status=q_enum("status", ASSIGNMENT_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.counter_assignment)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/counter-assignments/<counter_assignment_id>/activate", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def activate_counter_assignment(counter_assignment_id):
    row = get("counter_assignments", counter_assignment_id,
              "ERR_COUNTER_ASSIGNMENT_NOT_FOUND")
    agreement = db.agreements[row["agreement_id"]]
    check_owner(agreement)

    if row["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE")
    if agreement["contract_status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")

    space = db.counter_spaces[row["counter_space_id"]]
    if space.get("active_assignment_id") is not None:
        raise ApiError("ERR_COUNTER_SPACE_OCCUPIED")

    row["status"] = "ACTIVE"
    space["active_assignment_id"] = row["id"]
    bump(row)
    bump(space)
    return resp.ok(ser.counter_assignment(row))


@bp.route("/rac/counter-assignments/<counter_assignment_id>/release", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def release_counter_assignment(counter_assignment_id):
    row = get("counter_assignments", counter_assignment_id,
              "ERR_COUNTER_ASSIGNMENT_NOT_FOUND")
    agreement = db.agreements[row["agreement_id"]]
    check_owner(agreement)

    if row["status"] not in ("ALLOCATED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE")

    space = db.counter_spaces[row["counter_space_id"]]
    was_active = row["status"] == "ACTIVE"
    row["status"] = "RELEASED"
    row["released_on_date"] = clock_date()
    space["assignment_count"] -= 1
    agreement["counter_units_assigned"] -= 1
    if was_active:
        space["active_assignment_id"] = None
    bump(row)
    bump(space)
    bump(agreement)
    return resp.ok(ser.counter_assignment(row))


# --------------------------------------------------------------------------
# FleetAllocation
# --------------------------------------------------------------------------

@bp.route("/rac/fleet-allocations", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def create_fleet_allocation():
    data = body()
    agreement_id = req_str(data, "agreement_id")
    zone_id = req_str(data, "zone_id")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    stalls_requested = req_int(data, "stalls_requested", minimum=1)
    allow_overflow = opt_bool(data, "allow_overflow", False)
    expected_zone_version = req_int(data, "expected_zone_version")

    agreement = agreement_or_404(agreement_id)
    zone = get("zones", zone_id, "ERR_ZONE_NOT_FOUND")

    check_owner(agreement)

    if expected_zone_version != zone["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if to_date(start_date) > to_date(end_date):
        raise ApiError("ERR_INVALID_DATE_RANGE")

    if start_date < agreement["term_start_date"] or end_date > agreement["term_end_date"]:
        raise ApiError("ERR_OUTSIDE_AGREEMENT_TERM")

    facility = db.facilities[zone["facility_id"]]

    zone_in_use = 0
    for existing in all_rows("fleet_allocations"):
        if existing["zone_id"] != zone["id"] or existing["status"] != "ALLOCATED":
            continue
        if start_date <= existing["end_date"] and existing["start_date"] <= end_date:
            zone_in_use += existing["zone_stalls_granted"]
    zone_free = max(0, zone["stall_capacity"] - zone_in_use)
    zone_stalls_granted = min(stalls_requested, zone_free)

    overflow_need = stalls_requested - zone_stalls_granted
    if overflow_need > 0:
        if allow_overflow is not True:
            raise ApiError("ERR_ZONE_CAPACITY_EXCEEDED")
        facility_zone_ids = set(z["id"] for z in all_rows("zones")
                                if z["facility_id"] == facility["id"])
        overflow_in_use = 0
        for existing in all_rows("fleet_allocations"):
            if existing["zone_id"] not in facility_zone_ids:
                continue
            if existing["status"] != "ALLOCATED":
                continue
            if start_date <= existing["end_date"] and existing["start_date"] <= end_date:
                overflow_in_use += existing["overflow_stalls_granted"]
        overflow_free = max(0, facility["overflow_lot_stalls"] - overflow_in_use)
        if overflow_need > overflow_free:
            raise ApiError("ERR_OVERFLOW_EXHAUSTED")
        overflow_stalls_granted = overflow_need
    else:
        overflow_stalls_granted = 0

    days = calc.inclusive_days(start_date, end_date)
    surcharge = overflow_stalls_granted * facility["overflow_daily_surcharge_cents"] * days

    row = new_row("fleet_allocations", {
        "agreement_id": agreement["id"],
        "zone_id": zone["id"],
        "start_date": start_date,
        "end_date": end_date,
        "stalls_requested": stalls_requested,
        "allow_overflow": allow_overflow,
        "zone_stalls_granted": zone_stalls_granted,
        "overflow_stalls_granted": overflow_stalls_granted,
        "inclusive_days": days,
        "overflow_surcharge_cents": surcharge,
        "status": "ALLOCATED",
    })

    zone["stalls_allocated"] += zone_stalls_granted
    facility["overflow_stalls_allocated"] += overflow_stalls_granted
    agreement["fleet_stalls_allocated"] += zone_stalls_granted + overflow_stalls_granted
    bump(zone)
    bump(facility)
    bump(agreement)
    return resp.created(ser.fleet_allocation(row))


@bp.route("/rac/fleet-allocations/<fleet_allocation_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_fleet_allocation(fleet_allocation_id):
    row = get("fleet_allocations", fleet_allocation_id, "ERR_FLEET_ALLOCATION_NOT_FOUND")
    return resp.ok(ser.fleet_allocation(row))


@bp.route("/rac/fleet-allocations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_fleet_allocations():
    limit, offset = pagination()
    rows = rows_of("fleet_allocations",
                   agreement_id=q_str("agreement_id"),
                   zone_id=q_str("zone_id"),
                   status=q_enum("status", ALLOCATION_STATUSES))
    items, limit, offset, total = paginate(rows, limit, offset, ser.fleet_allocation)
    return resp.listing(items, limit, offset, total)


@bp.route("/rac/fleet-allocations/<fleet_allocation_id>/release", methods=["POST"])
@endpoint(["ConcessionaireOperator", "FacilityAdmin"])
def release_fleet_allocation(fleet_allocation_id):
    row = get("fleet_allocations", fleet_allocation_id, "ERR_FLEET_ALLOCATION_NOT_FOUND")
    agreement = db.agreements[row["agreement_id"]]
    check_owner(agreement)

    if row["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE")

    zone = db.zones[row["zone_id"]]
    facility = db.facilities[zone["facility_id"]]

    row["status"] = "RELEASED"
    zone["stalls_allocated"] -= row["zone_stalls_granted"]
    facility["overflow_stalls_allocated"] -= row["overflow_stalls_granted"]
    agreement["fleet_stalls_allocated"] -= \
        row["zone_stalls_granted"] + row["overflow_stalls_granted"]
    bump(row)
    bump(zone)
    bump(facility)
    bump(agreement)
    return resp.ok(ser.fleet_allocation(row))
