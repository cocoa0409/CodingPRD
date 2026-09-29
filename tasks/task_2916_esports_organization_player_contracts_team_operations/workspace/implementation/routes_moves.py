"""Roster changes: filing, league decision, execution and reversal (PRD section 3.9)."""

from flask import Blueprint

import calc
import cascade
import db
import response
import serializers as ser
import validation as v
from auth import endpoint, caller, require_org_owner, require_player_owner
from db import store
from errors import fail

bp = Blueprint("moves", __name__)

MOVE_TYPES = ("SIGN", "RELEASE", "TRANSFER_OUT")
MOVE_STATES = ("PENDING", "APPROVED", "REJECTED", "EXECUTED", "REVERSED")
DEPARTURES = ("RELEASE", "TRANSFER_OUT")


@bp.post("/roster-moves")
@endpoint(["GeneralManager"])
def file_roster_move():
    payload = v.body()
    raw_org = payload.get("organization_id")
    if isinstance(raw_org, str):
        require_org_owner(raw_org)

    organization_id = v.req_str(payload, "organization_id")
    player_id = v.req_str(payload, "player_id")
    move_type = v.req_enum(payload, "move_type", MOVE_TYPES)
    contract_id = v.req_str(payload, "contract_id")
    expected_version = v.req_int(payload, "expected_organization_version")
    transfer_to = v.opt_str(payload, "transfer_to_organization_id")
    gross_transfer_fee_cents = v.opt_int(payload, "gross_transfer_fee_cents", 0, 0)
    effective_at = v.opt_instant(payload, "effective_at", None)
    if move_type == "TRANSFER_OUT" and transfer_to is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'transfer_to_organization_id' is required for a TRANSFER_OUT.")
    if move_type != "TRANSFER_OUT" and transfer_to is not None:
        fail("ERR_INVALID_REQUEST",
             "Field 'transfer_to_organization_id' is only valid for a TRANSFER_OUT.")
    if effective_at is None:
        effective_at = db.now()

    # ---- band 6 ----------------------------------------------------------------
    organization = v.find_organization(organization_id)
    if transfer_to is not None:
        v.find_organization(transfer_to)
    v.find_player(player_id)
    v.find_contract(contract_id)

    # ---- band 7 ----------------------------------------------------------------
    if expected_version != organization["version"]:
        fail("ERR_ORGANIZATION_VERSION_STALE")

    # ---- band 10 ---------------------------------------------------------------
    league = calc.league_of_organization(organization)
    if move_type == "SIGN" and calc.roster_lock_active(league):
        fail("ERR_ROSTER_LOCK_ACTIVE")
    if move_type == "TRANSFER_OUT" and not calc.transfer_window_open(league):
        fail("ERR_TRANSFER_WINDOW_CLOSED")

    user_id, _role = caller()
    record = {
        "organization_id": organization["id"],
        "player_id": player_id,
        "contract_id": contract_id,
        "transfer_to_organization_id": transfer_to,
        "move_type": move_type,
        "move_status": "PENDING",
        "gross_transfer_fee_cents": gross_transfer_fee_cents,
        "buyout_credit_cents": 0,
        "commission_tier_bp": 0,
        "agent_commission_cents": 0,
        "net_to_org_cents": 0,
        "released_cap_cents": 0,
        "effective_at": effective_at,
        "requested_by_user_id": user_id,
        "approved_by_user_id": None,
        "decision_note": None,
        "reversal_reason": None,
    }
    db.insert(store.roster_moves, record)
    return response.object_response(ser.roster_move(record), 201)


@bp.get("/roster-moves/<move_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent"])
def read_roster_move(move_id):
    record = v.find_roster_move(move_id)
    require_org_owner(record["organization_id"])
    require_player_owner(record["player_id"])
    return response.object_response(ser.roster_move(record))


@bp.get("/roster-moves")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent"])
def list_roster_moves():
    limit, offset = response.pagination()
    organization_id = v.str_filter("organization_id")
    player_id = v.str_filter("player_id")
    contract_id = v.str_filter("contract_id")
    transfer_to = v.str_filter("transfer_to_organization_id")
    status = v.enum_filter("move_status", MOVE_STATES)
    records = list(store.roster_moves.values())
    if organization_id is not None:
        records = [m for m in records if m["organization_id"] == organization_id]
    if player_id is not None:
        records = [m for m in records if m["player_id"] == player_id]
    if contract_id is not None:
        records = [m for m in records if m["contract_id"] == contract_id]
    if transfer_to is not None:
        records = [m for m in records if m["transfer_to_organization_id"] == transfer_to]
    if status is not None:
        records = [m for m in records if m["move_status"] == status]
    return response.paginated(db.in_creation_order(records), ser.roster_move, limit, offset)


