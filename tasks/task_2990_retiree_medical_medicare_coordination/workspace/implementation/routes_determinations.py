"""EligibilityDetermination endpoints: rule evaluation, certification, appeal
and supersession (PRD 3.3, 3.4)."""

from flask import Blueprint, request

import calc
import errors
from auth import (ALL_ROLES, ROLE_COMPLIANCE_OFFICER, ROLE_ELIGIBILITY_ANALYST,
                  ROLE_ENROLLMENT_COUNSELOR, ROLE_RETIREE, require_caller,
                  require_ownership)
from domain import body_reference, get_determination, get_plan_year, get_retiree
from envelope import object_response, paginate
from errors import fail
from store import base_record, db, now, order_asc, touch
from validate import read_body

bp = Blueprint("determinations", __name__)

DETERMINATION_STATUSES = ("DRAFT", "CERTIFIED", "UNDER_APPEAL", "SUPERSEDED")
OUTCOMES = ("ELIGIBLE", "INELIGIBLE")
APPEAL_DECISIONS = ("UPHOLD", "REVERSE")
NON_SUPERSEDED = ("DRAFT", "CERTIFIED", "UNDER_APPEAL")


@bp.post("/retiree-benefits/eligibility-determinations")
def create_determination():
    caller = require_caller((ROLE_ELIGIBILITY_ANALYST,))
    body = read_body()
    plan_year = body_reference(body, "plan_year_id", get_plan_year)
    retiree = body_reference(body, "retiree_id", get_retiree)

    retiree_id = body.string("retiree_id")
    plan_year_id = body.string("plan_year_id")
    expected_version = body.integer("expected_retiree_version")

    if expected_version != retiree["version"]:
        fail(errors.ERR_STALE_RETIREE_VERSION)

    if plan_year["status"] != "OPEN":
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN)

    superseded = order_asc([d for d in db.determinations.values()
                            if d["retiree_id"] == retiree_id
                            and d["plan_year_id"] == plan_year_id
                            and d["status"] in NON_SUPERSEDED])
    for prior in superseded:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    group = retiree["grandfathered_group"]
    age_years = calc.completed_age_years(retiree["birth_date"],
                                         retiree["retirement_date"])
    service_years = calc.service_years(retiree["credited_service_months"])

    record = base_record()
    record.update({
        "retiree_id": retiree_id,
        "plan_year_id": plan_year_id,
        "rule_set_code": calc.rule_set_code(group),
        "grandfathered_group": group,
        "age_years_at_retirement": age_years,
        "service_years": service_years,
        "points": age_years + service_years,
        "outcome": calc.evaluate_eligibility(group, age_years, service_years),
        "status": "DRAFT",
        "created_by_user_id": caller.user_id,
        "certified_by_user_id": None,
        "appeal_reason": None,
        "appeal_decided_by_user_id": None,
        "appeal_decision": None,
        "certified_at": None,
    })
    db.determinations[record["id"]] = record

    retiree["determination_sequence"] += 1
    retiree["eligibility_points"] = calc.eligibility_points(retiree)
    touch(retiree)

    return object_response(record, 201)


@bp.get("/retiree-benefits/eligibility-determinations/<determination_id>")
def read_determination(determination_id):
    require_caller(ALL_ROLES)
    return object_response(get_determination(determination_id))


@bp.get("/retiree-benefits/eligibility-determinations")
def list_determinations():
    require_caller(ALL_ROLES)
    rows = list(db.determinations.values())
    for field in ("retiree_id", "plan_year_id", "status", "outcome"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/eligibility-determinations/<determination_id>/certify")
def certify_determination(determination_id):
    caller = require_caller((ROLE_ELIGIBILITY_ANALYST, ROLE_COMPLIANCE_OFFICER))
    determination = get_determination(determination_id)

    if determination["status"] != "DRAFT":
        fail(errors.ERR_INVALID_DETERMINATION_STATE,
             "Certification requires a DRAFT determination.")

    plan_year = db.plan_years.get(determination["plan_year_id"])
    if plan_year is None or plan_year["status"] not in ("DRAFT", "OPEN"):
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN,
             "Certification requires the governing plan year to be DRAFT or OPEN.")

    if determination["created_by_user_id"] is not None \
            and caller.user_id == determination["created_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The analyst who created the determination may not certify it.")

    determination["status"] = "CERTIFIED"
    determination["certified_by_user_id"] = caller.user_id
    determination["certified_at"] = now()
    touch(determination)

    retiree = db.retirees.get(determination["retiree_id"])
    if retiree is not None:
        retiree["eligibility_status"] = determination["outcome"]
        touch(retiree)

    touch(plan_year)
    return object_response(determination)


@bp.post("/retiree-benefits/eligibility-determinations/<determination_id>/appeal")
def open_appeal(determination_id):
    caller = require_caller((ROLE_RETIREE, ROLE_ENROLLMENT_COUNSELOR))
    determination = get_determination(determination_id)
    require_ownership(caller, determination["retiree_id"])
    body = read_body()
    appeal_reason = body.string("appeal_reason")

    if determination["status"] != "CERTIFIED":
        fail(errors.ERR_INVALID_DETERMINATION_STATE,
             "Opening an appeal requires a CERTIFIED determination.")

    determination["status"] = "UNDER_APPEAL"
    determination["appeal_reason"] = appeal_reason
    touch(determination)

    retiree = db.retirees.get(determination["retiree_id"])
    if retiree is not None:
        retiree["eligibility_status"] = "UNDETERMINED"
        touch(retiree)

    return object_response(determination)


@bp.post("/retiree-benefits/eligibility-determinations/<determination_id>"
         "/appeal-decision")
def decide_appeal(determination_id):
    caller = require_caller((ROLE_COMPLIANCE_OFFICER,))
    determination = get_determination(determination_id)
    body = read_body()
    decision = body.enum("decision", APPEAL_DECISIONS)

    if determination["status"] != "UNDER_APPEAL":
        fail(errors.ERR_INVALID_DETERMINATION_STATE,
             "Deciding an appeal requires an UNDER_APPEAL determination.")

    if determination["certified_by_user_id"] is not None \
            and caller.user_id == determination["certified_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The certifying user may not decide the appeal.")

    if decision == "REVERSE":
        determination["outcome"] = (
            "INELIGIBLE" if determination["outcome"] == "ELIGIBLE" else "ELIGIBLE")

    determination["status"] = "CERTIFIED"
    determination["appeal_decision"] = decision
    determination["appeal_decided_by_user_id"] = caller.user_id
    determination["certified_at"] = now()
    touch(determination)

    retiree = db.retirees.get(determination["retiree_id"])
    if retiree is not None:
        retiree["eligibility_status"] = determination["outcome"]
        touch(retiree)

    return object_response(determination)
