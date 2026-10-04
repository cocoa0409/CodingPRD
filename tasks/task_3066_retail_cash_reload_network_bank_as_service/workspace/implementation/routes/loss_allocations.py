"""Loss allocation endpoints."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil

bp = Blueprint("loss_allocations", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
)

BASES = ("FRAUD_LOSS", "AML_CONFIRMED", "DISPUTE_FAVOR_CARDHOLDER")


@bp.post("/v1/loss-allocations")
def create_allocation():
    middleware.authenticate(("ComplianceOfficer", "PlatformAdmin"))
    data = rh.body()
    program_id = rh.require_str(data, "program_id")
    load_id = rh.require_str(data, "load_transaction_id")
    agreement_id = rh.require_str(data, "retailer_agreement_id")
    total_loss = rh.require_int(data, "total_loss_cents")
    basis = rh.require_enum(data, "allocation_basis", BASES)
    dispute_case_id = rh.optional(data, "dispute_case_id")

    program = core.ref_program(program_id)
    load = core.ref_load(load_id)
    agreement = core.ref_agreement(agreement_id)
    core.guard_not_frozen(program)

    if total_loss < 1:
        raise errors.invalid_request("total_loss_cents must be at least 1.")

    if dispute_case_id is not None:
        core.ref_dispute(dispute_case_id)

    retailer_share, program_share, bank_share = calc.loss_split(
        total_loss, agreement["per_transaction_limit_cents"], program["program_type"]
    )
    if "retailer_share_cents" in data and data["retailer_share_cents"] is not None:
        supplied = rh.require_int(data, "retailer_share_cents")
        retailer_share = supplied
        remaining = int(total_loss) - supplied
        bank_pct = (
            calc.BANK_BEAR_PCT_BAAS
            if program["program_type"] == "BAAS_PROGRAM_MANAGER"
            else calc.BANK_BEAR_PCT_OWN
        )
        bank_share = calc.round_floor_int(Decimal(remaining) * bank_pct)
        program_share = remaining - bank_share

    if retailer_share + program_share + bank_share != int(total_loss):
        raise errors.loss_allocation_mismatch(
            "The three shares do not sum to total_loss_cents."
        )

    row = core.common_fields()
    row.update(
        {
            "program_id": program["id"],
            "load_transaction_id": load["id"],
            "retailer_agreement_id": agreement["id"],
            "dispute_case_id": dispute_case_id,
            "total_loss_cents": total_loss,
            "allocation_basis": basis,
            "retailer_share_cents": retailer_share,
            "program_share_cents": program_share,
            "bank_share_cents": bank_share,
            "allocation_status": "DRAFT",
            "posted_at": None,
        }
    )
    db.register(db.loss_allocations, row)
    return response.ok(core.public(core.LOSS_ALLOCATION, row), 201)


@bp.get("/v1/loss-allocations/<allocation_id>")
def get_allocation(allocation_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(core.public(core.LOSS_ALLOCATION, core.get_allocation(allocation_id)))


@bp.get("/v1/loss-allocations")
def list_allocations():
    middleware.authenticate(READ_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.loss_allocations,
        program_id=request.args.get("program_id"),
        retailer_agreement_id=request.args.get("retailer_agreement_id"),
        load_transaction_id=request.args.get("load_transaction_id"),
        dispute_case_id=request.args.get("dispute_case_id"),
        allocation_status=request.args.get("allocation_status"),
    )
    total = len(rows)
    return response.array(
        core.public_list(core.LOSS_ALLOCATION, rows[offset : offset + limit]), limit, offset, total
    )


@bp.post("/v1/loss-allocations/<allocation_id>/post")
def post_allocation(allocation_id):
    middleware.authenticate(("ComplianceOfficer",))
    allocation = core.get_allocation(allocation_id)
    rh.body()

    if allocation["allocation_status"] != "DRAFT":
        raise errors.invalid_state(
            "An allocation in status %s cannot be posted." % allocation["allocation_status"]
        )
    program = core.get_program(allocation["program_id"])
    core.guard_not_frozen(program)

    if (
        int(allocation["retailer_share_cents"])
        + int(allocation["program_share_cents"])
        + int(allocation["bank_share_cents"])
        != int(allocation["total_loss_cents"])
    ):
        raise errors.loss_allocation_mismatch(
            "The three shares do not sum to total_loss_cents."
        )

    agreement = core.get_agreement(allocation["retailer_agreement_id"])
    allocation["allocation_status"] = "POSTED"
    allocation["posted_at"] = timeutil.now()
    core.touch(allocation)

    agreement["contract_version_locked"] = True
    core.touch(agreement)

    core.recompute_program(program)
    core.touch(program)
    return response.ok(core.public(core.LOSS_ALLOCATION, allocation))


@bp.post("/v1/loss-allocations/<allocation_id>/recover")
def recover_allocation(allocation_id):
    middleware.authenticate(("SettlementOperator",))
    allocation = core.get_allocation(allocation_id)
    rh.body()

    if allocation["allocation_status"] != "POSTED":
        raise errors.invalid_state(
            "An allocation in status %s cannot be recovered." % allocation["allocation_status"]
        )
    agreement = core.get_agreement(allocation["retailer_agreement_id"])
    if not _share_charged_through_settlement(agreement, allocation):
        raise errors.invalid_state(
            "The retailer share has not been charged through a settlement of the cited agreement."
        )

    allocation["allocation_status"] = "RECOVERED"
    core.touch(allocation)
    return response.ok(core.public(core.LOSS_ALLOCATION, allocation))


def _share_charged_through_settlement(agreement, allocation):
    """True once a settlement of the cited agreement covers the allocation's
    chargeback window (the period in which its loss was charged)."""
    posted_at = allocation.get("posted_at")
    for batch in db.settlement_batches.values():
        if batch["retailer_agreement_id"] != agreement["id"]:
            continue
        if batch["batch_status"] != "SETTLED":
            continue
        start = batch["period_start_at"]
        end = batch["period_end_at"]
        if posted_at is None or start is None or end is None:
            return True
        if start <= posted_at < end:
            return True
    return False