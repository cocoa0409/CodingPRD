"""ElectionEvent endpoints: window evaluation, adjudication and the birth of an
Enrollment (PRD 3.5)."""

from flask import Blueprint, request

import calc
import errors
from auth import (ALL_ROLES, ROLE_BENEFITS_ADMIN, ROLE_ENROLLMENT_COUNSELOR,
                  ROLE_RETIREE, require_caller, require_ownership)
from domain import (adjust_enrolled_count, apply_msp, body_reference,
                   certified_determination, enrollments_of_retiree,
                   get_election_event, get_plan_option, get_plan_year,
                   get_retiree, require_certified_eligible)
from envelope import object_response, paginate
from errors import fail
from store import base_record, db, now, order_asc, touch
from validate import read_body

bp = Blueprint("elections", __name__)

EVENT_TYPES = ("ANNUAL_OPEN", "MEDICARE_ENTITLEMENT", "LOSS_OF_OTHER_COVERAGE",
               "MARRIAGE", "DEPENDENT_DEATH")
ELECTION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")
ELECTION_DECISIONS = ("APPROVE", "DENY")
DENIAL_REASON_CODES = ("COUNSELOR_DENIAL", "PLAN_CLOSED")
DEFAULT_DENIAL_REASON_CODE = "COUNSELOR_DENIAL"

ADJUDICATOR_ROLES = (ROLE_ENROLLMENT_COUNSELOR, ROLE_BENEFITS_ADMIN)
SUBSIDY_GATED_VEHICLES = ("RDS", "EGWP")


@bp.post("/retiree-benefits/election-events")
def create_election_event():
    caller = require_caller((ROLE_RETIREE, ROLE_ENROLLMENT_COUNSELOR))
    body = read_body()
    plan_year = body_reference(body, "plan_year_id", get_plan_year)
    retiree = body_reference(body, "retiree_id", get_retiree)
    option = body_reference(body, "requested_plan_option_id", get_plan_option)

    if body.present("retiree_id") and isinstance(body.value("retiree_id"), str):
        require_ownership(caller, body.value("retiree_id"))

    retiree_id = body.string("retiree_id")
    plan_year_id = body.string("plan_year_id")
    option_id = body.string("requested_plan_option_id")
    event_type = body.enum("event_type", EVENT_TYPES)
    event_date = body.date("event_date")

    if plan_year["status"] != "OPEN":
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN)
    if option["status"] != "ACTIVE":
        fail(errors.ERR_PLAN_OPTION_NOT_ACTIVE)

    require_certified_eligible(retiree_id, plan_year_id)

    clock = now()
    if event_type == "ANNUAL_OPEN":
        window_deadline = plan_year["open_enrollment_end"]
        coverage_effective_date = plan_year["coverage_start"]
        if not (plan_year["open_enrollment_start"] <= clock < window_deadline):
            fail(errors.ERR_ELECTION_WINDOW_CLOSED)
    else:
        window_open = calc.midnight(event_date)
        window_deadline = calc.plus_days(window_open, calc.LIFE_EVENT_WINDOW_DAYS)
        coverage_effective_date = calc.first_day_of_next_month(event_date)
        if not (window_open <= clock <= window_deadline):
            fail(errors.ERR_LIFE_EVENT_WINDOW_EXPIRED)

    if not calc.coverage_class_permitted(retiree["medicare_status"],
                                        option["coverage_class"]):
        fail(errors.ERR_PLAN_CLASS_MISMATCH)

    if option["requires_medicare_part_b"]:
        part_b = retiree["medicare_part_b_effective_date"]
        if part_b is None or calc.midnight(part_b) > coverage_effective_date:
            fail(errors.ERR_MEDICARE_PART_B_REQUIRED)

    if retiree["grandfathered_group"] not in option["allowed_grandfather_groups"]:
        fail(errors.ERR_GRANDFATHER_GROUP_NOT_PERMITTED)

    record = base_record()
    record.update({
        "retiree_id": retiree_id,
        "plan_year_id": plan_year_id,
        "requested_plan_option_id": option_id,
        "event_type": event_type,
        "event_date": event_date,
        "submitted_at": clock,
        "window_deadline": window_deadline,
        "coverage_effective_date": coverage_effective_date,
        "status": "SUBMITTED",
        "created_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
        "denial_reason_code": None,
        "resulting_enrollment_id": None,
    })
    db.election_events[record["id"]] = record
    return object_response(record, 201)


