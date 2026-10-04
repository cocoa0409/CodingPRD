"""Employer self-registration, domain verification, and fraud screening."""

from flask import Blueprint

import db
from db import wall_now
from errors import fail
from services import (
    employer_view,
    fraud_analyst_score,
    fraud_auto_score,
    tier_for,
)
from util import Body, get_context, require_role, success_object

bp = Blueprint("employers", __name__)

SCREEN_DECISIONS = ("CLEAR", "FLAG", "REJECT")


@bp.route("/employers", methods=["POST"])
def create_employer():
    _user_id, role = get_context()
    require_role(role, "Anonymous")
    body = Body()
    company_name = body.str_f("company_name", required=True)
    website_domain = body.str_f("website_domain", required=True)
    contact_email = body.str_f("contact_email", required=True)
    body.finalize()
    record = {
        "id": db.new_id(),
        "company_name": company_name,
        "website_domain": website_domain,
        "contact_email": contact_email,
        "status": "PENDING",
        "domain_verification_token": db.new_id(),
        "fraud_risk_score": None,
        "trust_tier": None,
        "screen_count": 0,
        "last_trust_decision_at": None,
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("employers", record)
    return success_object(employer_view(record), 201)


@bp.route("/employers/<employer_id>", methods=["GET"])
def get_employer(employer_id):
    user_id, role = get_context()
    require_role(role, "PlatformAdmin", "EmployerRecruiter", "CareerCenterAdmin")
    employer = db.get("employers", employer_id)
    if employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer id does not exist")
    if role == "EmployerRecruiter" and user_id != employer["id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may read only their own employer")
    return success_object(employer_view(employer))


@bp.route("/employers/<employer_id>/verify-domain", methods=["POST"])
def verify_domain(employer_id):
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter")
    employer = db.get("employers", employer_id)
    if employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer id does not exist")
    if user_id != employer["id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may verify only their own employer")
    body = Body()
    token = body.str_f("verification_token", required=True)
    # Priority 5 state before priority 7 token safety gate.
    if employer["status"] != "PENDING":
        fail("ERR_INVALID_EMPLOYER_TRANSITION",
             "Domain verification requires status PENDING")
    if token is not None and token != employer["domain_verification_token"]:
        fail("ERR_DOMAIN_VERIFICATION_FAILED", "verification_token does not match")
    body.finalize()
    employer["status"] = "DOMAIN_VERIFIED"
    employer["fraud_risk_score"] = fraud_auto_score(employer)
    employer["trust_tier"] = tier_for(employer["fraud_risk_score"])
    db.touch(employer)
    return success_object(employer_view(employer))


@bp.route("/employers/<employer_id>/screen", methods=["POST"])
def screen_employer(employer_id):
    _user_id, role = get_context()
    require_role(role, "PlatformAdmin")
    employer = db.get("employers", employer_id)
    if employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer id does not exist")
    body = Body()
    decision = body.str_f("decision", required=True, enum=SCREEN_DECISIONS)
    adjustment = body.int_f("analyst_signal_adjustment", minv=-40, maxv=40)
    if adjustment is None:
        adjustment = 0
    status = employer["status"]
    new_score = None
    new_tier = None
    if decision == "CLEAR":
        if status == "PENDING":
            fail("ERR_EMPLOYER_NOT_DOMAIN_VERIFIED",
                 "CLEAR requires a domain-verified employer")
        if status not in ("DOMAIN_VERIFIED", "UNDER_REVIEW"):
            fail("ERR_INVALID_EMPLOYER_TRANSITION",
                 "CLEAR is not allowed from status %s" % status)
        new_score = fraud_analyst_score(employer, adjustment, decision)
        new_tier = tier_for(new_score)
        if new_tier == "HIGH_RISK":
            fail("ERR_FRAUD_RISK_TOO_HIGH",
                 "CLEAR would leave trust_tier HIGH_RISK")
    elif decision == "FLAG":
        if status == "PENDING":
            fail("ERR_EMPLOYER_NOT_DOMAIN_VERIFIED",
                 "FLAG requires a domain-verified employer")
        if status not in ("DOMAIN_VERIFIED", "APPROVED"):
            fail("ERR_INVALID_EMPLOYER_TRANSITION",
                 "FLAG is not allowed from status %s" % status)
        new_score = fraud_analyst_score(employer, adjustment, decision)
        new_tier = tier_for(new_score)
    elif decision == "REJECT":
        if status not in ("PENDING", "DOMAIN_VERIFIED", "UNDER_REVIEW"):
            fail("ERR_INVALID_EMPLOYER_TRANSITION",
                 "REJECT is not allowed from status %s" % status)
        # REJECT does not recompute the score.
    body.finalize()
    if decision == "CLEAR":
        employer["fraud_risk_score"] = new_score
        employer["trust_tier"] = new_tier
        employer["status"] = "APPROVED"
    elif decision == "FLAG":
        employer["fraud_risk_score"] = new_score
        employer["trust_tier"] = new_tier
        employer["status"] = "UNDER_REVIEW"
    else:
        employer["status"] = "REJECTED"
    employer["screen_count"] += 1
    db.touch(employer)
    return success_object(employer_view(employer))
