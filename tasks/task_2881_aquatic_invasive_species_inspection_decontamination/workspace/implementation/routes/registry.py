"""Watercraft registry and interstate reciprocity agreements (PRD 3.3)."""

from flask import Blueprint

import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, fmt_iso, serialize, touch
from validate import (arg_filter, opt_bool, opt_dt, opt_int, opt_ref, opt_str,
                      read_body, req_enum, req_num, req_state_code, req_str,
                      require_auth)

bp = Blueprint("registry", __name__)

VESSEL_TYPES = ("OPEN_HULL", "PONTOON_MULTI_CHAMBER", "BALLASTED_WAKEBOAT",
                "PERSONAL_WATERCRAFT")
AGREEMENT_STATUSES = ("ACTIVE", "SUSPENDED")


@bp.post("/watercraft")
def create_watercraft():
    require_auth(("ProgramAdmin", "Inspector"))
    body = read_body()
    registration_number = req_str(body, "registration_number", max_len=32)
    home_state_code = req_state_code(body, "home_state_code")
    vessel_type = req_enum(body, "vessel_type", VESSEL_TYPES)
    hull_length_ft = req_num(body, "hull_length_ft", exclusive_min=0)
    last_water_body_id = opt_ref(body, "last_water_body_id")
    last_removed_at = opt_dt(body, "last_removed_at")

    if last_water_body_id is not None:
        services.water_body_or_404(last_water_body_id)

    for existing in db.watercraft.values():
        if existing["registration_number"] == registration_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    row = base_row()
    row.update({
        "registration_number": registration_number,
        "home_state_code": home_state_code,
        "vessel_type": vessel_type,
        "hull_length_ft": hull_length_ft,
        "last_water_body_id": last_water_body_id,
        "last_removed_at": fmt_iso(last_removed_at),
        "compliance_strikes": 0,
        "watchlist_status": "CLEAR",
        "mandatory_decon_flag": False,
        "last_decon_verified_at": None,
        "quarantine_hold_until": None,
    })
    db.watercraft[row["id"]] = row
    return created(serialize(row))


@bp.get("/watercraft/<vid>")
def get_watercraft(vid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.watercraft_or_404(vid)))


@bp.get("/watercraft")
def list_watercraft():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "last_water_body_id": arg_filter("last_water_body_id"),
        "watchlist_status": arg_filter("watchlist_status"),
        "vessel_type": arg_filter("vessel_type"),
        "registration_number": arg_filter("registration_number"),
    }
    rows = [r for r in db.watercraft.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/reciprocity-agreements")
def create_agreement():
    require_auth(("ProgramAdmin",))
    body = read_body()
    partner_state_code = req_state_code(body, "partner_state_code")
    accepted_seal_prefix = req_str(body, "accepted_seal_prefix", max_len=8)
    honors_our_seals = opt_bool(body, "honors_our_seals", True)
    max_seal_age_hours = opt_int(body, "max_seal_age_hours", 72, exclusive_min=0)
    fee_waiver = opt_bool(body, "fee_waiver", False)

    for existing in db.agreements.values():
        if existing["partner_state_code"] == partner_state_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    row = base_row()
    row.update({
        "partner_state_code": partner_state_code,
        "honors_our_seals": honors_our_seals,
        "max_seal_age_hours": max_seal_age_hours,
        "accepted_seal_prefix": accepted_seal_prefix,
        "fee_waiver": fee_waiver,
        "status": "ACTIVE",
    })
    db.agreements[row["id"]] = row
    return created(serialize(row))


@bp.get("/reciprocity-agreements/<aid>")
def get_agreement(aid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.agreement_or_404(aid)))


@bp.get("/reciprocity-agreements")
def list_agreements():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "partner_state_code": arg_filter("partner_state_code"),
        "status": arg_filter("status"),
    }
    rows = [r for r in db.agreements.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/reciprocity-agreements/<aid>/status")
def set_agreement_status(aid):
    require_auth(("ProgramAdmin",))
    body = read_body()
    target = req_enum(body, "target_status", AGREEMENT_STATUSES)
    opt_str(body, "reason", min_len=None)

    agreement = services.agreement_or_404(aid)
    agreement["status"] = target
    touch(agreement)
    return ok(serialize(agreement))
