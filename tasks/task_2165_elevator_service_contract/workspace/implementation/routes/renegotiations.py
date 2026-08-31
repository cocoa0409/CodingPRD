from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_contract,
    get_resource, check_contract_party, fail, req_id, req_int, req_enum, num,
    rounds_of_contract,
    ALL_ROLES, ROLE_MANAGER, ROLE_CONTRACTOR, SCOPE_TYPES, CLOSE_OUTCOMES,
    MAX_RENEGOTIATION_ROUNDS, RENEGOTIATION_TRIGGER_SCORE,
)
from calc import performance_score

bp = Blueprint("renegotiations", __name__)


def _proposal_fields(body):
    fee = req_int(body, "proposed_monthly_fee_cents", 1)
    minutes = req_int(body, "proposed_callback_response_minutes", 1)
    scope = req_enum(body, "proposed_scope_type", SCOPE_TYPES)
    return fee, minutes, scope


def _contract_has_open_round(contract_id):
    for rnd in rounds_of_contract(contract_id):
        if rnd["status"] == "OPEN":
            return True
    return False


@bp.route(API_PREFIX + "/renegotiations", methods=["POST"])
def open_renegotiation():
    user_id, role = authenticate([ROLE_MANAGER])
    body = json_body()
    contract_id = req_id(body, "contract_id")
    contract = get_contract(contract_id)
    check_contract_party(contract, user_id, role)

    fee, minutes, scope = _proposal_fields(body)

    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if contract["renegotiation_round_count"] >= MAX_RENEGOTIATION_ROUNDS:
        fail("ERR_RENEGOTIATION_ROUND_LIMIT")

    score = performance_score(contract)
    if score >= RENEGOTIATION_TRIGGER_SCORE:
        fail("ERR_RENEGOTIATION_NOT_WARRANTED")

    contract["performance_score"] = num(score)
    contract["renegotiation_round_count"] = contract["renegotiation_round_count"] + 1
    contract["status"] = "UNDER_RENEGOTIATION"
    touch(contract)

    rnd = new_entity({
        "contract_id": contract_id,
        "round_number": contract["renegotiation_round_count"],
        "proposed_monthly_fee_cents": fee,
        "proposed_callback_response_minutes": minutes,
        "proposed_scope_type": scope,
        "status": "OPEN",
        "opened_by_user_id": user_id,
        "countered_by_user_id": None,
        "accepted_by_user_id": None,
        "trigger_performance_score": num(score),
    })
    db.rounds[rnd["id"]] = rnd
    return object_response(serialize(rnd), 201)


@bp.route(API_PREFIX + "/renegotiations/<round_id>", methods=["GET"])
def read_round(round_id):
    authenticate(ALL_ROLES)
    rnd = get_resource(db.rounds, round_id)
    return object_response(serialize(rnd))


@bp.route(API_PREFIX + "/renegotiations", methods=["GET"])
def list_rounds():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.rounds)
    rows = filter_equals(rows, "contract_id")
    rows = filter_equals(rows, "status")
    return paginate(rows)


@bp.route(API_PREFIX + "/renegotiations/<round_id>/counter", methods=["POST"])
def counter_round(round_id):
    user_id, role = authenticate([ROLE_CONTRACTOR, ROLE_MANAGER])
    rnd = get_resource(db.rounds, round_id)
    contract = db.contracts.get(rnd["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    fee, minutes, scope = _proposal_fields(body)

    if rnd["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")
    if contract is None or contract["status"] != "UNDER_RENEGOTIATION":
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if user_id == rnd["opened_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if contract["renegotiation_round_count"] >= MAX_RENEGOTIATION_ROUNDS:
        fail("ERR_RENEGOTIATION_ROUND_LIMIT")

    rnd["status"] = "COUNTERED"
    rnd["countered_by_user_id"] = user_id
    touch(rnd)

    contract["renegotiation_round_count"] = contract["renegotiation_round_count"] + 1
    touch(contract)

    successor = new_entity({
        "contract_id": contract["id"],
        "round_number": contract["renegotiation_round_count"],
        "proposed_monthly_fee_cents": fee,
        "proposed_callback_response_minutes": minutes,
        "proposed_scope_type": scope,
        "status": "OPEN",
        "opened_by_user_id": user_id,
        "countered_by_user_id": None,
        "accepted_by_user_id": None,
        "trigger_performance_score": rnd["trigger_performance_score"],
    })
    db.rounds[successor["id"]] = successor
    return object_response(serialize(successor), 201)


@bp.route(API_PREFIX + "/renegotiations/<round_id>/accept", methods=["POST"])
def accept_round(round_id):
    user_id, role = authenticate([ROLE_MANAGER, ROLE_CONTRACTOR])
    rnd = get_resource(db.rounds, round_id)
    contract = db.contracts.get(rnd["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if rnd["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")
    if contract is None or contract["status"] != "UNDER_RENEGOTIATION":
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if user_id == rnd["opened_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    rnd["status"] = "ACCEPTED"
    rnd["accepted_by_user_id"] = user_id
    touch(rnd)

    for other in rounds_of_contract(contract["id"]):
        if other["id"] != rnd["id"] and other["status"] == "OPEN":
            other["status"] = "WITHDRAWN"
            touch(other)

    contract["monthly_base_fee_cents"] = rnd["proposed_monthly_fee_cents"]
    contract["callback_response_minutes"] = rnd["proposed_callback_response_minutes"]
    contract["scope_type"] = rnd["proposed_scope_type"]
    contract["status"] = "ACTIVE"
    touch(contract)

    return object_response(serialize(rnd))


@bp.route(API_PREFIX + "/renegotiations/<round_id>/close", methods=["POST"])
def close_round(round_id):
    user_id, role = authenticate([ROLE_MANAGER, ROLE_CONTRACTOR])
    rnd = get_resource(db.rounds, round_id)
    contract = db.contracts.get(rnd["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    outcome = req_enum(body, "outcome", CLOSE_OUTCOMES)

    if rnd["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")
    if contract is None or contract["status"] != "UNDER_RENEGOTIATION":
        fail("ERR_CONTRACT_NOT_ACTIVE")

    rnd["status"] = outcome
    touch(rnd)

    if not _contract_has_open_round(contract["id"]):
        contract["status"] = "ACTIVE"
        touch(contract)

    return object_response(serialize(rnd))
