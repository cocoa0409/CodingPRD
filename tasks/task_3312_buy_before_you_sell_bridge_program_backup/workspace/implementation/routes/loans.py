"""Interim-loan routes (PRD 3.5)."""

from flask import Blueprint

from constants import ROLES
from errors import ERR_INVALID_STATE, ApiError
from routes import endpoint, json_body, query_params
from services import loan as loan_service
from services import program as program_service
from services import repayment as repayment_service
from services.lookup import get_bridge_program, get_interim_loan
from store import db
from timeutil import format_iso
from validation import body_of, get_int, get_str
from services import current_time, touch

bp = Blueprint("loans", __name__)

COORDINATOR = ROLES[0]
UNDERWRITER = ROLES[1]
HOMEOWNER = ROLES[2]


@bp.post("/knock/interim-loans")
@endpoint([COORDINATOR], status=201)
def originate(actor):
    data = body_of(json_body())
    program_id = get_str(data, "bridge_program_id", required=True)
    principal_cents = get_int(data, "principal_cents", required=True, minimum=0)
    interest_rate_bps = get_int(data, "interest_rate_bps", required=True, minimum=0)

    program = get_bridge_program(program_id)
    property_record = db.get("properties", program.get("new_property_id"))
    if property_record is None:
        raise ApiError(ERR_INVALID_STATE, "The program has no new property to secure the loan against.")

    # The direct-origination path is subject to the same loan-to-value ceiling.
    program_service._assert_ltv_ok(principal_cents, property_record)

    loan = loan_service.originate(program["id"], principal_cents, interest_rate_bps)
    loan_service.mark_originated_at(loan, format_iso(current_time()))
    touch(loan)
    return loan


@bp.get("/knock/interim-loans")
@endpoint([COORDINATOR])
def list_loans(actor):
    params = query_params()
    records = db.all("interim_loans")
    program_id = params.get("bridge_program_id")
    if program_id:
        records = [r for r in records if r.get("bridge_program_id") == program_id]
    return db.sorted_by_created(records), params


@bp.get("/knock/interim-loans/<loan_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read(actor, loan_id):
    return get_interim_loan(loan_id)


@bp.post("/knock/interim-loans/<loan_id>/repayments")
@endpoint([COORDINATOR, HOMEOWNER])
def repay(actor, loan_id):
    return repayment_service.post_repayment(loan_id, json_body())


@bp.post("/knock/interim-loans/<loan_id>/reopen-advance")
@endpoint([UNDERWRITER])
def reopen(actor, loan_id):
    return repayment_service.reopen_advance(loan_id, actor)