@bp.post("/roster-moves/<move_id>/decision")
@endpoint(["LeagueAdmin"])
def decide_roster_move(move_id):
    record = v.find_roster_move(move_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    decision_note = v.free_text(payload, "decision_note")

    if record["move_status"] != "PENDING":
        fail("ERR_MOVE_NOT_PENDING")
    organization = store.organizations[record["organization_id"]]
    league = calc.league_of_organization(organization)
    if calc.roster_lock_active(league):
        fail("ERR_ROSTER_LOCK_ACTIVE")
    user_id, _role = caller()
    if user_id == record["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE" and record["move_type"] == "SIGN":
        # The stricter full-season variant: swap this contract's provisional charge for
        # its recomputed full-season charge and re-test the whole budget.
        contract = store.contracts.get(record["contract_id"])
        committed = calc.committed_salary_cents(organization)
        if contract is not None:
            committed = (committed
                         - contract["provisional_cap_charge_cents"]
                         + calc.final_cap_charge(contract))
        if committed > organization["annual_salary_budget_cents"]:
            fail("ERR_SALARY_CAP_EXCEEDED")

    record["approved_by_user_id"] = user_id
    record["decision_note"] = decision_note
    record["move_status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    db.touch(record)
    return response.object_response(ser.roster_move(record))


@bp.post("/roster-moves/<move_id>/execute")
@endpoint(["GeneralManager"])
def execute_roster_move(move_id):
    record = v.find_roster_move(move_id)
    require_org_owner(record["organization_id"])

    if record["move_status"] != "APPROVED":
        fail("ERR_MOVE_NOT_APPROVED")
    organization = store.organizations[record["organization_id"]]
    league = calc.league_of_organization(organization)
    contract = store.contracts.get(record["contract_id"])

    if record["move_type"] == "TRANSFER_OUT" and not calc.transfer_window_open(league):
        fail("ERR_TRANSFER_WINDOW_CLOSED")

    if record["move_type"] in DEPARTURES:
        if calc.active_roster_count(organization) - 1 < league["min_roster_size"]:
            fail("ERR_ROSTER_SIZE_BELOW_MINIMUM")

    if record["move_type"] == "SIGN":
        # A SIGN execution is deliberately empty: no cascade and no money field.
        record["move_status"] = "EXECUTED"
        db.touch(record)
        return response.object_response(ser.roster_move(record))

    if record["move_type"] == "TRANSFER_OUT":
        settlement = calc.transfer_settlement(record, contract)
        if settlement["net_to_org_cents"] < 0:
            fail("ERR_NEGATIVE_SETTLEMENT")
    else:
        settlement = calc.release_settlement(contract)

    record.update(settlement)
    record["move_status"] = "EXECUTED"
    db.touch(record)
    cascade.terminate_contract(contract, organization, league)
    return response.object_response(ser.roster_move(record))


@bp.post("/roster-moves/<move_id>/reverse")
@endpoint(["LeagueAdmin"])
def reverse_roster_move(move_id):
    record = v.find_roster_move(move_id)
    payload = v.body()
    reversal_reason = v.req_str(payload, "reversal_reason", 1)

    if record["move_status"] != "EXECUTED":
        fail("ERR_MOVE_NOT_EXECUTED")
    if record["move_type"] == "SIGN":
        fail("ERR_MOVE_NOT_REVERSIBLE")

    organization = store.organizations[record["organization_id"]]
    released = record["released_cap_cents"]
    if calc.uncommitted_salary_cents(organization) < released:
        fail("ERR_SALARY_CAP_EXCEEDED")

    contract = store.contracts.get(record["contract_id"])
    record["reversal_reason"] = reversal_reason
    record["move_status"] = "REVERSED"
    if contract is not None:
        cascade.restore_contract(contract, organization, record)
    db.touch(record)
    return response.object_response(ser.roster_move(record))
