"""Supplier contracts: negotiation, execution, withdrawal, exposure (PRD 3.4, 3.5)."""

from flask import Blueprint

import calc
import cascades
import serialize
from auth import authorize
from calc import MAX_NEGOTIATION_ROUNDS
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_dt, f_enum, f_id, f_int, f_str, raw_fk, validate
from store import db, norm_dt

bp = Blueprint("supplier_contracts", __name__)

READ_ROLES = ("ProgramDirector", "SourcingManager", "ContractApprover",
              "SalesOpsAnalyst", "TravelDesk")
EXPOSURE_ROLES = ("ProgramDirector", "SourcingManager", "ContractApprover")

KINDS = ("HOTEL", "DMC", "AIR_CONSOLIDATOR")
CLAUSES = ("NONE", "STANDARD", "EXPANDED")
BASES = ("ATTRITION_BASIS", "DEPOSIT_FORFEITURE_BASIS")
ACTIONS = ("PROPOSE", "COUNTER")

TERM_FIELDS = ("room_block_count", "contracted_nights", "stay_start_at",
               "nightly_rate_cents", "attrition_allowance_bp",
               "force_majeure_clause", "exposure_basis")


@bp.post("/supplier-contracts")
def create_contract():
    authorize("SourcingManager")
    payload = body()

    program_id = raw_fk(payload, "program_id")
    if program_id is not None:
        lookup("program", program_id)
    destination_id = raw_fk(payload, "destination_id")
    if destination_id is not None:
        lookup("destination", destination_id)

    data = validate(payload, [
        f_id("program_id"),
        f_id("destination_id"),
        f_str("supplier_name", max_len=160),
        f_enum("supplier_kind", KINDS),
        f_int("room_block_count", minimum=1),
        f_int("contracted_nights", minimum=1),
        f_dt("stay_start_at"),
        f_int("nightly_rate_cents", minimum=0),
        f_int("attrition_allowance_bp", minimum=0, maximum=10000),
        f_enum("force_majeure_clause", CLAUSES),
        f_enum("exposure_basis", BASES),
    ])
    lookup("program", data["program_id"])
    destination = lookup("destination", data["destination_id"])

    if destination["program_id"] != data["program_id"]:
        fail("ERR_PROGRAM_SCOPE_MISMATCH")

    row = {
        "program_id": data["program_id"],
        "destination_id": data["destination_id"],
        "supplier_name": data["supplier_name"],
        "supplier_kind": data["supplier_kind"],
        "status": "DRAFT",
        "round_count": 0,
        "room_block_count": data["room_block_count"],
        "contracted_nights": data["contracted_nights"],
        "stay_start_at": norm_dt(data["stay_start_at"]),
        "stay_end_at": None,
        "nightly_rate_cents": data["nightly_rate_cents"],
        "attrition_allowance_bp": data["attrition_allowance_bp"],
        "force_majeure_clause": data["force_majeure_clause"],
        "exposure_basis": data["exposure_basis"],
        "room_nights_blocked": 0,
        "room_nights_confirmed": 0,
        "room_nights_available": 0,
        "attrition_posture": "CLEAR",
        "last_proposed_by_user_id": None,
        "last_countered_by_user_id": None,
        "executed_by_user_id": None,
        "executed_at": None,
        "withdrawal_reason": None,
    }
    calc.recompute_stay_end(row)
    db.stamp_new(row)
    db.supplier_contracts[row["id"]] = row
    return created(serialize.supplier_contract(row))


@bp.get("/supplier-contracts/<contract_id>")
def read_contract(contract_id):
    authorize(*READ_ROLES)
    return ok(serialize.supplier_contract(lookup("contract", contract_id)))


@bp.get("/supplier-contracts")
def list_contracts():
    authorize(*READ_ROLES)
    rows = filtered(db.ordered(db.supplier_contracts), [
        ("program_id", "program_id"),
        ("destination_id", "destination_id"),
        ("supplier_kind", "supplier_kind"),
        ("status", "status"),
    ])
    return paginate(rows, serialize.supplier_contract)


@bp.post("/supplier-contracts/<contract_id>/negotiate")
def negotiate(contract_id):
    actor = authorize("SourcingManager", "ContractApprover")
    contract = lookup("contract", contract_id)
    data = validate(body(), [
        f_enum("action", ACTIONS),
        f_int("room_block_count", required=False, minimum=1),
        f_int("contracted_nights", required=False, minimum=1),
        f_dt("stay_start_at", required=False),
        f_int("nightly_rate_cents", required=False, minimum=0),
        f_int("attrition_allowance_bp", required=False, minimum=0, maximum=10000),
        f_enum("force_majeure_clause", CLAUSES, required=False),
        f_enum("exposure_basis", BASES, required=False),
        f_str("note", required=False),
    ])
    program_gate(db.programs.get(contract["program_id"]),
                 ("DESIGN", "SOURCING", "CONTRACTED"))

    action = data["action"]
    status = contract["status"]
    if action == "PROPOSE":
        if status not in ("DRAFT", "COUNTERED"):
            fail("ERR_CONTRACT_STATE_INVALID")
    else:
        if status != "PROPOSED":
            fail("ERR_CONTRACT_STATE_INVALID")

    if contract["round_count"] >= MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

    for field in TERM_FIELDS:
        if field in data:
            contract[field] = norm_dt(data[field]) if field == "stay_start_at" else data[field]
    calc.recompute_stay_end(contract)

    if action == "PROPOSE":
        contract["status"] = "PROPOSED"
        contract["last_proposed_by_user_id"] = actor.user_id
    else:
        contract["status"] = "COUNTERED"
        contract["last_countered_by_user_id"] = actor.user_id

    contract["round_count"] += 1
    db.touch(contract)
    return ok(serialize.supplier_contract(contract))


@bp.post("/supplier-contracts/<contract_id>/execute")
def execute(contract_id):
    actor = authorize("ContractApprover")
    contract = lookup("contract", contract_id)
    body()
    program_gate(db.programs.get(contract["program_id"]), ("SOURCING", "CONTRACTED"))

    if contract["status"] != "PROPOSED":
        fail("ERR_CONTRACT_STATE_INVALID")

    if actor.user_id in (contract["last_proposed_by_user_id"],
                         contract["last_countered_by_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES")

    if calc.scheduled_deposit_total(db, contract) > calc.contract_value(contract):
        fail("ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE")

    cascades.execute_contract(contract, actor)
    return ok(serialize.supplier_contract(contract))


@bp.post("/supplier-contracts/<contract_id>/withdraw")
def withdraw(contract_id):
    authorize("SourcingManager")
    contract = lookup("contract", contract_id)
    data = validate(body(), [f_str("withdrawal_reason")])
    program = db.programs.get(contract["program_id"])
    if program["status"] == "CLOSED":
        fail("ERR_PROGRAM_STATE_INVALID")

    if contract["status"] not in ("DRAFT", "PROPOSED", "COUNTERED"):
        fail("ERR_CONTRACT_STATE_INVALID")

    cascades.withdraw_contract(contract, data["withdrawal_reason"])
    return ok(serialize.supplier_contract(contract))


@bp.get("/supplier-contracts/<contract_id>/exposure-projection")
def exposure_projection(contract_id):
    authorize(*EXPOSURE_ROLES)
    contract = lookup("contract", contract_id)
    calc.room_night_ledger(db, contract)
    return ok(calc.exposure_projection(db, contract, db.logical_now()))
