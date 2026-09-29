"""Vessels and harvest authorizations: the widest gate in the API, the area
snapshot, activation and closing (PRD 3.7).
"""

from datetime import timedelta

from flask import Blueprint

import calc
import serializers as ser
from core import (
    AUTHORIZATION_STATUSES,
    DEFAULT_VESSEL_CAPACITY,
    MAX_AUTHORIZATION_WINDOW_HOURS,
    REFRIGERATION_TYPES,
    ROLE_AUTHORITY,
    ROLE_OPERATOR,
    apply_changes,
    authenticate,
    at_or_after_today,
    body_ref,
    clock,
    db,
    envelope_array,
    envelope_object,
    f_instant,
    f_int,
    f_enum,
    f_str,
    get_authorization,
    get_dealer,
    get_lease,
    get_unit,
    get_vessel,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_str,
    require_lease_owner,
    sort_default,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("harvest", __name__)

HARVEST_READ_ROLES = [ROLE_AUTHORITY, ROLE_OPERATOR]
HARVESTABLE_CLASSIFICATIONS = ("APPROVED", "CONDITIONALLY_APPROVED")
DIRECT_RECEIPT_CATEGORIES = ("SHELLSTOCK_SHIPPER", "SHUCKER_PACKER")


# --------------------------------------------------------------------------
# Vessels
# --------------------------------------------------------------------------
@bp.route("/harvest-vessels", methods=["POST"])
def register_vessel():
    authenticate([ROLE_OPERATOR])
    body = json_body()
    name = f_str(body, "name")
    registration_no = f_str(body, "registration_no")
    refrigeration_type = f_enum(body, "refrigeration_type", REFRIGERATION_TYPES)
    capacity = f_int(
        body,
        "concurrent_authorization_capacity",
        required=False,
        default=DEFAULT_VESSEL_CAPACITY,
        minimum=1,
    )
    vessel = {
        "name": name,
        "registration_no": registration_no,
        "refrigeration_type": refrigeration_type,
        "concurrent_authorization_capacity": capacity,
        "active_authorization_count": 0,
    }
    stamp_new(vessel)
    db.vessels[vessel["id"]] = vessel
    return envelope_object(ser.vessel(vessel)), 201


@bp.route("/harvest-vessels/<vessel_id>", methods=["GET"])
def read_vessel(vessel_id):
    authenticate(HARVEST_READ_ROLES)
    vessel = get_vessel(vessel_id)
    return envelope_object(ser.vessel(vessel)), 200


# --------------------------------------------------------------------------
# Issuing an authorization
# --------------------------------------------------------------------------
@bp.route("/harvest-authorizations", methods=["POST"])
def issue_authorization():
    authenticate([ROLE_OPERATOR])
    body = json_body()
    # Rung 3 — body references in narrative order.
    lease = get_lease(body_ref(body, "lease_id", "ERR_LEASE_NOT_FOUND"))
    unit = get_unit(body_ref(body, "growout_unit_id", "ERR_GROWOUT_UNIT_NOT_FOUND"))
    vessel = get_vessel(body_ref(body, "vessel_id", "ERR_VESSEL_NOT_FOUND"))
    dealer = get_dealer(body_ref(body, "dealer_id", "ERR_DEALER_NOT_FOUND"))
    # Rung 4 — ownership.
    require_lease_owner(lease)
    # Rung 5 — request shape.
    window_start = f_instant(body, "window_start")
    window_end = f_instant(body, "window_end")
    projected_bushels = f_int(body, "projected_bushels", minimum=1)

    # Rung 7 — lease state, then deployment state.
    if lease["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    if unit["status"] != "DEPLOYED":
        raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")
    # Rung 8 — the sanitary gates.
    area = db.growing_areas.get(lease["growing_area_id"])
    if area is not None:
        if area["classification"] not in HARVESTABLE_CLASSIFICATIONS:
            raise ApiError("ERR_AREA_CLASSIFICATION_NOT_HARVESTABLE")
        if area["harvest_status"] != "OPEN":
            raise ApiError("ERR_AREA_HARVEST_CLOSED")
    # Rung 10 — the window is intent, so only its own coherence is judged.
    if window_end <= window_start:
        raise ApiError("ERR_AUTHORIZATION_WINDOW_INVALID")
    if (window_end - window_start) > timedelta(hours=MAX_AUTHORIZATION_WINDOW_HOURS):
        raise ApiError("ERR_AUTHORIZATION_WINDOW_INVALID")
    # Rung 12 — vessel concurrency, deployment exclusivity, husbandry currency.
    load = calc.vessel_load(vessel["id"], window_start, window_end)
    if (load + 1) > vessel["concurrent_authorization_capacity"]:
        raise ApiError("ERR_VESSEL_CAPACITY_CONFLICT")
    for existing in calc.unit_authorizations(unit["id"]):
        if existing["status"] in ("ISSUED", "ACTIVE"):
            raise ApiError("ERR_UNIT_ALREADY_AUTHORIZED")
    if not calc.inspection_current(unit):
        raise ApiError("ERR_HUSBANDRY_LAPSED")
    if not calc.predator_control_current(unit):
        raise ApiError("ERR_PREDATOR_CONTROL_LAPSED")
    # Rung 13 — dealer and deployment referential coherence.
    if dealer["certification_category"] not in DIRECT_RECEIPT_CATEGORIES:
        raise ApiError("ERR_DEALER_CATEGORY_NOT_PERMITTED")
    if not at_or_after_today(dealer["certified_through"]):
        raise ApiError("ERR_DEALER_CERTIFICATION_EXPIRED")
    if unit["lease_id"] != lease["id"]:
        raise ApiError("ERR_UNIT_LEASE_MISMATCH")
    if dealer["listing_status"] == "SUSPENDED":
        raise ApiError("ERR_DEALER_SUSPENDED")
    # Rung 14 — fiscal standing, last of all.
    if not at_or_after_today(lease["rent_paid_through_date"]):
        raise ApiError("ERR_LEASE_RENT_DELINQUENT")

    authorization = {
        "lease_id": lease["id"],
        "growout_unit_id": unit["id"],
        "vessel_id": vessel["id"],
        "dealer_id": dealer["id"],
        # The snapshot every area-closure cascade matches on (PRD 3.7).
        "growing_area_id": lease["growing_area_id"],
        "window_start": window_start,
        "window_end": window_end,
        "projected_bushels": projected_bushels,
        "harvested_bushels": 0,
        "status": "ISSUED",
        "harvest_start_at": None,
        "harvest_end_at": None,
        "void_reason": None,
    }
    stamp_new(authorization)
    db.authorizations[authorization["id"]] = authorization
    apply_changes(
        vessel,
        {"active_authorization_count": vessel["active_authorization_count"] + 1},
    )
    if area is not None:
        calc.recompute_open_authorization_count(area)
    return envelope_object(ser.authorization(authorization)), 201


@bp.route("/harvest-authorizations/<authorization_id>", methods=["GET"])
def read_authorization(authorization_id):
    authenticate(HARVEST_READ_ROLES)
    authorization = get_authorization(authorization_id)
    return envelope_object(ser.authorization(authorization)), 200


@bp.route("/harvest-authorizations", methods=["GET"])
def list_authorizations():
    authenticate(HARVEST_READ_ROLES)
    limit, offset = pagination()
    lease_id = q_str("lease_id")
    growout_unit_id = q_str("growout_unit_id")
    vessel_id = q_str("vessel_id")
    dealer_id = q_str("dealer_id")
    status = q_enum("status", AUTHORIZATION_STATUSES)
    rows = []
    for authorization in db.authorizations.values():
        if lease_id is not None and authorization["lease_id"] != lease_id:
            continue
        if (
            growout_unit_id is not None
            and authorization["growout_unit_id"] != growout_unit_id
        ):
            continue
        if vessel_id is not None and authorization["vessel_id"] != vessel_id:
            continue
        if dealer_id is not None and authorization["dealer_id"] != dealer_id:
            continue
        if status is not None and authorization["status"] != status:
            continue
        rows.append(authorization)
    rows = sort_default(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.authorization(r) for r in page], limit, offset, total
    ), 200


# --------------------------------------------------------------------------
# Activation and closing
# --------------------------------------------------------------------------
@bp.route("/harvest-authorizations/<authorization_id>/activate", methods=["POST"])
def activate_authorization(authorization_id):
    authenticate([ROLE_OPERATOR])
    authorization = get_authorization(authorization_id)
    lease = db.leases.get(authorization["lease_id"])
    if lease is not None:
        require_lease_owner(lease)
    json_body()

    # Rung 7 — the authorization's own gate, then the deployment's.
    if authorization["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE")
    unit = db.growout_units.get(authorization["growout_unit_id"])
    if unit is None or unit["status"] != "DEPLOYED":
        raise ApiError("ERR_INVALID_GROWOUT_UNIT_STATE")
    # Rung 8 — the sanitary gates are re-checked, because conditions move.
    area = db.growing_areas.get(authorization["growing_area_id"])
    if area is not None:
        if area["classification"] not in HARVESTABLE_CLASSIFICATIONS:
            raise ApiError("ERR_AREA_CLASSIFICATION_NOT_HARVESTABLE")
        if area["harvest_status"] != "OPEN":
            raise ApiError("ERR_AREA_HARVEST_CLOSED")
    # Rung 10 — the logical clock must sit inside the half-open window.
    moment = clock.now()
    if not (
        authorization["window_start"] <= moment < authorization["window_end"]
    ):
        raise ApiError("ERR_OUTSIDE_AUTHORIZATION_WINDOW")

    apply_changes(
        authorization, {"status": "ACTIVE", "harvest_start_at": moment}
    )
    apply_changes(unit, {"status": "HARVESTING"})
    return envelope_object(ser.authorization(authorization)), 200


@bp.route("/harvest-authorizations/<authorization_id>/close", methods=["POST"])
def close_authorization(authorization_id):
    authenticate([ROLE_OPERATOR])
    authorization = get_authorization(authorization_id)
    lease = db.leases.get(authorization["lease_id"])
    if lease is not None:
        require_lease_owner(lease)
    json_body()

    # Rung 7 — only an active authorization closes.
    if authorization["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE")

    apply_changes(
        authorization, {"status": "CLOSED", "harvest_end_at": clock.now()}
    )
    unit = db.growout_units.get(authorization["growout_unit_id"])
    if unit is not None and unit["status"] == "HARVESTING":
        apply_changes(unit, {"status": "DEPLOYED"})
    vessel = db.vessels.get(authorization["vessel_id"])
    if vessel is not None:
        apply_changes(
            vessel,
            {"active_authorization_count": vessel["active_authorization_count"] - 1},
        )
    area = db.growing_areas.get(authorization["growing_area_id"])
    if area is not None:
        calc.recompute_open_authorization_count(area)
    return envelope_object(ser.authorization(authorization)), 200
