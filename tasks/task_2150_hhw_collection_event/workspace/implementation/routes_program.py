"""Program endpoints (PRD §3.1, §3.9)."""

from flask import Blueprint

import serializers
from calc import ZERO
from envelope import ok
from errors import ApiError
from rollups import cost_summary, effective_posture, refresh_world
from store import new_row, store, touch
from validation import (
    ALL_READ_ROLES,
    authorize,
    body,
    context,
    lookup,
    opt_enum,
    parse_iso,
    req_int,
    req_str,
    req_str_array,
)

bp = Blueprint("programs", __name__)


@bp.post("/hhw/programs")
def create_program():
    user_id, role = context()
    authorize(role, ["ProgramAdmin"])
    payload = body()
    name = req_str(payload, "name")
    fiscal_year = req_int(payload, "fiscal_year", minimum=2020, maximum=2100)
    budget_cents = req_int(payload, "budget_cents", minimum=0)
    ceiling = req_int(payload, "cost_per_participant_ceiling_cents", minimum=1)
    hourly = req_int(payload, "staff_hourly_rate_cents", minimum=1)
    codes = req_str_array(payload, "eligible_jurisdiction_codes")

    row = new_row({
        "name": name,
        "fiscal_year": fiscal_year,
        "budget_cents": budget_cents,
        "cost_per_participant_ceiling_cents": ceiling,
        "staff_hourly_rate_cents": hourly,
        "eligible_jurisdiction_codes": list(codes),
        "posture": "OPEN",
        "posture_override": "NONE",
        "posture_override_expires_utc": None,
        "budget_encumbered_cents": 0,
        "budget_in_transit_cents": 0,
        "budget_spent_cents": 0,
        "open_containment_deficiency_count": 0,
        "budget_alert_count": 0,
        "participant_count_ytd": 0,
        "tonnage_ytd_kg": ZERO,
    })
    store.programs[row["id"]] = row
    # Seed the stored posture from the live derivation so that the freshly
    # created row keeps version = 1 and budget_alert_count = 0.
    row["posture"] = effective_posture(row)
    refresh_world()
    return ok(serializers.program(row), 201)


@bp.get("/hhw/programs/<program_id>")
def read_program(program_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    program = lookup("program", program_id)
    return ok(serializers.program(program))


@bp.get("/hhw/programs/<program_id>/cost-summary")
def program_cost_summary(program_id):
    user_id, role = context()
    authorize(role, ["ProgramAdmin", "EventCoordinator"])
    program = lookup("program", program_id)
    return ok(cost_summary(program))


@bp.post("/hhw/programs/<program_id>/posture-override")
def posture_override(program_id):
    user_id, role = context()
    authorize(role, ["ProgramAdmin"])
    payload = body()
    override = opt_enum(payload, "posture_override", ["NONE", "OPEN"])
    if override is None:
        raise ApiError("ERR_INVALID_REQUEST", "posture_override is required.")
    expires_raw = payload.get("posture_override_expires_utc")
    if expires_raw is not None:
        if not isinstance(expires_raw, str):
            raise ApiError("ERR_INVALID_REQUEST",
                           "posture_override_expires_utc must be a string.")
        parse_iso(expires_raw, "posture_override_expires_utc")
    program = lookup("program", program_id)

    if override == "NONE":
        expires_raw = None
    program["posture_override"] = override
    program["posture_override_expires_utc"] = expires_raw
    touch(program)
    refresh_world()
    return ok(serializers.program(program))
