"""Settlement batch endpoints: scheduling, opening, settling and clawback."""

from flask import Blueprint, request

from decimal import Decimal

import calc
import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil

bp = Blueprint("settlement_batches", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)
LIST_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)


@bp.post("/v1/settlement-batches")
def create_batch():
    middleware.authenticate(("SettlementOperator", "PlatformAdmin"))
    data = rh.body()
    agreement_id = rh.require_str(data, "retailer_agreement_id")
    start = rh.require_datetime(data, "period_start_at")
    end = rh.require_datetime(data, "period_end_at")

    agreement = core.ref_agreement(agreement_id)
    program = core.get_program(agreement["program_id"])
    core.guard_not_frozen(program)
    if start >= end:
        raise errors.invalid_request("period_start_at must precede period_end_at.")

    for batch in db.settlement_batches.values():
        if batch["retailer_agreement_id"] != agreement["id"]:
            continue
        if batch["batch_status"] != "OPEN":
            continue
        if _overlaps(start, end, batch["period_start_at"], batch["period_end_at"]):
            raise errors.settlement_period_overlap(
                "The candidate period shares an interior with an open batch period."
            )

    row = core.common_fields()
    row.update(
        {
            "retailer_agreement_id": agreement["id"],
            "period_start_at": start,
            "period_end_at": end,
            "batch_status": "SCHEDULED",
            "gross_principal_cents": 0,
            "accrued_retailer_share_cents": 0,
            "net_fee_payable_cents": 0,
            "settlement_rounding_delta_cents": 0,
            "chargeback_total_cents": 0,
            "float_retained_cents": 0,
            "settled_at": None,
        }
    )
    db.register(db.settlement_batches, row)
    return response.ok(core.public(core.SETTLEMENT_BATCH, row), 201)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open adjacency is not an overlap."""
    return a_start < b_end and b_start < a_end


@bp.get("/v1/settlement-batches/<batch_id>")
def get_batch(batch_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(core.public(core.SETTLEMENT_BATCH, core.get_batch(batch_id)))


@bp.get("/v1/settlement-batches")
def list_batches():
    middleware.authenticate(LIST_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.settlement_batches,
        retailer_agreement_id=request.args.get("retailer_agreement_id"),
        batch_status=request.args.get("batch_status"),
    )
    total = len(rows)
    return response.array(
        core.public_list(core.SETTLEMENT_BATCH, rows[offset : offset + limit]),
        limit,
        offset,
        total,
    )


@bp.post("/v1/settlement-batches/<batch_id>/open")
def open_batch(batch_id):
    middleware.authenticate(("SettlementOperator",))
    batch = core.get_batch(batch_id)
    rh.body()
    if batch["batch_status"] != "SCHEDULED":
        raise errors.invalid_state(
            "A batch in status %s cannot be opened." % batch["batch_status"]
        )
    agreement = core.get_agreement(batch["retailer_agreement_id"])
    program = core.get_program(agreement["program_id"])
    core.guard_not_frozen(program)
    if agreement["agreement_status"] != "ACTIVE":
        raise errors.agreement_not_active(
            "The retailer agreement is %s, not ACTIVE." % agreement["agreement_status"]
        )
    for other in db.settlement_batches.values():
        if other["id"] == batch["id"]:
            continue
        if other["retailer_agreement_id"] == agreement["id"] and other["batch_status"] == "OPEN":
            raise errors.settlement_period_overlap(
                "Another batch of this agreement is already OPEN."
            )
    batch["batch_status"] = "OPEN"
    core.touch(batch)
    return response.ok(core.public(core.SETTLEMENT_BATCH, batch))


@bp.post("/v1/settlement-batches/<batch_id>/settle")
def settle_batch(batch_id):
    middleware.authenticate(("SettlementOperator",))
    batch = core.get_batch(batch_id)
    rh.body()
    if batch["batch_status"] != "OPEN":
        raise errors.invalid_state(
            "A batch in status %s cannot be settled." % batch["batch_status"]
        )
    agreement = core.get_agreement(batch["retailer_agreement_id"])
    program = core.get_program(agreement["program_id"])
    core.guard_not_frozen(program)
    if agreement["agreement_status"] != "ACTIVE":
        raise errors.agreement_not_active(
            "The retailer agreement is %s, not ACTIVE." % agreement["agreement_status"]
        )

    start = batch["period_start_at"]
    end = batch["period_end_at"]
    agreement_locations = {
        l["id"] for l in db.reload_locations.values() if l["retailer_agreement_id"] == agreement["id"]
    }
    candidates = []
    for load in db.ordered(db.load_transactions.values()):
        if load["reload_location_id"] not in agreement_locations:
            continue
        if load["load_status"] != "FUNDED":
            continue
        funded_at = load["funded_at"]
        if funded_at is None:
            continue
        if start <= funded_at < end:
            candidates.append(load)

    if not candidates:
        raise errors.settlement_empty_period(
            "No FUNDED load falls inside the batch period."
        )

    for load in candidates:
        load["load_status"] = "SETTLED"
        load["settlement_batch_id"] = batch["id"]
        core.touch(load)

    amounts = calc.batch_amounts(
        [load["convenience_fee_cents"] for load in candidates],
        [load["principal_cents"] for load in candidates],
        agreement["fee_split_retailer_pct"],
    )
    batch.update(amounts)
    batch["chargeback_total_cents"] = sum(
        int(a["total_loss_cents"])
        for a in db.loss_allocations.values()
        if a["retailer_agreement_id"] == agreement["id"]
        and a["allocation_status"] == "POSTED"
        and a.get("posted_at") is not None
        and start <= a["posted_at"] < end
    )
    batch["float_retained_cents"] = calc.float_retained_cents(
        candidates, agreement["float_position_cents"]
    )
    batch["batch_status"] = "SETTLED"
    batch["settled_at"] = timeutil.now()
    core.touch(batch)

    agreement["settled_fee_total_cents"] = calc.num(
        Decimal(str(agreement["settled_fee_total_cents"]))
        + Decimal(str(batch["accrued_retailer_share_cents"]))
    )
    agreement["accrual_pending_cents"] = calc.num(
        Decimal(str(agreement["accrual_pending_cents"]))
        - Decimal(str(batch["accrued_retailer_share_cents"]))
    )
    core.touch(agreement)
    return response.ok(core.public(core.SETTLEMENT_BATCH, batch))


@bp.post("/v1/settlement-batches/<batch_id>/clawback")
def clawback_batch(batch_id):
    middleware.authenticate(("SettlementOperator",))
    batch = core.get_batch(batch_id)
    rh.body()
    if batch["batch_status"] != "SETTLED":
        raise errors.settlement_not_settled(
            "A clawback requires a batch whose batch_status is SETTLED."
        )

    agreement = core.get_agreement(batch["retailer_agreement_id"])
    program = core.get_program(agreement["program_id"])

    # hop 1
    batch["batch_status"] = "CLAWED_BACK"
    core.touch(batch)
    touched_programs = set()
    for load in db.ordered(db.load_transactions.values()):
        if load["settlement_batch_id"] != batch["id"]:
            continue
        if load["load_status"] != "SETTLED":
            continue
        _, _, _, load_program = core.reverse_load(
            load, "RETAILER_REQUEST", unwind_agreement=False
        )
        touched_programs.add(load_program["id"])
    for pid in touched_programs:
        core.recompute_program(db.programs[pid])
        core.touch(db.programs[pid])

    agreement["float_position_cents"] = core.money_sub(
        agreement["float_position_cents"], batch["float_retained_cents"]
    )
    agreement["accrual_pending_cents"] = calc.num(
        Decimal(str(agreement["accrual_pending_cents"]))
        + Decimal(str(batch["accrued_retailer_share_cents"]))
    )
    core.touch(agreement)
    return response.ok(core.public(core.SETTLEMENT_BATCH, batch))