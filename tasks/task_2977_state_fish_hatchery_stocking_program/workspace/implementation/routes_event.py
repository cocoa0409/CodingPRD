"""The stocking trip: booking, loading, releasing, aborting and recoveries
(PRD 3.8 and 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import derive
import validators as v
from auth import authorize, scope_hatchery
from envelope import created, enum_filter, ok, pagination, paginate, str_filter
from errors import ApiError
from serialize import dump
from store import (Tx, base_record, clock, find, fmt_instant, get_or_404, hours, insert,
                   parse_instant, sort_key, values)

bp = Blueprint("stocking_event", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.VETERINARIAN, K.REGIONAL_BIOLOGIST)
LIVE_TRIP_STATUSES = ("SCHEDULED", "IN_TRANSIT", "RELEASED")


def _intersects(first, second):
    """"two trips intersect exactly when this trip's scheduled_depart_at falls
    strictly before the other's scheduled_return_at and the other's
    scheduled_depart_at falls strictly before this trip's scheduled_return_at"."""
    first_depart = parse_instant(first["scheduled_depart_at"])
    first_return = parse_instant(first["scheduled_return_at"])
    second_depart = parse_instant(second["scheduled_depart_at"])
    second_return = parse_instant(second["scheduled_return_at"])
    return first_depart < second_return and second_depart < first_return


