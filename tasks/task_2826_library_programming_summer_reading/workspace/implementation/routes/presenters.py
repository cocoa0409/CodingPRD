"""Presenters, the screening cycle and presenter contracts."""

from flask import Blueprint, request

import calc
import derive
import lookup
import revision
import services
import store
import validate
from core import date_of
from errors import ApiError
from web import Arr, Obj, endpoint

bp = Blueprint("presenters", __name__)

MANAGER = ("ProgramManager",)
STAFF = ("ProgramManager", "ProgramCoordinator")
STAFF_AND_SCREENER = ("ProgramManager", "ProgramCoordinator", "ScreeningOfficer")
SCREENER = ("ScreeningOfficer",)

PRESENTER_TYPES = ("INDIVIDUAL", "AGENCY")
SCREENING_TIERS = ("NAME_CHECK", "FINGERPRINT")
SCREENING_RESULTS = ("CLEAR", "FLAGGED")
ADJUDICATIONS = ("CLEARED_WITH_CONDITIONS", "DENIED")

SCHEDULABLE = ("DRAFT", "SCHEDULED")
WINDOW_HOLDING = ("EXECUTED", "COMPLETED")


# ---------------------------------------------------------------- presenters

@bp.route("/library/presenters/<presenter_id>", methods=["GET"])
@endpoint(STAFF_AND_SCREENER)
def get_presenter(user_id, role, presenter_id):
    return Obj("presenters", lookup.presenter(presenter_id))


@bp.route("/library/presenters", methods=["POST"])
@endpoint(STAFF, mutating=True)
def create_presenter(user_id, role):
    payload = validate.body()
    legal_name = validate.string_field(payload, "legal_name")
    presenter_type = validate.enum_field(payload, "presenter_type", PRESENTER_TYPES)
    expires_on = validate.date_field(
        payload, "insurance_certificate_expires_on"
    )
    quoted_fee = validate.integer_field(payload, "quoted_fee_cents", minimum=0)
    presenter = store.new_entity(
        "presenters",
        {
            "legal_name": legal_name,
            "presenter_type": presenter_type,
            "insurance_certificate_expires_on": expires_on,
            "quoted_fee_cents": quoted_fee,
            "engagement_status": "PROSPECT",
            "screening_tier": "NONE",
            "screening_decision": "NONE",
            "screening_decided_on": None,
            "screening_valid_until": None,
            "executed_contract_count": 0,
        },
    )
    return Obj("presenters", presenter, 201)


# ----------------------------------------------------------------- screening

@bp.route(
    "/library/presenters/<presenter_id>/screening-requests", methods=["POST"]
)
@endpoint(SCREENER, mutating=True)
def open_screening(user_id, role, presenter_id):
    payload = validate.body()
    tier = validate.enum_field(payload, "screening_tier", SCREENING_TIERS)
    presenter = lookup.presenter(presenter_id)

    if calc.screening_status(presenter) not in ("NONE", "EXPIRED", "BLOCKED"):
        raise ApiError("ERR_SCREENING_STATE_INVALID")

    presenter["screening_decision"] = "PENDING"
    presenter["screening_tier"] = tier
    presenter["screening_decided_on"] = None
    presenter["screening_valid_until"] = None
    revision.mark(presenter)
    return Obj("presenters", presenter)


@bp.route(
    "/library/presenters/<presenter_id>/screening-results", methods=["POST"]
)
@endpoint(SCREENER, mutating=True)
def record_screening_result(user_id, role, presenter_id):
    payload = validate.body()
    result = validate.enum_field(payload, "result", SCREENING_RESULTS)
    decided_on = validate.date_field(payload, "decided_on")
    presenter = lookup.presenter(presenter_id)

    if presenter["screening_decision"] != "PENDING":
        raise ApiError("ERR_SCREENING_STATE_INVALID")

    presenter["screening_decided_on"] = decided_on
    if result == "CLEAR":
        presenter["screening_decision"] = "CLEAR"
        presenter["screening_valid_until"] = calc.screening_valid_until(
            decided_on, presenter["screening_tier"]
        )
    else:
        presenter["screening_decision"] = "FLAGGED"
        presenter["screening_valid_until"] = None
        services.suspend_presenter_cascade(presenter)
    revision.mark(presenter)
    return Obj("presenters", presenter)


