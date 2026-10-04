"""Bank sponsor endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core

bp = Blueprint("bank_sponsors", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)
LIST_ROLES = ("PlatformAdmin", "BankSponsor", "ComplianceOfficer", "SettlementOperator")


@bp.post("/v1/bank-sponsors")
def create_bank_sponsor():
    middleware.authenticate(("PlatformAdmin",))
    data = rh.body()
    legal_name = rh.require_str(data, "legal_name")
    charter_state_code = rh.require_str(data, "charter_state_code")
    capacity = rh.require_int(data, "sponsorship_capacity_programs")
    if capacity < 1:
        raise errors.invalid_request("sponsorship_capacity_programs must be at least 1.")
    oversight_tier = rh.optional(data, "oversight_tier", "TIER_2")
    if oversight_tier not in ("TIER_1", "TIER_2"):
        raise errors.invalid_request("oversight_tier must be TIER_1 or TIER_2.")
    regulator_exam_due_at = rh.require_datetime(data, "regulator_exam_due_at")

    row = core.common_fields()
    row.update(
        {
            "legal_name": legal_name,
            "charter_state_code": charter_state_code,
            "sponsorship_capacity_programs": capacity,
            "oversight_tier": oversight_tier,
            "regulator_exam_due_at": regulator_exam_due_at,
            "active_program_count": 0,
            "oversight_reviews_completed": 0,
            "is_capacity_exhausted": False,
        }
    )
    db.register(db.bank_sponsors, row)
    return response.ok(core.public(core.BANK_SPONSOR, row), 201)


@bp.get("/v1/bank-sponsors/<bank_id>")
def get_bank_sponsor(bank_id):
    middleware.authenticate(READ_ROLES)
    row = core.get_bank(bank_id)
    return response.ok(core.public(core.BANK_SPONSOR, row))


@bp.get("/v1/bank-sponsors")
def list_bank_sponsors():
    middleware.authenticate(LIST_ROLES)
    limit, offset = rh.pagination()
    rows = db.ordered(db.bank_sponsors.values())
    total = len(rows)
    return response.array(
        core.public_list(core.BANK_SPONSOR, rows[offset : offset + limit]), limit, offset, total
    )