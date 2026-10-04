"""Reload location endpoints and the location state machine."""

from flask import Blueprint, request

import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil
from routes.retailer_agreements import guard_location_owner

bp = Blueprint("reload_locations", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)


def personalised(location):
    core.refresh_location(location)
    out = core.public(core.RELOAD_LOCATION, location)
    out["effective_per_transaction_limit_cents"] = core.effective_per_transaction_limit(location)
    return out


@bp.post("/v1/reload-locations")
def create_location():
    user_id, role = middleware.authenticate(("PlatformAdmin", "ProgramManager"))
    data = rh.body()
    agreement_id = rh.require_str(data, "retailer_agreement_id")
    location_code = rh.require_str(data, "location_code")
    state_code = rh.require_str(data, "state_code")
    register_count = rh.require_int(data, "register_count")
    if register_count < 1:
        raise errors.invalid_request("register_count must be at least 1.")

    agreement = core.ref_agreement(agreement_id)
    if role == "ProgramManager" and agreement["program_id"] != user_id:
        raise errors.unauthorized("The acting program manager does not own this agreement.")
    program = core.get_program(agreement["program_id"])
    core.guard_not_frozen(program)

    for existing in db.reload_locations.values():
        if (
            existing["retailer_agreement_id"] == agreement["id"]
            and existing["location_code"] == location_code
        ):
            raise errors.invalid_request(
                "location_code %r is already used within this agreement." % (location_code,)
            )

    row = core.common_fields()
    row.update(
        {
            "retailer_agreement_id": agreement["id"],
            "location_code": location_code,
            "state_code": state_code,
            "register_count": register_count,
            "location_status": "OPEN",
            "daily_accepted_cents": 0,
            "daily_txn_count": 0,
            "aml_velocity_score": 0.0,
            "is_velocity_breached": False,
            "last_epoch_index": timeutil.current_epoch_index(),
        }
    )
    db.register(db.reload_locations, row)
    return response.ok(personalised(row), 201)


@bp.get("/v1/reload-locations/<location_id>")
def get_location(location_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(personalised(core.get_location(location_id)))


@bp.get("/v1/reload-locations")
def list_locations():
    middleware.authenticate(READ_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.reload_locations,
        retailer_agreement_id=request.args.get("retailer_agreement_id"),
        state_code=request.args.get("state_code"),
    )
    total = len(rows)
    return response.array(
        [personalised(r) for r in rows[offset : offset + limit]], limit, offset, total
    )


# --- state machine ------------------------------------------------------------
@bp.post("/v1/reload-locations/<location_id>/state")
def move_location_state(location_id):
    user_id, role = middleware.authenticate(("ProgramManager",))
    location = core.get_location(location_id)
    guard_location_owner(location, user_id, role)
    program = core.program_of_location(location)

    data = rh.body()
    to_status = rh.require_enum(data, "to_status", ("OPEN", "RESTRICTED", "CLOSED"))
    current = location["location_status"]
    if to_status == current:
        raise errors.invalid_state("The location is already %s." % current)

    if to_status == "RESTRICTED":
        if current != "OPEN":
            raise errors.invalid_state("No transition from %s to RESTRICTED." % current)
        core.guard_not_frozen(program)
        location["location_status"] = "RESTRICTED"
        core.touch(location)
        return response.ok(personalised(location))

    if to_status == "OPEN":
        if current != "RESTRICTED":
            raise errors.invalid_state("No transition from %s to OPEN." % current)
        if program["compliance_posture"] != "OPEN":
            raise errors.program_frozen(
                "A location may only be reopened while the program is OPEN."
            )
        location["location_status"] = "OPEN"
        core.touch(location)
        return response.ok(personalised(location))

    # CLOSED
    if current not in ("OPEN", "RESTRICTED"):
        raise errors.invalid_state("No transition from %s to CLOSED." % current)
    core.guard_not_frozen(program)
    for load in core.location_loads(location):
        if load["load_status"] in ("INITIATED", "FUNDED"):
            raise errors.invalid_state(
                "The location holds a load that is INITIATED or FUNDED."
            )
    location["location_status"] = "CLOSED"
    core.touch(location)
    for window in db.float_windows.values():
        if window["reload_location_id"] == location["id"] and window["window_status"] in (
            "REQUESTED",
            "CONFIRMED",
        ):
            window["window_status"] = "CANCELLED"
            core.touch(window)
    return response.ok(personalised(location))