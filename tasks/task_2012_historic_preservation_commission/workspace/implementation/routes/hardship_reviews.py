"""Economic hardship reviews (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_FORBIDDEN_ROLE, ERR_INVALID_STATE, ERR_HARDSHIP_WINDOW_LAPSED,
)
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.helpers import public, list_response, get_one
from services.calculations import (
    HARDSHIP_FILING_CUTOFF_DAYS, HARDSHIP_LIFT_DAYS, provisional_delay_end,
    lazy_expire_delay,
)
from services.core import new_record, touch, delay_for_application
from util import CLOCK, parse_dt, fmt_dt, add_days
from validate import (
    get_body, req_str, req_enum, req_int, req_number, require_path_resource,
    require_body_ref,
)

bp = Blueprint("hardship_reviews", __name__, url_prefix="/preservation")

APPROVAL_TERMINAL = {"APPROVED", "APPROVED_WITH_CONDITIONS", "APPROVED_ON_APPEAL"}
HARDSHIP_OUTCOMES = {"GRANT", "DENY"}
COMMISSIONER = ["Commissioner"]


@bp.post("/hardship-reviews")
def create_hardship():
    caller = get_caller()
    body = get_body()
    application_id = req_str(body, "application_id")
    claimed_rate_of_return_pct = req_number(body, "claimed_rate_of_return_pct")
    appraisal_basis_cents = req_int(body, "appraisal_basis_cents", minimum=0)
    check_role_allowed(caller, ["Applicant"])
    app = require_body_ref("applications", application_id, "application_id")
    # Layer 2: own applications only.
    if caller.user_id != app["owner_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the owning applicant may file a hardship review")
    # Layer 5: an approved DEMOLITION application with a live delay record.
    if app["application_type"] != "DEMOLITION" or app["status"] not in APPROVAL_TERMINAL:
        raise_error(ERR_INVALID_STATE,
                    "hardship review requires an approved DEMOLITION application")
    delay = delay_for_application(app["id"])
    if delay is None:
        raise_error(ERR_INVALID_STATE, "no demolition delay exists for this application")
    # Layer 8: filing window (decided_at, provisional_delay_end - 30 days].
    filed_dt = CLOCK.now()
    decided_dt = parse_dt(app["decided_at"])
    cutoff = add_days(provisional_delay_end(delay), -HARDSHIP_FILING_CUTOFF_DAYS)
    if filed_dt <= decided_dt or filed_dt > cutoff:
        raise_error(ERR_HARDSHIP_WINDOW_LAPSED,
                    "hardship filing must be strictly after the decision and no later "
                    "than provisional_delay_end - 30 days")
    rec = new_record("hardship_reviews", {
        "application_id": app["id"],
        "filed_at": fmt_dt(filed_dt),
        "claimed_rate_of_return_pct": claimed_rate_of_return_pct,
        "appraisal_basis_cents": appraisal_basis_cents,
        "findings": None,
        "decided_at": None,
        "status": "FILED",
    })
    return success_object(public(rec), status=201)


@bp.get("/hardship-reviews")
def list_hardship_reviews():
    filters = {
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    }
    return list_response("hardship_reviews", filters)


@bp.get("/hardship-reviews/<rid>")
def get_hardship_review(rid):
    return get_one("hardship_reviews", rid)


@bp.post("/hardship-reviews/<rid>/hear")
def hear_hardship(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, COMMISSIONER)
    review = require_path_resource("hardship_reviews", rid)
    if review["status"] != "FILED":
        raise_error(ERR_INVALID_STATE, f"hear requires FILED, got {review['status']}")
    review["status"] = "HEARD"
    touch(review)
    return success_object(public(review))


@bp.post("/hardship-reviews/<rid>/decide")
def decide_hardship(rid):
    caller = get_caller()
    body = get_body()
    outcome = req_enum(body, "outcome", HARDSHIP_OUTCOMES)
    findings = req_str(body, "findings")
    check_role_allowed(caller, COMMISSIONER)
    review = require_path_resource("hardship_reviews", rid)
    if review["status"] != "HEARD":
        raise_error(ERR_INVALID_STATE, f"decide requires HEARD, got {review['status']}")

    decided_dt = CLOCK.now()
    review["decided_at"] = fmt_dt(decided_dt)
    review["findings"] = findings
    if outcome == "GRANT":
        review["status"] = "GRANTED"
        delay = delay_for_application(review["application_id"])
        if delay is not None:
            lazy_expire_delay(delay)
            if delay["status"] == "ACTIVE":
                delay["status"] = "LIFTED_BY_HARDSHIP"
                delay["final_delay_end"] = fmt_dt(add_days(decided_dt, HARDSHIP_LIFT_DAYS))
                touch(delay)
    else:
        review["status"] = "DENIED"
    touch(review)
    return success_object(public(review))