@bp.get("/retiree-benefits/election-events/<election_event_id>")
def read_election_event(election_event_id):
    require_caller(ALL_ROLES)
    return object_response(get_election_event(election_event_id))


@bp.get("/retiree-benefits/election-events")
def list_election_events():
    require_caller(ALL_ROLES)
    rows = list(db.election_events.values())
    for field in ("retiree_id", "plan_year_id", "requested_plan_option_id",
                  "resulting_enrollment_id", "status", "event_type"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/election-events/<election_event_id>/review")
def review_election_event(election_event_id):
    caller = require_caller(ADJUDICATOR_ROLES)
    event = get_election_event(election_event_id)

    if event["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_ELECTION_STATE,
             "Taking an election into review requires status SUBMITTED.")

    plan_year = db.plan_years.get(event["plan_year_id"])
    if plan_year is None or plan_year["status"] != "OPEN":
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN)

    event["status"] = "UNDER_REVIEW"
    event["reviewed_by_user_id"] = caller.user_id
    touch(event)
    return object_response(event)


@bp.post("/retiree-benefits/election-events/<election_event_id>/decision")
def decide_election_event(election_event_id):
    caller = require_caller(ADJUDICATOR_ROLES)
    event = get_election_event(election_event_id)
    body = read_body()
    decision = body.enum("decision", ELECTION_DECISIONS)
    denial_reason_code = body.enum("denial_reason_code", DENIAL_REASON_CODES,
                                   required=False, default=None)

    if event["status"] != "UNDER_REVIEW":
        fail(errors.ERR_INVALID_ELECTION_STATE,
             "Deciding an election requires status UNDER_REVIEW.")

    if event["created_by_user_id"] is not None \
            and caller.user_id == event["created_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The submitting user may not decide their own election.")

    if decision == "DENY":
        event["status"] = "DENIED"
        event["denial_reason_code"] = denial_reason_code or DEFAULT_DENIAL_REASON_CODE
        touch(event)
        return object_response(event)

    return _approve(event)


def _approve(event):
    option = db.plan_options.get(event["requested_plan_option_id"])
    if option is None or option["status"] != "ACTIVE":
        fail(errors.ERR_PLAN_OPTION_NOT_ACTIVE)

    if option["subsidy_vehicle"] in SUBSIDY_GATED_VEHICLES \
            and option["subsidy_certification_status"] != "CERTIFIED":
        fail(errors.ERR_SUBSIDY_NOT_CERTIFIED)

    require_certified_eligible(event["retiree_id"], event["plan_year_id"])

    proposed_start = event["coverage_effective_date"]
    for existing in enrollments_of_retiree(event["retiree_id"]):
        if calc.coverage_intervals_collide(proposed_start, None,
                                           existing["coverage_effective_date"],
                                           existing["coverage_end_date"]):
            fail(errors.ERR_DUPLICATE_ENROLLMENT_PERIOD)

    retiree = db.retirees[event["retiree_id"]]
    clock = now()
    waterfall = calc.premium_waterfall(option, retiree, 0)

    enrollment = base_record()
    enrollment.update({
        "retiree_id": event["retiree_id"],
        "plan_year_id": event["plan_year_id"],
        "plan_option_id": option["id"],
        "election_event_id": event["id"],
        "coverage_status": "ACTIVE" if clock >= proposed_start else "PENDING",
        "billing_status": "CURRENT",
        "coverage_effective_date": proposed_start,
        "coverage_end_date": None,
        "monthly_retiree_premium_cents": waterfall["retiree_share_cents"],
        "consecutive_unpaid_periods": 0,
        "delinquency_first_unpaid_period_start": None,
        "lapse_date": None,
        "reinstatement_deadline": None,
        "reinstatement_count": 0,
        "termination_reason": None,
    })
    apply_msp(enrollment, retiree)
    db.enrollments[enrollment["id"]] = enrollment

    adjust_enrolled_count(option["id"], 1)

    event["status"] = "APPROVED"
    event["resulting_enrollment_id"] = enrollment["id"]
    touch(event)
    return object_response(event)
