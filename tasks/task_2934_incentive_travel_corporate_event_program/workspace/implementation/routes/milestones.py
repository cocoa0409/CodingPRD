"""Deposit schedules (PRD 3.5)."""

from flask import Blueprint

import calc
import serialize
from auth import authorize
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_dt, f_id, f_int, raw_fk, validate
from store import db, norm_dt

bp = Blueprint("deposit_milestones", __name__)

READ_ROLES = ("ProgramDirector", "SourcingManager", "ContractApprover")


@bp.post("/deposit-milestones")
def create_milestone():
    authorize("SourcingManager")
    payload = body()

    contract_id = raw_fk(payload, "contract_id")
    if contract_id is not None:
        lookup("contract", contract_id)

    data = validate(payload, [
        f_id("contract_id"),
        f_int("sequence", minimum=1),
        f_dt("due_at"),
        f_int("amount_cents", minimum=0),
        f_int("refundable_bp", minimum=0, maximum=10000),
    ])
    contract = lookup("contract", data["contract_id"])

    for existing in db.deposit_milestones.values():
        if (existing["contract_id"] == contract["id"]
                and existing["sequence"] == data["sequence"]):
            fail("ERR_DUPLICATE_MILESTONE_SEQUENCE")

    prospective = calc.scheduled_deposit_total(db, contract) + data["amount_cents"]
    if prospective > calc.contract_value(contract):
        fail("ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE")

    row = {
        "contract_id": contract["id"],
        "sequence": data["sequence"],
        "due_at": norm_dt(data["due_at"]),
        "amount_cents": data["amount_cents"],
        "refundable_bp": data["refundable_bp"],
        "status": "SCHEDULED",
        "requires_finance_review": False,
        "paid_at": None,
    }
    db.stamp_new(row)
    db.deposit_milestones[row["id"]] = row
    return created(serialize.deposit_milestone(row))


@bp.get("/deposit-milestones/<milestone_id>")
def read_milestone(milestone_id):
    authorize(*READ_ROLES)
    return ok(serialize.deposit_milestone(lookup("milestone", milestone_id)))


@bp.get("/deposit-milestones")
def list_milestones():
    authorize(*READ_ROLES)
    rows = filtered(db.ordered(db.deposit_milestones), [
        ("contract_id", "contract_id"),
        ("status", "status"),
        ("requires_finance_review", "requires_finance_review"),
    ])
    return paginate(rows, serialize.deposit_milestone)


@bp.post("/deposit-milestones/<milestone_id>/pay")
def pay_milestone(milestone_id):
    authorize("ContractApprover")
    milestone = lookup("milestone", milestone_id)
    body()
    contract = db.supplier_contracts.get(milestone["contract_id"])
    program = db.programs.get(contract["program_id"]) if contract else None

    if program is not None and program["status"] in ("CANCELLED", "CLOSED"):
        fail("ERR_PROGRAM_STATE_INVALID")

    if milestone["status"] != "SCHEDULED":
        fail("ERR_MILESTONE_STATE_INVALID")

    if contract is None or contract["status"] != "EXECUTED":
        fail("ERR_CONTRACT_STATE_INVALID")

    milestone["status"] = "PAID"
    milestone["paid_at"] = db.logical_now()
    db.touch(milestone)

    if program is not None:
        calc.program_cancellation_exposure(db, program)

    return ok(serialize.deposit_milestone(milestone))
