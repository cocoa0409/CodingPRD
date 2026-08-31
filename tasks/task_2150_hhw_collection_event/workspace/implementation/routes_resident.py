"""Resident endpoints (PRD §3.5)."""

from flask import Blueprint, request

import serializers
from calc import ZERO
from common import list_response
from envelope import ok
from errors import ApiError
from rollups import refresh_world
from store import new_row, set_and_touch, store
from validation import (
    ALL_READ_ROLES,
    authorize,
    body,
    context,
    lookup,
    req_enum,
    req_str,
)

bp = Blueprint("residents", __name__)

ELIGIBILITY_ACTIONS = ["VERIFY", "REINSTATE"]


@bp.post("/hhw/residents")
def create_resident():
    user_id, role = context()
    authorize(role, ["Anonymous", "EligibilityClerk"])
    payload = body()
    program_id = req_str(payload, "program_id")
    full_name = req_str(payload, "full_name")
    street_address = req_str(payload, "street_address")
    claimed = req_str(payload, "claimed_jurisdiction_code")

    program = lookup("program", program_id)

    row = new_row({
        "program_id": program["id"],
        "full_name": full_name,
        "street_address": street_address,
        "claimed_jurisdiction_code": claimed,
        "eligibility_status": "PENDING_VERIFICATION",
        "verified_jurisdiction_code": None,
        "annual_quantity_reserved_kg": ZERO,
        "annual_quantity_settled_kg": ZERO,
        "no_show_strike_count": 0,
        "completed_visit_count": 0,
    })
    store.residents[row["id"]] = row
    refresh_world()
    return ok(serializers.resident(row), 201)


@bp.get("/hhw/residents")
def list_residents():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "eligibility_status": request.args.get("eligibility_status"),
    }
    return list_response(request.args, list(store.residents.values()),
                         serializers.resident, filters)


@bp.get("/hhw/residents/<resident_id>")
def read_resident(resident_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.resident(lookup("resident", resident_id)))


@bp.post("/hhw/residents/<resident_id>/eligibility-actions")
def eligibility_action(resident_id):
    user_id, role = context()
    authorize(role, ["EligibilityClerk"])
    payload = body()
    action = req_enum(payload, "action", ELIGIBILITY_ACTIONS)
    verified_code = None
    if action == "VERIFY":
        verified_code = req_str(payload, "verified_jurisdiction_code")

    resident = lookup("resident", resident_id)
    program = store.programs.get(resident["program_id"])

    if action == "VERIFY":
        if resident["eligibility_status"] not in ("PENDING_VERIFICATION",
                                                  "INELIGIBLE_OUT_OF_JURISDICTION"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        codes = program["eligible_jurisdiction_codes"] if program else []
        if verified_code in codes:
            new_status = "ELIGIBLE"
        else:
            new_status = "INELIGIBLE_OUT_OF_JURISDICTION"
        set_and_touch(resident, eligibility_status=new_status,
                      verified_jurisdiction_code=verified_code)
    else:
        if resident["eligibility_status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        # no_show_strike_count is NOT reset — it stays a count over NO_SHOW rows.
        set_and_touch(resident, eligibility_status="ELIGIBLE")

    refresh_world()
    return ok(serializers.resident(resident))