@bp.post("/stocking-events")
def create_stocking_event():
    user_id, role = authorize(K.HATCHERY_MANAGER)
    body = v.body()
    # "declares stocking_request_id first, then lot_id, then transport_unit_id"
    stocking_request = get_or_404("stocking_requests", v.req_id(body, "stocking_request_id"))
    lot = get_or_404("rearing_lots", v.req_id(body, "lot_id"))
    unit = get_or_404("transport_units", v.req_id(body, "transport_unit_id"))
    scope_hatchery(role, user_id, lot["hatchery_id"])

    fish_count = v.req_int(body, "fish_count", minimum=Decimal(1))
    scheduled_depart_at = v.req_instant(body, "scheduled_depart_at")
    scheduled_return_at = v.req_instant(body, "scheduled_return_at")
    v.strictly_after("scheduled_return_at", scheduled_return_at,
                     "scheduled_depart_at", scheduled_depart_at)
    expected_lot_version = v.req_int(body, "expected_lot_version")
    mark_type = v.opt_enum(body, "mark_type", K.MARK_TYPES, default="NONE")
    marked_count = v.opt_int(body, "marked_count", default=0, minimum=Decimal(0))
    if mark_type == "NONE":
        if marked_count != 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "marked_count must be 0 when mark_type is NONE.")
    elif marked_count > fish_count:
        raise ApiError("ERR_INVALID_REQUEST", "marked_count must not exceed fish_count.")

    if expected_lot_version != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION", "The lot has advanced since it was read.")

    if stocking_request["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE",
                       "A trip may only be scheduled against an ALLOCATED request.")
    if lot["health_status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "This lot is under quarantine.")

    unreserved = lot["count_on_hand"] - lot["reserved_count"]
    if fish_count > unreserved:
        raise ApiError("ERR_LOT_INSUFFICIENT_FISH",
                       "The lot does not hold that many unreserved fish.")
    if fish_count > stocking_request["allocated_count"]:
        raise ApiError("ERR_ALLOCATION_EXCEEDED",
                       "A trip may not ship more fish than the request was granted.")
    if lot["species"] != stocking_request["species"]:
        raise ApiError("ERR_SPECIES_MISMATCH",
                       "The lot's species does not match the request's.")

    hatchery = get_or_404("hatcheries", lot["hatchery_id"])
    planned_load_lbs = calc.planned_load_lbs(fish_count, lot["avg_weight_g"])
    transport_cost_cents = calc.transport_cost_cents(planned_load_lbs)
    if transport_cost_cents > hatchery["budget_available_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED",
                       "The trip's transport cost exceeds the station's appropriation.")

    record = base_record()
    record.update({
        "stocking_request_id": stocking_request["id"],
        "lot_id": lot["id"],
        "transport_unit_id": unit["id"],
        "fish_count": fish_count,
        "scheduled_depart_at": fmt_instant(scheduled_depart_at),
        "scheduled_return_at": fmt_instant(scheduled_return_at),
        "mark_type": mark_type,
        "marked_count": marked_count,
        "planned_load_lbs": planned_load_lbs,
        "transport_cost_cents": transport_cost_cents,
        "max_fish_allowed": None,
        "oxygen_flow_lpm": calc.oxygen_flow_lpm(planned_load_lbs),
        "loaded_at": None,
        "load_water_temp_c": None,
        "measured_load_lbs": None,
        "arrived_at": None,
        "site_water_temp_c": None,
        "tempering_minutes": None,
        "transport_mortality_count": 0,
        "tempering_minutes_required": None,
        "released_count": None,
        "recovered_count": 0,
        "creel_sample_fraction": None,
        "contribution_index_cohort": None,
        "contribution_index_harvest": None,
        "effective_marked_count": calc.effective_marked_count(mark_type, marked_count),
        "released_at": None,
        "aborted_at": None,
        "abort_reason": None,
        "status": "SCHEDULED",
    })
    insert("stocking_events", record)

    tx = Tx()
    # "the fish_count is added to the lot's reserved_count and the lot's version
    # advances"; nothing yet leaves count_on_hand.
    derive.recompute_lot_reservation(tx, lot)
    tx.touch(lot)
    derive.recompute_hatchery(tx, hatchery)
    tx.settle()
    return created(dump(record))


@bp.get("/stocking-events/<identifier>")
def get_stocking_event(identifier):
    user_id, role = authorize(*READ_ROLES)
    event = get_or_404("stocking_events", identifier)
    lot = get_or_404("rearing_lots", event["lot_id"])
    scope_hatchery(role, user_id, lot["hatchery_id"])
    return ok(dump(event))


@bp.get("/stocking-events")
def list_stocking_events():
    authorize(*READ_ROLES)
    lot_id = str_filter("lot_id")
    stocking_request_id = str_filter("stocking_request_id")
    transport_unit_id = str_filter("transport_unit_id")
    status = enum_filter("status", K.EVENT_STATUSES)
    limit, offset = pagination()

    records = values("stocking_events")
    if lot_id is not None:
        records = [r for r in records if r["lot_id"] == lot_id]
    if stocking_request_id is not None:
        records = [r for r in records if r["stocking_request_id"] == stocking_request_id]
    if transport_unit_id is not None:
        records = [r for r in records if r["transport_unit_id"] == transport_unit_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


# --- loading ----------------------------------------------------------------

def _health_gates(lot):
    """PRD 2.10: the internal level-10 order — quarantine, expired certificate,
    never certified, then the drug-withdrawal window."""
    if lot["health_status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "This lot is under quarantine.")
    expiry = lot["certificate_expires_at"]
    if expiry is not None and clock() > parse_instant(expiry):
        raise ApiError("ERR_HEALTH_CERTIFICATE_EXPIRED",
                       "The lot's health certificate has lapsed.")
    if lot["health_status"] != "CERTIFIED":
        raise ApiError("ERR_LOT_NOT_CERTIFIED", "This lot carries no health certificate.")
    inspection = derive.latest_inspection_with_withdrawal(lot["id"])
    if inspection is not None:
        clears_at = parse_instant(inspection["withdrawal_clears_at"])
        if clock() < clears_at:
            raise ApiError("ERR_WITHDRAWAL_PERIOD_ACTIVE",
                           "The drug-withdrawal window has not elapsed.")


@bp.post("/stocking-events/<identifier>/load")
def load_stocking_event(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER)
    event = get_or_404("stocking_events", identifier)
    lot = get_or_404("rearing_lots", event["lot_id"])
    scope_hatchery(role, user_id, lot["hatchery_id"])

    body = v.body()
    loaded_at = v.req_instant(body, "loaded_at")
    load_water_temp_c = v.req_num(body, "load_water_temp_c")
    measured_load_lbs = v.opt_num(body, "measured_load_lbs", minimum=Decimal(0))

    if event["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED trip may be loaded.")

    hatchery = get_or_404("hatcheries", lot["hatchery_id"])
    if hatchery["operating_posture"] == "FROZEN":
        raise ApiError("ERR_HATCHERY_FROZEN", "This station is frozen.")
    _health_gates(lot)

    unit = get_or_404("transport_units", event["transport_unit_id"])
    if unit["status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_TRANSPORT_UNIT_UNAVAILABLE",
                       "This transport unit is out of service.")
    for other in values("stocking_events"):
        if other["id"] == event["id"]:
            continue
        if other["transport_unit_id"] != unit["id"]:
            continue
        if other["status"] not in LIVE_TRIP_STATUSES:
            continue
        if _intersects(event, other):
            raise ApiError("ERR_TRANSPORT_UNIT_UNAVAILABLE",
                           "Another trip on this unit overlaps this trip's interval.")

    # "the station's bulk oxygen supply is shared across every truck that is out
    # at the same time"
    demand = Decimal(event["oxygen_flow_lpm"])
    for other in derive.events_of_hatchery(hatchery["id"]):
        if other["id"] == event["id"] or other["status"] != "IN_TRANSIT":
            continue
        if _intersects(event, other):
            demand += Decimal(other["oxygen_flow_lpm"])
    if demand > Decimal(hatchery["oxygen_supply_lpm"]):
        raise ApiError("ERR_OXYGEN_SUPPLY_EXCEEDED",
                       "The station's bulk oxygen supply cannot cover the trips out at once.")

    max_fish_allowed = calc.load_plan(unit, lot["avg_weight_g"], load_water_temp_c)
    if max_fish_allowed is None or event["fish_count"] > max_fish_allowed:
        raise ApiError("ERR_TRANSPORT_CAPACITY_EXCEEDED",
                       "The trip's fish_count exceeds the unit's load plan.")

    tx = Tx()
    event["status"] = "IN_TRANSIT"
    event["loaded_at"] = fmt_instant(loaded_at)
    event["load_water_temp_c"] = load_water_temp_c
    event["measured_load_lbs"] = measured_load_lbs
    event["oxygen_flow_lpm"] = calc.oxygen_flow_lpm(event["planned_load_lbs"])
    event["max_fish_allowed"] = max_fish_allowed
    tx.touch(event)

    unit["status"] = "IN_USE"
    unit["current_event_id"] = event["id"]
    tx.touch(unit)
    tx.settle()
    return ok(dump(event))


# --- release ----------------------------------------------------------------

@bp.post("/stocking-events/<identifier>/release")
def release_stocking_event(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER)
    event = get_or_404("stocking_events", identifier)
    lot = get_or_404("rearing_lots", event["lot_id"])
    scope_hatchery(role, user_id, lot["hatchery_id"])

    body = v.body()
    arrived_at = v.req_instant(body, "arrived_at")
    site_water_temp_c = v.req_num(body, "site_water_temp_c")
    tempering_minutes = v.req_int(body, "tempering_minutes", minimum=Decimal(0))
    transport_mortality_count = v.opt_int(body, "transport_mortality_count", default=0,
                                        minimum=Decimal(0))

    if event["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_TRANSIT trip may be released.")

    stocking_request = get_or_404("stocking_requests", event["stocking_request_id"])
    water = get_or_404("waters", stocking_request["water_id"])
    if water["status"] != "ACTIVE":
        raise ApiError("ERR_WATER_CLOSED", "The receiving water is closed.")

    delta = calc.temp_delta_c(site_water_temp_c, event["load_water_temp_c"])
    if delta > K.MAX_TEMP_DELTA_C:
        raise ApiError("ERR_TEMP_DELTA_EXCEEDED",
                       "The thermal shock exceeds the releasable tolerance.")
    minutes_required = calc.tempering_minutes_required(delta)
    if tempering_minutes < minutes_required:
        raise ApiError("ERR_ACCLIMATION_INSUFFICIENT",
                       "The load was not tempered for long enough.")
    if water["last_release_at"]:
        rest_until = parse_instant(water["last_release_at"]) + hours(K.WATER_REST_BUFFER_HOURS)
        if clock() < rest_until:
            raise ApiError("ERR_WATER_REST_BUFFER",
                           "The receiving water has not had its rest interval.")

    tx = Tx()
    stamp = fmt_instant(clock())
    event["status"] = "RELEASED"
    event["arrived_at"] = fmt_instant(arrived_at)
    event["site_water_temp_c"] = site_water_temp_c
    event["tempering_minutes"] = tempering_minutes
    event["transport_mortality_count"] = transport_mortality_count
    event["tempering_minutes_required"] = minutes_required
    event["released_count"] = event["fish_count"] - transport_mortality_count
    event["released_at"] = stamp
    tx.touch(event)

    # the demand side settles first so the water's counters see FULFILLED
    stocking_request["status"] = "FULFILLED"
    stocking_request["fulfilled_at"] = stamp
    tx.touch(stocking_request)

    lot["count_on_hand"] = lot["count_on_hand"] - event["fish_count"]
    lot["cumulative_mortality_count"] = (lot["cumulative_mortality_count"]
                                        + transport_mortality_count)
    tx.touch(lot)
    derive.recompute_lot_reservation(tx, lot)
    derive.settle_lot_after_release(tx, lot)

    derive.recompute_water(tx, water)
    water["last_release_at"] = stamp
    tx.touch(water)

    derive.recompute_hatchery(tx, get_or_404("hatcheries", lot["hatchery_id"]))

    unit = find("transport_units", event["transport_unit_id"])
    if unit is not None and unit["current_event_id"] == event["id"]:
        unit["status"] = "AVAILABLE"
        unit["current_event_id"] = None
        tx.touch(unit)

    derive.close_plan_if_complete(tx, find("allocation_plans",
                                           stocking_request["allocation_plan_id"]))
    tx.settle()
    return ok(dump(event))


# --- abort ------------------------------------------------------------------

@bp.post("/stocking-events/<identifier>/abort")
def abort_stocking_event(identifier):
    user_id, role = authorize(K.HATCHERY_MANAGER, K.PROGRAM_ADMIN)
    event = get_or_404("stocking_events", identifier)
    lot = get_or_404("rearing_lots", event["lot_id"])
    scope_hatchery(role, user_id, lot["hatchery_id"])

    if event["status"] not in ("SCHEDULED", "IN_TRANSIT"):
        raise ApiError("ERR_INVALID_STATE", "This trip is already terminal.")

    tx = Tx()
    event["status"] = "ABORTED"
    event["aborted_at"] = fmt_instant(clock())
    event["abort_reason"] = "OPERATOR_ABORT"
    event["released_count"] = 0
    tx.touch(event)

    # "It returns the fish ... while leaving count_on_hand untouched."
    derive.recompute_lot_reservation(tx, lot)
    tx.touch(lot)

    stocking_request = find("stocking_requests", event["stocking_request_id"])
    if stocking_request is not None:
        stocking_request["status"] = "DEFERRED"
        stocking_request["allocated_count"] = 0
        stocking_request["allocated_at"] = None
        stocking_request["deferral_reason"] = "EVENT_ABORTED"
        tx.touch(stocking_request)
        water = find("waters", stocking_request["water_id"])
        if water is not None:
            derive.recompute_water(tx, water)

    derive.recompute_hatchery(tx, get_or_404("hatcheries", lot["hatchery_id"]))

    unit = find("transport_units", event["transport_unit_id"])
    if unit is not None and unit["current_event_id"] == event["id"]:
        unit["status"] = "AVAILABLE"
        unit["current_event_id"] = None
        tx.touch(unit)
    tx.settle()
    return ok(dump(event))


# --- recoveries -------------------------------------------------------------

@bp.post("/stocking-events/<identifier>/recoveries")
def record_event_recoveries(identifier):
    authorize(K.PROGRAM_ADMIN, K.REGIONAL_BIOLOGIST)
    event = get_or_404("stocking_events", identifier)

    body = v.body()
    recovered_count = v.req_int(body, "recovered_count", minimum=Decimal(0))
    creel_sample_fraction = v.req_num(body, "creel_sample_fraction", minimum=Decimal(0),
                                     maximum=Decimal(1), exclusive_min=True)

    if event["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE",
                       "Recoveries may only be reported against a RELEASED trip.")

    tx = Tx()
    effective_marked = calc.effective_marked_count(event["mark_type"], event["marked_count"])
    cohort, harvest = calc.contribution_indices(recovered_count, effective_marked,
                                                event["released_count"],
                                                creel_sample_fraction)
    event["recovered_count"] = recovered_count
    event["creel_sample_fraction"] = creel_sample_fraction
    event["effective_marked_count"] = effective_marked
    event["contribution_index_cohort"] = cohort
    event["contribution_index_harvest"] = harvest
    tx.touch(event)
    tx.settle()
    return ok(dump(event))
