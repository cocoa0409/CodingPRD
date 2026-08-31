from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_contract,
    get_resource, check_contract_party, fail, req_id, req_int, req_string,
    req_enum, opt_string, req_period_month, month_bounds, now_clock, num,
    require_contract_operational, cars_of_contract, penalties_of_contract,
    ALL_ROLES, ROLE_ADMIN, ROLE_MANAGER, RESOLUTIONS,
)
from calc import assess_penalty

bp = Blueprint("penalties", __name__)


def penalty_json(penalty):
    return serialize(penalty)


def _recompute_balance(contract):
    contract["penalty_balance_cents"] = (
        contract["penalty_lifetime_assessed_cents"]
        - contract["penalty_lifetime_waived_cents"]
        - contract["penalty_lifetime_credited_cents"])


@bp.route(API_PREFIX + "/penalties", methods=["POST"])
def create_penalty():
    user_id, role = authenticate([ROLE_ADMIN])
    body = json_body()
    contract_id = req_id(body, "contract_id")
    contract = get_contract(contract_id)
    check_contract_party(contract, user_id, role)

    period_month = req_period_month(body)
    expected_version = req_int(body, "expected_contract_version")

    if expected_version != contract["version"]:
        fail("ERR_STALE_CONTRACT_VERSION")

    require_contract_operational(contract)

    _, period_end = month_bounds(period_month)
    if now_clock() < period_end:
        fail("ERR_PENALTY_PERIOD_NOT_CLOSED")

    if not cars_of_contract(contract_id):
        fail("ERR_NO_CARS_IN_SCOPE")

    computed = assess_penalty(contract, period_month)

    for prior in penalties_of_contract(contract_id):
        if prior["period_month"] == period_month and prior["status"] == "ISSUED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
            contract["penalty_lifetime_assessed_cents"] -= prior["amount_cents"]

    penalty = new_entity({
        "contract_id": contract_id,
        "period_month": period_month,
        "schedule_applied": computed["schedule_applied"],
        "uptime_variant_applied": computed["uptime_variant_applied"],
        "uptime_pct_applied": num(computed["uptime_pct_applied"]),
        "late_callback_count": computed["late_callback_count"],
        "entrapment_breach_count": computed["entrapment_breach_count"],
        "missed_visit_count": computed["missed_visit_count"],
        "raw_amount_cents": computed["raw_amount_cents"],
        "cap_amount_cents": computed["cap_amount_cents"],
        "amount_cents": computed["amount_cents"],
        "service_credit_cents": computed["service_credit_cents"],
        "status": "ISSUED",
        "assessed_by_user_id": user_id,
        "dispute_reason": None,
        "resolved_by_user_id": None,
        "resolution_note": None,
    })
    db.penalties[penalty["id"]] = penalty

    contract["penalty_lifetime_assessed_cents"] += penalty["amount_cents"]
    _recompute_balance(contract)
    touch(contract)

    return object_response(penalty_json(penalty), 201)


@bp.route(API_PREFIX + "/penalties/<penalty_id>", methods=["GET"])
def read_penalty(penalty_id):
    authenticate(ALL_ROLES)
    penalty = get_resource(db.penalties, penalty_id)
    return object_response(penalty_json(penalty))


@bp.route(API_PREFIX + "/penalties", methods=["GET"])
def list_penalties():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.penalties)
    rows = filter_equals(rows, "contract_id")
    rows = filter_equals(rows, "status")
    rows = filter_equals(rows, "period_month")
    return paginate(rows)


@bp.route(API_PREFIX + "/penalties/<penalty_id>/dispute", methods=["POST"])
def dispute_penalty(penalty_id):
    user_id, role = authenticate([ROLE_MANAGER])
    penalty = get_resource(db.penalties, penalty_id)
    contract = db.contracts.get(penalty["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    reason = req_string(body, "dispute_reason")

    if penalty["status"] != "ISSUED":
        fail("ERR_INVALID_STATE_TRANSITION")

    penalty["status"] = "DISPUTED"
    penalty["dispute_reason"] = reason
    touch(penalty)
    return object_response(penalty_json(penalty))


@bp.route(API_PREFIX + "/penalties/<penalty_id>/resolve", methods=["POST"])
def resolve_penalty(penalty_id):
    user_id, role = authenticate([ROLE_ADMIN])
    penalty = get_resource(db.penalties, penalty_id)
    contract = db.contracts.get(penalty["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    resolution_note = opt_string(body, "resolution_note")

    if penalty["status"] != "DISPUTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if user_id == penalty.get("assessed_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES")

    penalty["status"] = resolution
    penalty["resolved_by_user_id"] = user_id
    penalty["resolution_note"] = resolution_note
    touch(penalty)

    if contract is not None:
        if resolution == "WAIVED":
            contract["penalty_lifetime_waived_cents"] += penalty["amount_cents"]
        elif resolution == "CREDITED":
            contract["penalty_lifetime_credited_cents"] += penalty["amount_cents"]
        _recompute_balance(contract)
        touch(contract)

    return object_response(penalty_json(penalty))