@bp.route("/library/presenters/<presenter_id>/adjudications", methods=["POST"])
@endpoint(SCREENER, mutating=True)
def adjudicate_screening(user_id, role, presenter_id):
    payload = validate.body()
    decision = validate.enum_field(payload, "decision", ADJUDICATIONS)
    decided_on = validate.date_field(payload, "decided_on")
    presenter = lookup.presenter(presenter_id)

    if presenter["screening_decision"] != "FLAGGED":
        raise ApiError("ERR_SCREENING_STATE_INVALID")

    presenter["screening_decided_on"] = decided_on
    if decision == "CLEARED_WITH_CONDITIONS":
        presenter["screening_decision"] = "CLEARED_WITH_CONDITIONS"
        presenter["screening_valid_until"] = calc.screening_valid_until(
            decided_on, presenter["screening_tier"]
        )
        services.restore_presenter_cascade(presenter)
    else:
        presenter["screening_decision"] = "DENIED"
        presenter["screening_valid_until"] = None
    revision.mark(presenter)
    return Obj("presenters", presenter)


# ----------------------------------------------------------------- contracts

@bp.route("/library/contracts/<contract_id>", methods=["GET"])
@endpoint(STAFF)
def get_contract(user_id, role, contract_id):
    return Obj("contracts", lookup.contract(contract_id))


@bp.route("/library/contracts", methods=["GET"])
@endpoint(STAFF)
def list_contracts(user_id, role):
    contracts = store.all_of("contracts")
    for field in ("presenter_id", "program_id", "status"):
        value = request.args.get(field)
        if value is not None:
            contracts = [c for c in contracts if c[field] == value]
    return Arr("contracts", contracts)


@bp.route("/library/contracts", methods=["POST"])
@endpoint(STAFF, mutating=True)
def create_contract(user_id, role):
    payload = validate.body()
    presenter_id = validate.string_field(payload, "presenter_id")
    program_id = validate.string_field(payload, "program_id")
    miles = validate.integer_field(payload, "round_trip_miles", minimum=0)

    # step 6: body foreign keys, in field-declaration order
    presenter = lookup.presenter(presenter_id)
    program = lookup.program(program_id)

    # step 16
    if presenter["engagement_status"] == "SUSPENDED":
        raise ApiError("ERR_PRESENTER_SUSPENDED")

    contract = store.new_entity(
        "contracts",
        {
            "presenter_id": presenter["id"],
            "program_id": program["id"],
            "round_trip_miles": miles,
            "negotiation_round": 0,
            "offered_fee_cents": None,
            "countered_fee_cents": None,
            "agreed_fee_cents": None,
            "travel_fee_cents": 0,
            "escort_fee_cents": 0,
            "insurance_rider_fee_cents": 0,
            "weekend_premium_cents": 0,
            "total_fee_cents": 0,
            "kill_fee_cents": 0,
            "offered_by_user_id": None,
            "executed_by_user_id": None,
            "status": "DRAFT",
        },
    )

    if (
        program["compliance_status"] == "UNVERIFIED"
        and program["serves_minors"]
        and calc.screening_status(presenter) != "ACTIVE"
    ):
        program["compliance_status"] = "PENDING_SCREENING"
        revision.mark(program)

    return Obj("contracts", contract, 201)


