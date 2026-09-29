"""Enrollment endpoints: reads, voluntary termination and reinstatement
(PRD 3.5, 3.8)."""

from flask import Blueprint, request

import calc
import errors
from auth import (ALL_ROLES, ROLE_BENEFITS_ADMIN, ROLE_BILLING_CLERK,
                  ROLE_ENROLLMENT_COUNSELOR, require_caller)
from domain import (adjust_enrolled_count, apply_msp, get_enrollment,
                   invoices_of_enrollment, open_account_for,
                   outstanding_balance, terminate_coverage, write_off_invoices)
from envelope import object_response, paginate
from errors import fail
from store import db, now, order_asc, touch
from validate import read_body

bp = Blueprint("enrollments", __name__)

COVERAGE_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
BILLING_STATUSES = ("CURRENT", "DELINQUENT", "LAPSED", "REINSTATED")
TERMINABLE_COVERAGE_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED")


@bp.get("/retiree-benefits/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    require_caller(ALL_ROLES)
    return object_response(get_enrollment(enrollment_id))


@bp.get("/retiree-benefits/enrollments")
def list_enrollments():
    require_caller(ALL_ROLES)
    rows = list(db.enrollments.values())
    for field in ("retiree_id", "plan_year_id", "plan_option_id",
                  "election_event_id", "coverage_status", "billing_status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/enrollments/<enrollment_id>/terminate")
def terminate_enrollment(enrollment_id):
    require_caller((ROLE_BENEFITS_ADMIN, ROLE_ENROLLMENT_COUNSELOR))
    enrollment = get_enrollment(enrollment_id)
    body = read_body()
    termination_reason = body.string("termination_reason")

    if enrollment["coverage_status"] not in TERMINABLE_COVERAGE_STATUSES:
        fail(errors.ERR_INVALID_ENROLLMENT_STATE,
             "Termination requires coverage_status PENDING, ACTIVE or SUSPENDED.")

    terminate_coverage(enrollment, termination_reason)
    adjust_enrolled_count(enrollment["plan_option_id"], -1)
    write_off_invoices(enrollment["id"], ("ISSUED", "PARTIALLY_PAID"))
    touch(enrollment)
    return object_response(enrollment)


@bp.post("/retiree-benefits/enrollments/<enrollment_id>/reinstate")
def reinstate_enrollment(enrollment_id):
    require_caller((ROLE_BILLING_CLERK,))
    enrollment = get_enrollment(enrollment_id)

    if enrollment["coverage_status"] != "TERMINATED" \
            or enrollment["billing_status"] != "LAPSED":
        fail(errors.ERR_INVALID_ENROLLMENT_STATE,
             "Reinstatement requires a TERMINATED enrollment whose billing "
             "status is LAPSED.")

    deadline = enrollment["reinstatement_deadline"]
    if deadline is None or now() > deadline:
        fail(errors.ERR_REINSTATEMENT_WINDOW_EXPIRED)

    for other in db.enrollments.values():
        if other["id"] == enrollment["id"]:
            continue
        if other["retiree_id"] != enrollment["retiree_id"]:
            continue
        for invoice in invoices_of_enrollment(other["id"]):
            if invoice["status"] == "PAST_DUE" and outstanding_balance(invoice) != 0:
                fail(errors.ERR_OUTSTANDING_PREMIUM_BALANCE)

    enrollment["billing_status"] = "REINSTATED"
    enrollment["consecutive_unpaid_periods"] = 0
    enrollment["delinquency_first_unpaid_period_start"] = None
    enrollment["lapse_date"] = None
    enrollment["reinstatement_count"] += 1
    enrollment["coverage_status"] = "ACTIVE"
    enrollment["coverage_end_date"] = None
    enrollment["termination_reason"] = None

    adjust_enrolled_count(enrollment["plan_option_id"], 1)

    account = open_account_for(enrollment["retiree_id"],
                              enrollment["plan_year_id"], statuses=("FROZEN",))
    if account is not None:
        account["status"] = "OPEN"
        touch(account)

    retiree = db.retirees.get(enrollment["retiree_id"])
    if retiree is not None:
        apply_msp(enrollment, retiree)

    touch(enrollment)
    return object_response(enrollment)
