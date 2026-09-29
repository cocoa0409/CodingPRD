"""Grow-out gear: deployment with its heavily ordered guards, plot occupancy
and the fallow buffer, husbandry journals, retrieval and voiding (PRD 3.6).
"""

from datetime import timedelta

from flask import Blueprint

import calc
import serializers as ser
from core import (
    CONTROL_METHODS,
    FALLOW_DAYS,
    GEAR_TYPES,
    GROWOUT_STATUSES,
    LOG_TYPES,
    PREDATOR_SPECIES,
    ROLE_AUTHORITY,
    ROLE_OPERATOR,
    acting_user,
    apply_changes,
    authenticate,
    body_ref,
    check_not_future_date,
    check_not_future_instant,
    db,
    envelope_array,
    envelope_object,
    f_date,
    f_enum,
    f_instant,
    f_int,
    f_str,
    get_lease,
    get_seed_lot,
    get_unit,
    invalid,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_str,
    require_lease_owner,
    sort_default,
    sort_journal,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("growout", __name__)

GROWOUT_READ_ROLES = [ROLE_AUTHORITY, ROLE_OPERATOR]
PLANTABLE_STATUSES = ("READY_FOR_PLANTING", "PLANTED")


@bp.route("/growout-units", methods=["POST"])
def deploy_gear():
    authenticate([ROLE_OPERATOR])
    body = json_body()
    # Rung 3 — body references in narrative order.
    lease = get_lease(body_ref(body, "lease_id", "ERR_LEASE_NOT_FOUND"))
    seed_lot = get_seed_lot(body_ref(body, "seed_lot_id", "ERR_SEED_LOT_NOT_FOUND"))
    # Rung 4 — ownership.
    require_lease_owner(lease)
    # Rung 5 — request shape.
    plot_code = f_str(body, "plot_code")
    gear_type = f_enum(body, "gear_type", GEAR_TYPES)
    gear_units = f_int(body, "gear_units", minimum=1)
    seed_count_planted = f_int(body, "seed_count_planted", minimum=1)
    deployed_on = f_date(body, "deployed_on")
    planned_retrieval_on = f_date(body, "planned_retrieval_on")

    # Rung 7 — lease state.
    if lease["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    # Rung 8 — the area must not be prohibited.
    area = db.growing_areas.get(lease["growing_area_id"])
    if area is not None and area["classification"] == "PROHIBITED":
        raise ApiError("ERR_AREA_PROHIBITED")
    # Rung 9 — deployment referential coherence, in the declared order.
    if plot_code not in lease["plot_codes"]:
        raise ApiError("ERR_PLOT_NOT_IN_LEASE")
    if gear_type not in lease["gear_types_permitted"]:
        raise ApiError("ERR_GEAR_TYPE_NOT_PERMITTED")
    if seed_lot["lease_id"] != lease["id"]:
        raise ApiError("ERR_SEED_LOT_LEASE_MISMATCH")
    # Rung 10 — nothing future-dated, then the window ordering (PRD 2.7).
    check_not_future_date(deployed_on)
    if planned_retrieval_on <= deployed_on:
        raise ApiError("ERR_INVALID_DEPLOYMENT_WINDOW")
    # Rung 11 — the seed must be plantable.
    if seed_lot["status"] not in PLANTABLE_STATUSES:
        raise ApiError("ERR_SEED_LOT_NOT_PLANTABLE")

    # Rung 12 — occupancy, then the fallow buffer, then capacity, then seed.
    occupants = calc.plot_occupants(lease["id"], plot_code)
    for unit in occupants:
        effective_end = calc.unit_effective_end(unit)
        if effective_end is None:
            continue
        if unit["deployed_on"] < planned_retrieval_on and deployed_on < effective_end:
            raise ApiError("ERR_PLOT_OCCUPIED")
    for unit in occupants:
        effective_end = calc.unit_effective_end(unit)
        if effective_end is None:
            continue
        if deployed_on < effective_end + timedelta(days=FALLOW_DAYS):
            raise ApiError("ERR_PLOT_FALLOW_CONFLICT")
    if lease["deployed_gear_units"] + gear_units > lease["authorized_gear_units"]:
        raise ApiError("ERR_LEASE_GEAR_CAPACITY_EXCEEDED")
    if seed_count_planted > seed_lot["unallocated_seed_count"]:
        raise ApiError("ERR_SEED_ALLOCATION_EXCEEDED")

    unit = {
        "lease_id": lease["id"],
        "seed_lot_id": seed_lot["id"],
        "plot_code": plot_code,
        "gear_type": gear_type,
        "gear_units": gear_units,
        "seed_count_planted": seed_count_planted,
        "deployed_on": deployed_on,
        "planned_retrieval_on": planned_retrieval_on,
        "status": "DEPLOYED",
        "retrieved_on": None,
        "void_reason": None,
        "last_inspection_at": None,
        "last_predator_control_at": None,
        "mortality_count_total": 0,
    }
    stamp_new(unit)
    db.growout_units[unit["id"]] = unit
    calc.recompute_lease_gear(lease)
    calc.recompute_seed_allocation(seed_lot)
    return envelope_object(ser.growout_unit(unit)), 201


@bp.route("/growout-units/<unit_id>", methods=["GET"])
def read_growout_unit(unit_id):
    authenticate(GROWOUT_READ_ROLES)
    unit = get_unit(unit_id)
    return envelope_object(ser.growout_unit(unit)), 200


@bp.route("/growout-units", methods=["GET"])
def list_growout_units():
    authenticate(GROWOUT_READ_ROLES)
    limit, offset = pagination()
    lease_id = q_str("lease_id")
    seed_lot_id = q_str("seed_lot_id")
    plot_code = q_str("plot_code")
    status = q_enum("status", GROWOUT_STATUSES)
    rows = []
    for unit in db.growout_units.values():
        if lease_id is not None and unit["lease_id"] != lease_id:
            continue
        if seed_lot_id is not None and unit["seed_lot_id"] != seed_lot_id:
            continue
        if plot_code is not None and unit["plot_code"] != plot_code:
            continue
        if status is not None and unit["status"] != status:
            continue
        rows.append(unit)
    rows = sort_default(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.growout_unit(r) for r in page], limit, offset, total
    ), 200


# --------------------------------------------------------------------------
# Husbandry logs
# --------------------------------------------------------------------------
@bp.route("/growout-units/<unit_id>/husbandry-logs", methods=["POST"])
def record_husbandry_log(unit_id):
    authenticate([ROLE_OPERATOR])
    unit = get_unit(unit_id)
    lease = db.leases.get(unit["lease_id"])
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    log_type = f_enum(body, "log_type", LOG_TYPES)
    performed_at = f_instant(body, "performed_at")
    predator_species = f_enum(
        body, "predator_species", PREDATOR_SPECIES, required=False, default=None
    )
    control_method = f_enum(
        body, "control_method", CONTROL_METHODS, required=False, default=None
    )
    mortality_count = f_int(
        body, "mortality_count", required=False, default=0, minimum=0
    )
    notes = f_str(body, "notes", required=False, default=None, allow_blank=True)
    if log_type == "PREDATOR_CONTROL":
        if predator_species is None:
            raise invalid(
                "Field 'predator_species' is required for a predator-control log."
            )
        if control_method is None:
            raise invalid(
                "Field 'control_method' is required for a predator-control log."
            )
    else:
        predator_species = None
        control_method = None

    # Rung 7 — husbandry is only recorded on gear that is in the water.
    if unit["status"] not in ("DEPLOYED", "HARVESTING"):
        raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")
    # Rung 10 — nothing future-dated.
    check_not_future_instant(performed_at)

    entry = {
        "growout_unit_id": unit["id"],
        "log_type": log_type,
        "performed_at": performed_at,
        "performed_by_user_id": acting_user(),
        "predator_species": predator_species,
        "control_method": control_method,
        "mortality_count": mortality_count,
        "notes": notes,
    }
    stamp_new(entry, versioned=False)
    db.husbandry_logs[entry["id"]] = entry
    calc.recompute_unit_husbandry(unit)
    return envelope_object(ser.husbandry_log(entry)), 201


@bp.route("/growout-units/<unit_id>/husbandry-logs", methods=["GET"])
def list_husbandry_logs(unit_id):
    authenticate(GROWOUT_READ_ROLES)
    unit = get_unit(unit_id)
    limit, offset = pagination()
    log_type = q_enum("log_type", LOG_TYPES)
    rows = []
    for entry in calc.unit_logs(unit["id"]):
        if log_type is not None and entry["log_type"] != log_type:
            continue
        rows.append(entry)
    rows = sort_journal(rows, "performed_at", True)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.husbandry_log(r) for r in page], limit, offset, total
    ), 200


