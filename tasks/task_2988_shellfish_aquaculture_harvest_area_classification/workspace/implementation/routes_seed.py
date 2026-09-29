"""Hatcheries and seed lots: certificates, the three sanitary gates, pathogen
screening with its rejection cascade, and nursery grow-out (PRD 3.5).
"""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import serializers as ser
from cascades import seed_rejection_cascade
from core import (
    DISEASE_CERT_MAX_AGE_DAYS,
    MIN_NURSERY_DAYS,
    NURSERY_SYSTEMS,
    ROLE_AUTHORITY,
    ROLE_HATCHERY,
    ROLE_OPERATOR,
    SEED_LOT_STATUSES,
    SPECIES,
    SURVIVAL_FLOOR_PCT,
    acting_user,
    apply_changes,
    authenticate,
    body_ref,
    check_not_future_date,
    clock,
    db,
    envelope_array,
    envelope_object,
    f_date,
    f_enum,
    f_int,
    f_str,
    f_str_list,
    get_hatchery,
    get_lease,
    get_seed_lot,
    invalid,
    json_body,
    pagination,
    paginate,
    q,
    q_enum,
    q_str,
    require_lease_owner,
    sort_default,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("seed", __name__)

SEED_READ_ROLES = [ROLE_AUTHORITY, ROLE_HATCHERY, ROLE_OPERATOR]


# --------------------------------------------------------------------------
# Hatcheries
# --------------------------------------------------------------------------
@bp.route("/hatcheries", methods=["POST"])
def register_hatchery():
    authenticate([ROLE_AUTHORITY])
    body = json_body()
    name = f_str(body, "name")
    state_code = f_str(body, "state_code", pattern=r"^[A-Z]{2}$", min_len=2, max_len=2)
    certificate_no = f_str(body, "ncsp_certificate_no")
    expires_on = f_date(body, "certificate_expires_on")
    species = f_str_list(
        body, "pathogen_free_species", min_items=1, unique=True, members=SPECIES
    )
    hatchery = {
        "name": name,
        "state_code": state_code,
        "ncsp_certificate_no": certificate_no,
        "certificate_expires_on": expires_on,
        "pathogen_free_species": list(species),
    }
    stamp_new(hatchery)
    db.hatcheries[hatchery["id"]] = hatchery
    return envelope_object(ser.hatchery(hatchery)), 201


@bp.route("/hatcheries/<hatchery_id>", methods=["GET"])
def read_hatchery(hatchery_id):
    authenticate(SEED_READ_ROLES)
    hatchery = get_hatchery(hatchery_id)
    return envelope_object(ser.hatchery(hatchery)), 200


# --------------------------------------------------------------------------
# Seed shipments
# --------------------------------------------------------------------------
@bp.route("/seed-lots", methods=["POST"])
def record_seed_shipment():
    authenticate([ROLE_HATCHERY])
    body = json_body()
    # Rung 3 — body references in the order the narrative introduces them.
    hatchery = get_hatchery(body_ref(body, "hatchery_id", "ERR_HATCHERY_NOT_FOUND"))
    lease = get_lease(body_ref(body, "lease_id", "ERR_LEASE_NOT_FOUND"))
    # Rung 4 — the acting identity IS a hatchery identifier.
    if hatchery["id"] != acting_user():
        raise ApiError("ERR_HATCHERY_OWNERSHIP_VIOLATION")
    # Rung 5 — the rest of the shape.
    species = f_enum(body, "species", SPECIES)
    received = f_int(body, "received_seed_count", minimum=1)
    disease_certificate_no = f_str(body, "disease_certificate_no")
    issued_on = f_date(body, "disease_cert_issued_on")
    shipped_on = f_date(body, "shipped_on")

    # Rung 7 — the destination lease must be approved.
    if lease["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    # Rung 8 — the three sanitary gates, in the declared order.
    if hatchery["certificate_expires_on"] < shipped_on:
        raise ApiError("ERR_HATCHERY_CERTIFICATE_EXPIRED")
    if species not in hatchery["pathogen_free_species"]:
        raise ApiError("ERR_SPECIES_NOT_CERTIFIED")
    if (shipped_on - issued_on) > timedelta(days=DISEASE_CERT_MAX_AGE_DAYS):
        raise ApiError("ERR_DISEASE_CERTIFICATE_STALE")
    # Rung 10 — a shipment cannot have left in the future.
    check_not_future_date(shipped_on)

    seed_lot = {
        "hatchery_id": hatchery["id"],
        "lease_id": lease["id"],
        "species": species,
        "received_seed_count": received,
        "disease_certificate_no": disease_certificate_no,
        "disease_cert_issued_on": issued_on,
        "shipped_on": shipped_on,
        "status": "RECEIVED",
        "screening_result": None,
        "screened_on": None,
        "nursery_started_on": None,
        "nursery_system": None,
        "nursery_completed_on": None,
        "surviving_seed_count": None,
        "survival_rate_pct": None,
        "allocated_seed_count": 0,
        "unallocated_seed_count": 0,
    }
    stamp_new(seed_lot)
    db.seed_lots[seed_lot["id"]] = seed_lot
    return envelope_object(ser.seed_lot(seed_lot)), 201


@bp.route("/seed-lots/<seed_lot_id>", methods=["GET"])
def read_seed_lot(seed_lot_id):
    authenticate(SEED_READ_ROLES)
    seed_lot = get_seed_lot(seed_lot_id)
    return envelope_object(ser.seed_lot(seed_lot)), 200


@bp.route("/seed-lots", methods=["GET"])
def list_seed_lots():
    authenticate(SEED_READ_ROLES)
    limit, offset = pagination()
    hatchery_id = q_str("hatchery_id")
    lease_id = q_str("lease_id")
    status = q_enum("status", SEED_LOT_STATUSES)
    rows = []
    for seed_lot in db.seed_lots.values():
        if hatchery_id is not None and seed_lot["hatchery_id"] != hatchery_id:
            continue
        if lease_id is not None and seed_lot["lease_id"] != lease_id:
            continue
        if status is not None and seed_lot["status"] != status:
            continue
        rows.append(seed_lot)
    rows = sort_default(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array([ser.seed_lot(r) for r in page], limit, offset, total), 200


# --------------------------------------------------------------------------
# Screening (PRD 3.5) — a positive result condemns the lot.
# --------------------------------------------------------------------------
@bp.route("/seed-lots/<seed_lot_id>/screening", methods=["POST"])
def screen_seed_lot(seed_lot_id):
    authenticate([ROLE_AUTHORITY])
    seed_lot = get_seed_lot(seed_lot_id)
    body = json_body()
    result = f_enum(body, "result", ["NEGATIVE", "POSITIVE"])
    screened_on = f_date(body, "screened_on")

    # Rung 7 — only a received lot may be screened.
    if seed_lot["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_SEED_LOT_STATE")
    # Rung 10 — nothing future-dated, then the screening date coherence.
    check_not_future_date(screened_on)
    if screened_on < seed_lot["shipped_on"]:
        raise ApiError("ERR_SCREENING_DATE_INVALID")

    changes = {"screening_result": result, "screened_on": screened_on}
    if result == "NEGATIVE":
        changes["status"] = "SCREENED"
    else:
        changes["status"] = "REJECTED"
    apply_changes(seed_lot, changes)
    if result == "POSITIVE":
        seed_rejection_cascade(seed_lot)
    return envelope_object(ser.seed_lot(seed_lot)), 200


# --------------------------------------------------------------------------
# Nursery grow-out
# --------------------------------------------------------------------------
def _seed_lot_lease(seed_lot):
    return db.leases.get(seed_lot["lease_id"])


@bp.route("/seed-lots/<seed_lot_id>/nursery-start", methods=["POST"])
def start_nursery(seed_lot_id):
    authenticate([ROLE_OPERATOR])
    seed_lot = get_seed_lot(seed_lot_id)
    lease = _seed_lot_lease(seed_lot)
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    started_on = f_date(body, "nursery_started_on")
    nursery_system = f_enum(body, "nursery_system", NURSERY_SYSTEMS)
    # Rung 5 — a nursery cannot start before the seed left the hatchery.
    if started_on < seed_lot["shipped_on"]:
        raise invalid("Field 'nursery_started_on' must be at or after 'shipped_on'.")

    # Rung 7 — only a screened lot may enter the nursery.
    if seed_lot["status"] != "SCREENED":
        raise ApiError("ERR_INVALID_SEED_LOT_STATE")
    # Rung 10 — nothing future-dated.
    check_not_future_date(started_on)

    apply_changes(
        seed_lot,
        {
            "nursery_started_on": started_on,
            "nursery_system": nursery_system,
            "status": "NURSERY",
        },
    )
    return envelope_object(ser.seed_lot(seed_lot)), 200


@bp.route("/seed-lots/<seed_lot_id>/nursery-complete", methods=["POST"])
def complete_nursery(seed_lot_id):
    authenticate([ROLE_OPERATOR])
    seed_lot = get_seed_lot(seed_lot_id)
    lease = _seed_lot_lease(seed_lot)
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    completed_on = f_date(body, "nursery_completed_on")
    surviving = f_int(body, "surviving_seed_count", minimum=0)

    # Rung 7 — only a lot in the nursery may complete grow-out.
    if seed_lot["status"] != "NURSERY":
        raise ApiError("ERR_INVALID_SEED_LOT_STATE")
    # Rung 10 — the nursery period, then the future-dating rule (PRD 2.7).
    started_on = seed_lot["nursery_started_on"]
    if started_on is not None and completed_on < started_on + timedelta(
        days=MIN_NURSERY_DAYS
    ):
        raise ApiError("ERR_NURSERY_PERIOD_TOO_SHORT")
    check_not_future_date(completed_on)

    # Rung 12 — the survival figures must be credible.
    received = seed_lot["received_seed_count"]
    survival_rate = q(Decimal(100 * surviving) / Decimal(received), 2)
    if surviving > received or survival_rate < SURVIVAL_FLOOR_PCT:
        raise ApiError("ERR_SEED_SURVIVAL_BELOW_FLOOR")

    apply_changes(
        seed_lot,
        {
            "nursery_completed_on": completed_on,
            "surviving_seed_count": surviving,
            "survival_rate_pct": survival_rate,
            "allocated_seed_count": 0,
            "unallocated_seed_count": surviving,
            "status": "READY_FOR_PLANTING",
        },
    )
    return envelope_object(ser.seed_lot(seed_lot)), 200
