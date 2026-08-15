"""Violations, civil penalties, and after-the-fact legalization (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_LINKED_APPLICATION_NOT_APPROVED,
    ERR_ESCALATION_THRESHOLD_NOT_MET,
)
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.helpers import public, list_response, get_one
from services.calculations import demand_letter_penalty, final_penalty
from services.core import (
    new_record, touch, recompute_property_enforcement,
    linked_after_fact_application,
)
from util import CLOCK, fmt_dt, whole_days_between, parse_dt
from validate import (
    get_body, req_str, req_datetime, require_path_resource, require_body_ref,
)

bp = Blueprint("violations", __name__, url_prefix="/preservation")

OFFICER = ["EnforcementOfficer"]
APPROVAL_TERMINAL = {"APPROVED", "APPROVED_WITH_CONDITIONS", "APPROVED_ON_APPEAL"}
ESCALATION_DAYS = 60


@bp.post("/violations")
def create_violation():
    caller = get_caller()
    body = get_body()
    property_id = req_str(body, "property_id")
    observed_violation_date = req_datetime(body, "observed_violation_date")
    work_description = req_str(body, "work_description")
    check_role_allowed(caller, OFFICER)
    require_body_ref("properties", property_id, "property_id")
    rec = new_record("violations", {
        "property_id": property_id,
        "observed_violation_date": fmt_dt(observed_violation_date),
        "work_description": work_description,
        "notice_issued_at": None,
        "demand_letter_amount_cents": None,
        "compliance_verified_at": None,
        "referred_at": None,
        "final_penalty_cents": None,
        "penalty_capped": False,
        "status": "OPEN",
    })
    recompute_property_enforcement(property_id)
    return success_object(public(rec), status=201)


@bp.get("/violations")
def list_violations():
    filters = {
        "property_id": request.args.get("property_id"),
        "status": request.args.get("status"),
    }
    return list_response("violations", filters)


@bp.get("/violations/<rid>")
def get_violation(rid):
    return get_one("violations", rid)


@bp.post("/violations/<rid>/issue-notice")
def issue_notice(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, OFFICER)
    violation = require_path_resource("violations", rid)
    if violation["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    f"issue-notice requires OPEN, got {violation['status']}")
    violation["notice_issued_at"] = CLOCK.now_iso()
    prop = db["properties"].get(violation["property_id"])
    violation["demand_letter_amount_cents"] = demand_letter_penalty(violation, prop)
    violation["status"] = "NOTICE_ISSUED"
    touch(violation)
    return success_object(public(violation))


@bp.post("/violations/<rid>/verify-compliance")
def verify_compliance(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, OFFICER)
    violation = require_path_resource("violations", rid)
    if violation["status"] not in ("NOTICE_ISSUED", "AFTER_THE_FACT_PENDING"):
        raise_error(ERR_INVALID_STATE,
                    f"verify-compliance requires NOTICE_ISSUED or AFTER_THE_FACT_PENDING, "
                    f"got {violation['status']}")
    # Layer 7 (referential): a violation awaiting an after-the-fact decision can
    # be verified by the officer only once the linked application is approved.
    if violation["status"] == "AFTER_THE_FACT_PENDING":
        app = linked_after_fact_application(violation["id"])
        if app is not None and app["status"] not in APPROVAL_TERMINAL:
            raise_error(ERR_LINKED_APPLICATION_NOT_APPROVED,
                        "the linked after-the-fact application is not in an approval state")

    verified_dt = CLOCK.now()
    violation["compliance_verified_at"] = fmt_dt(verified_dt)
    prop = db["properties"].get(violation["property_id"])
    if prop is not None:
        penalty, capped = final_penalty(violation, prop, verified_dt)
        violation["final_penalty_cents"] = penalty
        violation["penalty_capped"] = capped
    violation["status"] = "COMPLIANCE_VERIFIED"
    touch(violation)
    if prop is not None:
        recompute_property_enforcement(prop["id"])
    return success_object(public(violation))


@bp.post("/violations/<rid>/refer-court")
def refer_court(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, OFFICER)
    violation = require_path_resource("violations", rid)
    if violation["status"] != "NOTICE_ISSUED":
        raise_error(ERR_INVALID_STATE,
                    f"refer-court requires NOTICE_ISSUED, got {violation['status']}")
    # Layer 8 (temporal): more than 60 whole days must have elapsed since notice.
    elapsed = whole_days_between(parse_dt(violation["notice_issued_at"]), CLOCK.now())
    if elapsed <= ESCALATION_DAYS:
        raise_error(ERR_ESCALATION_THRESHOLD_NOT_MET,
                    f"only {elapsed} whole days since notice; court referral needs more than 60")
    violation["referred_at"] = CLOCK.now_iso()
    violation["status"] = "COURT_REFERRAL"
    touch(violation)
    return success_object(public(violation))


@bp.post("/violations/<rid>/close")
def close_violation(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, OFFICER)
    violation = require_path_resource("violations", rid)
    if violation["status"] not in ("COMPLIANCE_VERIFIED", "COURT_REFERRAL"):
        raise_error(ERR_INVALID_STATE,
                    f"close requires COMPLIANCE_VERIFIED or COURT_REFERRAL, got {violation['status']}")
    if violation["status"] == "COURT_REFERRAL" and violation.get("final_penalty_cents") is None:
        # Accrual stopped at the referral instant.
        prop = db["properties"].get(violation["property_id"])
        if prop is not None:
            penalty, capped = final_penalty(violation, prop, parse_dt(violation["referred_at"]))
            violation["final_penalty_cents"] = penalty
            violation["penalty_capped"] = capped
    violation["status"] = "CLOSED"
    touch(violation)
    return success_object(public(violation))