# --------------------------------------------------------------------------
# Retrieval and voiding
# --------------------------------------------------------------------------
@bp.route("/growout-units/<unit_id>/retrieve", methods=["POST"])
def retrieve_gear(unit_id):
    authenticate([ROLE_OPERATOR])
    unit = get_unit(unit_id)
    lease = db.leases.get(unit["lease_id"])
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    retrieved_on = f_date(body, "retrieved_on")

    # Rung 7 — only deployed gear is retrievable, and only when it is free.
    if unit["status"] != "DEPLOYED":
        raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")
    for auth in calc.unit_authorizations(unit["id"]):
        if auth["status"] in ("ISSUED", "ACTIVE"):
            raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")
    # Rung 10 — nothing future-dated.
    check_not_future_date(retrieved_on)

    apply_changes(unit, {"status": "RETRIEVED", "retrieved_on": retrieved_on})
    # Retrieval releases gear capacity but deliberately never gives seed back.
    if lease is not None:
        calc.recompute_lease_gear(lease)
    return envelope_object(ser.growout_unit(unit)), 200


@bp.route("/growout-units/<unit_id>/void", methods=["POST"])
def void_gear(unit_id):
    authenticate([ROLE_OPERATOR])
    unit = get_unit(unit_id)
    lease = db.leases.get(unit["lease_id"])
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    f_str(body, "void_note", required=False, default=None)

    # Rung 7 — a void is far more restrictive than a retrieval.
    if unit["status"] != "DEPLOYED":
        raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")
    for auth in calc.unit_authorizations(unit["id"]):
        if auth["status"] in ("ISSUED", "ACTIVE", "CLOSED"):
            raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")
        if calc.authorization_lots(auth["id"]):
            raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")

    apply_changes(
        unit, {"status": "VOIDED", "void_reason": "OPERATOR_CORRECTION"}
    )
    if lease is not None:
        calc.recompute_lease_gear(lease)
    seed_lot = db.seed_lots.get(unit["seed_lot_id"])
    if seed_lot is not None:
        calc.recompute_seed_allocation(seed_lot)
    return envelope_object(ser.growout_unit(unit)), 200