@bp.route("/library/contracts/<contract_id>/offer", methods=["POST"])
@endpoint(STAFF, mutating=True)
def offer_contract(user_id, role, contract_id):
    payload = validate.body()
    offered = validate.integer_field(payload, "offered_fee_cents", minimum=0)
    contract = lookup.contract(contract_id)
    presenter = store.get("presenters", contract["presenter_id"])
    program = store.get("programs", contract["program_id"])

    # step 11
    if program is not None and program["operational_status"] not in SCHEDULABLE:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    # step 13
    if contract["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError("ERR_CONTRACT_STATE_INVALID")
    # step 16
    if presenter is not None and presenter["engagement_status"] == "SUSPENDED":
        raise ApiError("ERR_PRESENTER_SUSPENDED")
    # step 44
    if contract["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

    contract["offered_fee_cents"] = offered
    contract["negotiation_round"] += 1
    contract["offered_by_user_id"] = user_id
    contract["status"] = "OFFERED"
    revision.mark(contract)
    return Obj("contracts", contract)


@bp.route("/library/contracts/<contract_id>/counter", methods=["POST"])
@endpoint(STAFF, mutating=True)
def counter_contract(user_id, role, contract_id):
    payload = validate.body()
    countered = validate.integer_field(payload, "countered_fee_cents", minimum=0)
    contract = lookup.contract(contract_id)
    presenter = store.get("presenters", contract["presenter_id"])

    # step 13
    if contract["status"] != "OFFERED":
        raise ApiError("ERR_CONTRACT_STATE_INVALID")
    # step 16
    if presenter is not None and presenter["engagement_status"] == "SUSPENDED":
        raise ApiError("ERR_PRESENTER_SUSPENDED")

    contract["countered_fee_cents"] = countered
    contract["status"] = "COUNTERED"
    revision.mark(contract)
    return Obj("contracts", contract)


def _presenter_conflict(contract, presenter, program):
    """Step 27: closed engagement windows of the presenter's live contracts."""
    start, end = calc.presenter_engagement_window(program)
    for other in derive.presenter_contracts(presenter["id"]):
        if other["id"] == contract["id"]:
            continue
        if other["status"] not in WINDOW_HOLDING:
            continue
        other_program = store.get("programs", other["program_id"])
        if other_program is None:
            continue
        other_start, other_end = calc.presenter_engagement_window(other_program)
        if calc.intervals_overlap_closed(start, end, other_start, other_end):
            return True
    return False


@bp.route("/library/contracts/<contract_id>/execute", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def execute_contract(user_id, role, contract_id):
    contract = lookup.contract(contract_id)
    presenter = store.get("presenters", contract["presenter_id"])
    program = store.get("programs", contract["program_id"])

    # step 8
    if contract["offered_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # step 11
    if program is not None and program["operational_status"] not in SCHEDULABLE:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    # step 13
    if contract["status"] != "OFFERED":
        raise ApiError("ERR_CONTRACT_STATE_INVALID")
    # step 16
    if presenter["engagement_status"] == "SUSPENDED":
        raise ApiError("ERR_PRESENTER_SUSPENDED")
    # step 19
    if program["serves_minors"] and calc.screening_status(presenter) != "ACTIVE":
        raise ApiError("ERR_PRESENTER_SCREENING_REQUIRED")
    # step 20
    if presenter["insurance_certificate_expires_on"] < date_of(program["end_utc"]):
        raise ApiError("ERR_PRESENTER_INSURANCE_LAPSED")
    # step 27
    if _presenter_conflict(contract, presenter, program):
        raise ApiError("ERR_PRESENTER_DOUBLE_BOOKED")

    priced = calc.contract_total_fee(contract, program, presenter)

    # step 45
    branch = store.get("branches", program["branch_id"])
    ceiling = calc.fee_cap_cents(branch) if branch is not None else calc.PROGRAM_FEE_CAP_CENTS
    if priced["total_fee_cents"] > ceiling:
        raise ApiError("ERR_FEE_CAP_EXCEEDED")

    guard = services.PostureGuard()
    guard.watch(program)

    contract.update(priced)
    contract["status"] = "EXECUTED"
    contract["executed_by_user_id"] = user_id
    revision.mark(contract)

    presenter["executed_contract_count"] += 1
    presenter["engagement_status"] = "ACTIVE"
    revision.mark(presenter)

    program["compliance_status"] = "CLEARED"
    program["presenter_fee_committed_cents"] += priced["total_fee_cents"]
    guard.settle()
    revision.mark(program)

    return Obj("contracts", contract)
