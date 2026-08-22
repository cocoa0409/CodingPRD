"""Cycles: scheduling, the load map, readiness, the dwell and dosimetry review."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import response
import validation as V
from db import db
from errors import ApiError
from middleware import authenticate
from routes.common import fetch, paginate, peek
from services import calc
from services.domain import (TERMINAL_SCHEDULING_STATUSES, by_seq,
                             current_qualification, delete_position_row,
                             deviation_qualification_cascade,
                             indicators_of_cycle, lots_of_cycle, new_record,
                             positions_of_cycle, positions_of_lot,
                             recompute_cycle_load, recompute_open_lot_count,
                             refresh_lot_pallets, settle_lot_after_removal,
                             touch, unwind_cycle_state)

bp = Blueprint("cycles", __name__)

ZONES = ("MIN_DOSE", "MAX_DOSE", "INTERIOR", "EDGE")
LOAD_MAP_STATES = ("PLANNED", "LOADING", "READY")


# =====================================================================
# Cycle scheduling (PRD 3.4)
# =====================================================================
@bp.post("/sterilization/cycles")
def create_cycle():
    authenticate("CycleOperator")
    body = V.body()
    chamber_id = V.req_id(body, "chamber_id")
    recipe_id = V.req_id(body, "recipe_id")
    cycle_code = V.req_string(body, "cycle_code", 1, 32)
    scheduled_start_at = V.req_datetime(body, "scheduled_start_at")
    scheduled_end_at = V.req_datetime(body, "scheduled_end_at")
    if not scheduled_end_at > scheduled_start_at:
        raise ApiError("ERR_VALIDATION",
                       "scheduled_end_at must be strictly later than scheduled_start_at.")
    raw_eto_charge_kg = V.opt_number(body, "raw_eto_charge_kg", ge=0,
                                     default=Decimal("0"))

    recipe = fetch("recipes", recipe_id)
    chamber = fetch("chambers", chamber_id)

    for existing in db.cycles.values():
        if existing["cycle_code"] == cycle_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "cycle_code '%s' is already registered." % cycle_code)

    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_NOT_APPROVED")

    if chamber["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_CHAMBER_UNAVAILABLE",
                       "A DECOMMISSIONED chamber cannot host a cycle.")

    if recipe["modality"] != chamber["modality"]:
        raise ApiError("ERR_MODALITY_MISMATCH",
                       "Recipe modality %s does not match chamber modality %s."
                       % (recipe["modality"], chamber["modality"]))

    occupancy_end_at = scheduled_end_at + timedelta(minutes=chamber["turnaround_minutes"])

    # priority 75 - chamber occupancy: pairwise, buffer extended, half open
    new_start = clock.truncate_s(scheduled_start_at)
    new_occ_end = clock.truncate_s(occupancy_end_at)
    for other in db.cycles.values():
        if other["chamber_id"] != chamber["id"]:
            continue
        if other["status"] in TERMINAL_SCHEDULING_STATUSES:
            continue
        other_start = clock.truncate_s(other["scheduled_start_at"])
        other_occ_end = clock.truncate_s(other["occupancy_end_at"])
        if new_start < other_occ_end and other_start < new_occ_end:
            raise ApiError("ERR_CHAMBER_WINDOW_CONFLICT")

    # priority 78 - permit EtO concurrency: aggregate, unbuffered, closed
    permit = db.permits.get(chamber["permit_id"])
    if chamber["modality"] == "ETO" and permit is not None:
        new_dwell_start = new_start
        new_dwell_end = clock.truncate_s(scheduled_end_at)
        collisions = 0
        for other in db.cycles.values():
            other_chamber = db.chambers.get(other["chamber_id"])
            if other_chamber is None or other_chamber["permit_id"] != permit["id"]:
                continue
            if other_chamber["modality"] != "ETO":
                continue
            if other["status"] in TERMINAL_SCHEDULING_STATUSES:
                continue
            other_start = clock.truncate_s(other["scheduled_start_at"])
            other_end = clock.truncate_s(other["scheduled_end_at"])
            if new_dwell_start <= other_end and other_start <= new_dwell_end:
                collisions += 1
        if collisions >= permit["max_concurrent_eto_cycles"]:
            raise ApiError("ERR_PERMIT_CONCURRENCY_EXCEEDED")

    cycle = new_record({
        "chamber_id": chamber["id"],
        "recipe_id": recipe["id"],
        "cycle_code": cycle_code,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "occupancy_end_at": occupancy_end_at,
        "raw_eto_charge_kg": raw_eto_charge_kg,
        "abated_eto_kg": Decimal("0.000"),
        "emission_fee_usd": Decimal("0.00"),
        "loaded_pallet_count": 0,
        "load_density_g_per_cm3": Decimal("0.0000"),
        "delivered_dose_kgy": None,
        "max_observed_dose_kgy": None,
        "deviation_code": "NONE",
        "operator_user_id": None,
        "dosimetry_closed_by_user_id": None,
        "status": "PLANNED",
    })
    db.cycles[cycle["id"]] = cycle
    return response.object_response(cycle, 201)


@bp.get("/sterilization/cycles/<cycle_id>")
def read_cycle(cycle_id):
    authenticate("CycleOperator", "DosimetryAnalyst", "QualityReleaseOfficer",
                 "RegulatoryAdmin")
    return response.object_response(fetch("cycles", cycle_id))


@bp.get("/sterilization/cycles")
def list_cycles():
    authenticate("CycleOperator", "DosimetryAnalyst", "QualityReleaseOfficer",
                 "RegulatoryAdmin")
    limit, offset = V.pagination()
    chamber_id = request.args.get("chamber_id")
    recipe_id = request.args.get("recipe_id")
    status = request.args.get("status")
    rows = [
        c for c in db.cycles.values()
        if (chamber_id is None or c["chamber_id"] == chamber_id)
        and (recipe_id is None or c["recipe_id"] == recipe_id)
        and (status is None or c["status"] == status)
    ]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# =====================================================================
# Load map (PRD 3.5)
# =====================================================================
@bp.post("/sterilization/cycles/<cycle_id>/load-positions")
def create_load_position(cycle_id):
    authenticate("CycleOperator")
    body = V.body()
    lot_id = V.req_id(body, "lot_id")
    position_index = V.req_int(body, "position_index", minimum=1)
    zone = V.req_enum(body, "zone", ZONES)
    pallet_count = V.req_int(body, "pallet_count", minimum=1)
    expected_cycle_version = V.req_int(body, "expected_cycle_version")

    preview_cycle = peek("cycles", cycle_id)
    if preview_cycle is not None:
        preview_chamber = db.chambers.get(preview_cycle["chamber_id"])
        if preview_chamber is not None and position_index > preview_chamber["pallet_capacity"]:
            raise ApiError("ERR_VALIDATION",
                           "position_index must not exceed the chamber's pallet_capacity.")

    cycle = fetch("cycles", cycle_id)
    lot = fetch("lots", lot_id)

    chamber = db.chambers.get(cycle["chamber_id"])
    recipe = db.recipes.get(cycle["recipe_id"])
    product = db.products.get(lot["product_id"])
    customer = db.customers.get(lot["customer_id"])

    # priority 45 - declared transition
    if cycle["status"] not in LOAD_MAP_STATES:
        raise ApiError("ERR_INVALID_STATE",
                       "A load map may only be revised from PLANNED, LOADING or READY.")

    # priority 47 - lot schedulability
    if not lot["schedulable"]:
        raise ApiError("ERR_LOT_NOT_SCHEDULABLE")

    # priority 50 - optimistic concurrency on the parent cycle
    if expected_cycle_version != cycle["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION")

    # priority 60 - current qualification
    if current_qualification(lot["product_id"], cycle["recipe_id"]) is None:
        raise ApiError("ERR_QUALIFICATION_NOT_CURRENT")

    # priority 72 - modality coherence
    if customer is None or chamber["modality"] not in customer["contracted_modalities"]:
        raise ApiError("ERR_MODALITY_MISMATCH",
                       "The customer is not contracted for %s work." % chamber["modality"])

    # priority 88 - capacity
    if cycle["loaded_pallet_count"] + pallet_count > chamber["pallet_capacity"] \
            or pallet_count > lot["available_pallet_count"]:
        raise ApiError("ERR_CHAMBER_CAPACITY_EXCEEDED")

    # priority 89 - slot uniqueness
    for existing in positions_of_cycle(cycle["id"]):
        if existing["position_index"] == position_index:
            raise ApiError("ERR_DUPLICATE_POSITION_INDEX")

    # priority 92 - cumulative dose headroom
    projected = calc.round_dose(calc.dec(lot["cumulative_dose_kgy"])
                               + calc.dec(recipe["target_dose_kgy"]))
    if projected > calc.dec(product["max_cumulative_dose_kgy"]):
        raise ApiError("ERR_CUMULATIVE_DOSE_EXCEEDED")

    position = new_record({
        "cycle_id": cycle["id"],
        "lot_id": lot["id"],
        "position_index": position_index,
        "zone": zone,
        "pallet_count": pallet_count,
        "cycle_version_after": None,
    })
    db.load_positions[position["id"]] = position

    recompute_cycle_load(cycle)
    if cycle["status"] in ("PLANNED", "READY"):
        cycle["status"] = "LOADING"
    touch(cycle)
    position["cycle_version_after"] = cycle["version"]

    refresh_lot_pallets(lot)
    if lot["status"] == "RECEIVED":
        lot["status"] = "STAGED"
    touch(lot)
    recompute_open_lot_count(lot["customer_id"])

    return response.object_response(position, 201)


@bp.delete("/sterilization/cycles/<cycle_id>/load-positions/<position_id>")
def delete_load_position(cycle_id, position_id):
    authenticate("CycleOperator")
    cycle = fetch("cycles", cycle_id)
    position = db.load_positions.get(position_id)
    if position is None or position["cycle_id"] != cycle["id"]:
        raise ApiError("ERR_LOAD_POSITION_NOT_FOUND")

    if cycle["status"] not in LOAD_MAP_STATES:
        raise ApiError("ERR_INVALID_STATE",
                       "Slots may only be removed while the cycle is PLANNED, LOADING or READY.")

    lot = db.lots.get(position["lot_id"])
    delete_position_row(position, cycle)
    unwind_cycle_state(cycle)
    touch(cycle)
    if lot is not None:
        settle_lot_after_removal(lot)
    return response.no_content_response()


# =====================================================================
# Readiness sign-off (PRD 3.6)
# =====================================================================
@bp.post("/sterilization/cycles/<cycle_id>/ready")
def mark_cycle_ready(cycle_id):
    authenticate("CycleOperator")
    cycle = fetch("cycles", cycle_id)

    # priority 45 - the gate deliberately admits PLANNED as well as LOADING
    if cycle["status"] not in ("PLANNED", "LOADING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Readiness sign-off is only accepted from PLANNED or LOADING.")

    positions = positions_of_cycle(cycle["id"])
    # priority 82 - non-empty load map
    if not positions:
        raise ApiError("ERR_LOAD_MAP_EMPTY")

    recipe = db.recipes.get(cycle["recipe_id"])
    indicators = indicators_of_cycle(cycle["id"])
    min_zone = sum(1 for i in indicators
                   if i["indicator_type"] == "DOSIMETER" and i["placement_zone"] == "MIN_DOSE")
    routine = sum(1 for i in indicators
                  if i["indicator_type"] == "DOSIMETER" and i["placement_zone"] == "ROUTINE")
    biological = sum(1 for i in indicators if i["indicator_type"] == "BIOLOGICAL")

    # priority 84 - indicator placement
    if min_zone < recipe["required_min_zone_dosimeters"] \
            or routine < recipe["required_routine_dosimeters"] \
            or biological < recipe["required_biological_indicators"]:
        raise ApiError("ERR_INDICATOR_PLACEMENT_INCOMPLETE")

    # priority 86 - density band, lower inclusive and upper exclusive
    density = calc.dec(cycle["load_density_g_per_cm3"])
    if density < calc.dec(recipe["density_min_g_per_cm3"]) \
            or density >= calc.dec(recipe["density_max_g_per_cm3"]):
        raise ApiError("ERR_LOAD_DENSITY_OUT_OF_BAND")

    cycle["status"] = "READY"
    touch(cycle)
    return response.object_response(cycle)


# =====================================================================
# Start, complete and abort (PRD 3.6)
# =====================================================================
@bp.post("/sterilization/cycles/<cycle_id>/start")
def start_cycle(cycle_id):
    user_id, _role = authenticate("CycleOperator")
    cycle = fetch("cycles", cycle_id)

    # priority 45
    if cycle["status"] != "READY":
        raise ApiError("ERR_CYCLE_NOT_READY")

    chamber = db.chambers.get(cycle["chamber_id"])
    permit = db.permits.get(chamber["permit_id"]) if chamber else None

    # priority 65
    if chamber is None or chamber["status"] != "AVAILABLE":
        raise ApiError("ERR_CHAMBER_UNAVAILABLE")

    # priority 68
    if permit is None or permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE")

    if chamber["modality"] == "ETO":
        abated = calc.abated_mass(cycle["raw_eto_charge_kg"],
                                  chamber["abatement_efficiency_pct"])
        prospective = calc.prospective_ytd(permit["consumed_kg_ytd"], abated)
        # priority 95 - landing exactly on the allowance is accepted
        if prospective > calc.dec(permit["annual_allowance_kg"]):
            raise ApiError("ERR_PERMIT_ALLOWANCE_EXCEEDED")
        rate = calc.emission_rate(prospective)
        fee = calc.emission_fee(abated, rate)
        permit["consumed_kg_ytd"] = prospective
        permit["total_emission_fee_usd"] = calc.round_money(
            calc.dec(permit["total_emission_fee_usd"]) + fee)
        cycle["abated_eto_kg"] = abated
        cycle["emission_fee_usd"] = fee
        if permit["status"] == "ACTIVE" \
                and prospective >= calc.dec(permit["annual_allowance_kg"]):
            permit["status"] = "SUSPENDED"
        touch(permit)

    cycle["operator_user_id"] = user_id
    cycle["status"] = "RUNNING"
    touch(cycle)

    for lot in lots_of_cycle(cycle["id"]):
        if lot["status"] == "STAGED":
            lot["status"] = "IN_PROCESS"
            touch(lot)
            recompute_open_lot_count(lot["customer_id"])

    return response.object_response(cycle)


@bp.post("/sterilization/cycles/<cycle_id>/complete")
def complete_cycle(cycle_id):
    authenticate("CycleOperator")
    cycle = fetch("cycles", cycle_id)
    if cycle["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", "Only a RUNNING cycle may be completed.")

    chamber = db.chambers.get(cycle["chamber_id"])
    cycle["status"] = "COMPLETED"
    touch(cycle)

    for lot in lots_of_cycle(cycle["id"]):
        changed = False
        if lot["status"] == "IN_PROCESS":
            lot["status"] = "PROCESSED"
            changed = True
        product = db.products.get(lot["product_id"])
        if chamber is not None and chamber["modality"] == "ETO" \
                and product is not None and product["requires_aeration"] \
                and lot["residual_status"] == "NOT_APPLICABLE":
            lot["residual_status"] = "PENDING_AERATION"
            changed = True
        if changed:
            touch(lot)
            recompute_open_lot_count(lot["customer_id"])

    return response.object_response(cycle)


@bp.post("/sterilization/cycles/<cycle_id>/abort")
def abort_cycle(cycle_id):
    authenticate("CycleOperator")
    body = V.body()
    V.req_string(body, "reason", 1, None)
    cycle = fetch("cycles", cycle_id)

    if cycle["status"] not in ("PLANNED", "LOADING", "READY", "RUNNING"):
        raise ApiError("ERR_INVALID_STATE", "This cycle can no longer be aborted.")

    was_running = cycle["status"] == "RUNNING"
    chamber = db.chambers.get(cycle["chamber_id"])
    permit = db.permits.get(chamber["permit_id"]) if chamber else None

    if was_running and chamber is not None and chamber["modality"] == "ETO" \
            and permit is not None:
        permit["consumed_kg_ytd"] = calc.round_mass(
            calc.dec(permit["consumed_kg_ytd"]) - calc.dec(cycle["abated_eto_kg"]))
        permit["total_emission_fee_usd"] = calc.round_money(
            calc.dec(permit["total_emission_fee_usd"]) - calc.dec(cycle["emission_fee_usd"]))
        if permit["status"] == "SUSPENDED" \
                and calc.dec(permit["consumed_kg_ytd"]) < calc.dec(permit["annual_allowance_kg"]):
            permit["status"] = "ACTIVE"
        touch(permit)
        cycle["abated_eto_kg"] = Decimal("0.000")
        cycle["emission_fee_usd"] = Decimal("0.00")

    affected_lots = []
    for position in positions_of_cycle(cycle["id"]):
        lot = db.lots.get(position["lot_id"])
        delete_position_row(position, cycle)
        if lot is not None and lot["id"] not in [l["id"] for l in affected_lots]:
            affected_lots.append(lot)

    cycle["loaded_pallet_count"] = 0
    cycle["load_density_g_per_cm3"] = Decimal("0.0000")
    cycle["status"] = "CANCELLED"
    touch(cycle)

    for lot in affected_lots:
        settle_lot_after_removal(lot, running_abort=was_running)

    return response.object_response(cycle)


# =====================================================================
# Dosimetry review (PRD 3.7)
# =====================================================================
@bp.post("/sterilization/cycles/<cycle_id>/dosimetry-close")
def close_dosimetry(cycle_id):
    user_id, _role = authenticate("DosimetryAnalyst")
    cycle = fetch("cycles", cycle_id)

    if cycle["status"] != "DOSIMETRY_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       "Dosimetry may only be closed from DOSIMETRY_REVIEW.")

    recipe = db.recipes.get(cycle["recipe_id"])
    indicators = indicators_of_cycle(cycle["id"])

    # priority 93 - dosimetry completeness
    for indicator in indicators:
        if indicator["reading_status"] != "READ":
            raise ApiError("ERR_DOSIMETRY_INCOMPLETE",
                           "Indicator %s is still UNREAD." % indicator["serial_code"])

    read_dosimeters = [i for i in indicators
                       if i["indicator_type"] == "DOSIMETER" and i["reading_status"] == "READ"]
    if not read_dosimeters:
        raise ApiError("ERR_DOSIMETRY_INCOMPLETE", "No dosimeter readings on this cycle.")

    if recipe["dose_basis"] == "ROUTINE_MEAN":
        subset = [i for i in read_dosimeters if i["placement_zone"] == "ROUTINE"]
    else:
        subset = [i for i in read_dosimeters if i["placement_zone"] == "MIN_DOSE"]
    if not subset:
        raise ApiError("ERR_DOSIMETRY_INCOMPLETE",
                       "The %s dosimeter subset is empty." % recipe["dose_basis"])

    max_observed = calc.round_dose(max(calc.dec(i["measured_dose_kgy"]) for i in read_dosimeters))
    if recipe["dose_basis"] == "ROUTINE_MEAN":
        total = sum((calc.dec(i["measured_dose_kgy"]) for i in subset), calc.D0)
        delivered = calc.round_dose(total / Decimal(len(subset)))
    else:
        delivered = calc.round_dose(min(calc.dec(i["measured_dose_kgy"]) for i in subset))

    cycle_lots = lots_of_cycle(cycle["id"])
    ceilings = [calc.dec(db.products[l["product_id"]]["max_allowed_dose_kgy"])
                for l in cycle_lots if l["product_id"] in db.products]
    product_dose_ceiling = min(ceilings) if ceilings else None

    # dose_conformance_verdict - first matching test wins
    deviation_code = "NONE"
    if any(i["indicator_type"] == "BIOLOGICAL" and i["bi_result"] == "POSITIVE"
           for i in indicators):
        deviation_code = "BI_POSITIVE"
    elif delivered < calc.dec(recipe["min_dose_kgy"]):
        deviation_code = "UNDERDOSE"
    elif max_observed > calc.dec(recipe["max_dose_kgy"]) \
            or (product_dose_ceiling is not None and max_observed > product_dose_ceiling):
        deviation_code = "OVERDOSE"

    cycle["delivered_dose_kgy"] = delivered
    cycle["max_observed_dose_kgy"] = max_observed
    cycle["deviation_code"] = deviation_code
    cycle["dosimetry_closed_by_user_id"] = user_id

    if deviation_code == "NONE":
        cycle["status"] = "DOSE_CONFORMING"
        touch(cycle)
        for lot in cycle_lots:
            changed = False
            if lot["status"] == "PROCESSED":
                lot["status"] = "QUARANTINE"
                lot["quarantine_reason"] = "ROUTINE"
                changed = True
            elif lot["status"] == "QUARANTINE" \
                    and lot["quarantine_reason"] in ("DOSE_DEVIATION", "BI_POSITIVE"):
                lot["quarantine_reason"] = "ROUTINE"
                lot["schedulable"] = True
                changed = True
            lot["cumulative_dose_kgy"] = calc.round_dose(
                calc.dec(lot["cumulative_dose_kgy"]) + delivered)
            touch(lot)
            if changed:
                recompute_open_lot_count(lot["customer_id"])
    else:
        # CASCADE A hop 1
        cycle["status"] = "DOSE_DEVIATION"
        touch(cycle)
        # CASCADE A hop 2
        quarantined = []
        reason = "BI_POSITIVE" if deviation_code == "BI_POSITIVE" else "DOSE_DEVIATION"
        for lot in cycle_lots:
            if lot["status"] == "PROCESSED":
                lot["status"] = "QUARANTINE"
                lot["quarantine_reason"] = reason
                lot["schedulable"] = False
                touch(lot)
                recompute_open_lot_count(lot["customer_id"])
                quarantined.append(lot)
        # CASCADE A hops 3 and 4
        deviation_qualification_cascade(quarantined, cycle["recipe_id"])

    return response.object_response(cycle)
