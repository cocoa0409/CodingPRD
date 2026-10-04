"""Retailer agreement endpoints and the agreement state machine."""

from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core

bp = Blueprint("retailer_agreements", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)


def _guard_agreement_owner(agreement, user_id, role):
    """A ProgramManager may act only on an agreement of its own program, or on
    a location under such an agreement."""
    if role == "ProgramManager" and agreement["program_id"] != user_id:
        raise errors.unauthorized("The acting program manager does not own this agreement.")


def guard_location_owner(location, user_id, role):
    agreement = core.agreement_of_location(location)
    _guard_agreement_owner(agreement, user_id, role)


@bp.post("/v1/retailer-agreements")
def create_agreement():
    user_id, role = middleware.authenticate(("PlatformAdmin", "ProgramManager"))
    data = rh.body()
    program_id = rh.require_str(data, "program_id")
    retailer_name = rh.require_str(data, "retailer_name")

    pct = data.get("fee_split_retailer_pct")
    if pct is None:
        raise errors.invalid_request("fee_split_retailer_pct is required.")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise errors.invalid_request("fee_split_retailer_pct must be a number.")
    pct_dec = Decimal(str(pct))
    if not (Decimal(0) < pct_dec < Decimal(1)):
        raise errors.invalid_request("fee_split_retailer_pct must be strictly between 0 and 1.")

    per_limit = rh.require_int(data, "per_transaction_limit_cents")
    if per_limit < 1:
        raise errors.invalid_request("per_transaction_limit_cents must be at least 1.")
    daily_limit = rh.require_int(data, "daily_location_limit_cents")
    period_hours = rh.optional_int(data, "settlement_period_hours", 24)
    reload_enabled = rh.optional_bool(data, "reload_enabled", True)

    program = core.ref_program(program_id)
    if role == "ProgramManager" and program["id"] != user_id:
        raise errors.unauthorized("The acting program manager does not own this program.")
    core.guard_not_frozen(program)

    row = core.common_fields()
    row.update(
        {
            "program_id": program["id"],
            "retailer_name": retailer_name,
            "fee_split_retailer_pct": float(pct_dec),
            "fee_split_program_pct": float(Decimal(1) - pct_dec),
            "per_transaction_limit_cents": per_limit,
            "daily_location_limit_cents": daily_limit,
            "settlement_period_hours": period_hours,
            "reload_enabled": reload_enabled,
            "agreement_status": "DRAFT",
            "float_position_cents": 0,
            "settled_fee_total_cents": 0,
            "accrual_pending_cents": 0,
            "contract_version_locked": False,
        }
    )
    db.register(db.retailer_agreements, row)
    return response.ok(core.public(core.RETAILER_AGREEMENT, row), 201)


@bp.get("/v1/retailer-agreements/<agreement_id>")
def get_agreement(agreement_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(core.public(core.RETAILER_AGREEMENT, core.get_agreement(agreement_id)))


@bp.get("/v1/retailer-agreements")
def list_agreements():
    middleware.authenticate(READ_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(db.retailer_agreements, program_id=request.args.get("program_id"))
    total = len(rows)
    return response.array(
        core.public_list(core.RETAILER_AGREEMENT, rows[offset : offset + limit]),
        limit,
        offset,
        total,
    )


# --- state machine ------------------------------------------------------------
ALLOWED = {
    "DRAFT": ("ACTIVE", "TERMINATED"),
    "ACTIVE": ("SUSPENDED", "DRAFT"),
    "SUSPENDED": ("ACTIVE", "TERMINATED"),
    "TERMINATED": (),
}


@bp.post("/v1/retailer-agreements/<agreement_id>/state")
def move_agreement_state(agreement_id):
    user_id, role = middleware.authenticate(("ProgramManager",))
    agreement = core.get_agreement(agreement_id)
    _guard_agreement_owner(agreement, user_id, role)
    program = core.get_program(agreement["program_id"])

    data = rh.body()
    to_status = rh.require_enum(
        data, "to_status", ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
    )
    current = agreement["agreement_status"]
    if to_status not in ALLOWED.get(current, ()):
        raise errors.invalid_state("No transition from %s to %s." % (current, to_status))

    if to_status == "ACTIVE":
        core.guard_not_frozen(program)
        agreement["agreement_status"] = "ACTIVE"
        agreement["fee_split_program_pct"] = float(
            Decimal(1) - Decimal(str(agreement["fee_split_retailer_pct"]))
        )
        core.touch(agreement)
        return response.ok(core.public(core.RETAILER_AGREEMENT, agreement))

    if to_status == "SUSPENDED":
        agreement["agreement_status"] = "SUSPENDED"
        core.touch(agreement)
        for location in _agreement_locations(agreement):
            if location["location_status"] == "OPEN":
                location["location_status"] = "RESTRICTED"
                core.touch(location)
        return response.ok(core.public(core.RETAILER_AGREEMENT, agreement))

    if to_status == "DRAFT":
        if agreement["contract_version_locked"]:
            raise errors.contract_version_locked(
                "The agreement is cited by a posted loss allocation; its contract version is pinned."
            )
        agreement["agreement_status"] = "DRAFT"
        core.touch(agreement)
        return response.ok(core.public(core.RETAILER_AGREEMENT, agreement))

    # TERMINATED
    if current == "SUSPENDED" and int(agreement["accrual_pending_cents"]) != 0:
        raise errors.invalid_state(
            "Unsettled accruals must be settled before the agreement can be terminated."
        )
    agreement["agreement_status"] = "TERMINATED"
    core.touch(agreement)
    for location in _agreement_locations(agreement):
        location["location_status"] = "CLOSED"
        core.touch(location)
    return response.ok(core.public(core.RETAILER_AGREEMENT, agreement))


def _agreement_locations(agreement):
    return [
        l for l in db.reload_locations.values() if l["retailer_agreement_id"] == agreement["id"]
    ]