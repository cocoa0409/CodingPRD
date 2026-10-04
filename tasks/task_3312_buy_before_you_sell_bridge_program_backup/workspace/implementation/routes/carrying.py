"""Carrying-cost routes (PRD 3.9)."""

from flask import Blueprint

from constants import CARRYING_COST_KINDS, ROLES
from routes import endpoint, json_body, query_params
from services import burden as burden_service
from services import current_time, create, touch
from services.lookup import get_bridge_program, get_carrying_cost
from store import db
from timeutil import format_iso
from validation import body_of, get_datetime, get_enum, get_int, get_str

bp = Blueprint("carrying", __name__)

COORDINATOR = ROLES[0]
HOMEOWNER = ROLES[2]


@bp.post("/knock/carrying-costs")
@endpoint([COORDINATOR], status=201)
def register_cost(actor):
    data = body_of(json_body())
    program_id = get_str(data, "bridge_program_id", required=True)
    kind = get_enum(data, "kind", CARRYING_COST_KINDS, required=True)
    amount_cents = get_int(data, "amount_cents", required=True, minimum=0)
    due_date = get_datetime(data, "due_date", required=True)

    program = get_bridge_program(program_id)

    record = {
        "bridge_program_id": program["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "due_date": format_iso(due_date),
        "repayment_status": "UNPAID",
        "repaid_at": None,
    }
    create("carrying_costs", record)

    burden_service.recompute_program_burden(program)
    touch(program)
    return record


@bp.get("/knock/carrying-costs")
@endpoint([COORDINATOR])
def list_costs(actor):
    params = query_params()
    records = db.all("carrying_costs")
    program_id = params.get("bridge_program_id")
    if program_id:
        records = [r for r in records if r.get("bridge_program_id") == program_id]
    status = params.get("repayment_status")
    if status:
        records = [r for r in records if r.get("repayment_status") == status]
    return db.sorted_by_created(records), params


@bp.get("/knock/carrying-costs/<cost_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read_cost(actor, cost_id):
    return get_carrying_cost(cost_id)


@bp.post("/knock/carrying-costs/<cost_id>/repay")
@endpoint([COORDINATOR, HOMEOWNER])
def repay_cost(actor, cost_id):
    record = get_carrying_cost(cost_id)

    record["repayment_status"] = "REPAID"
    record["repaid_at"] = format_iso(current_time())
    touch(record)

    program = get_bridge_program(record["bridge_program_id"])
    burden_service.recompute_program_burden(program)
    touch(program)
    return record