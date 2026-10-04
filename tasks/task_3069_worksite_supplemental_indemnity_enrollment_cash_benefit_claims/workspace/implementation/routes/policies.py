"""Policy endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors as E
import services
from middleware import require_role
from response import success_object
from serializers import policy as policy_ser
from util import get_body, get_or_404, list_response, parse_iso

bp = Blueprint("policies", __name__)

STORE = db.STORES["policies"]


@bp.route("/policies", methods=["POST"])
def create(role, user_id):
    require_role(role, {"BenefitCounselor"})
    body = get_body(["campaign_id", "employee_id", "policy_series_id"])
    campaign = db.STORES["enrollment_campaigns"].get(body["campaign_id"])
    if campaign is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "campaign_id does not exist")
    employee = db.STORES["employees"].get(body["employee_id"])
    if employee is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "employee_id does not exist")
    series = db.STORES["policy_series"].get(body["policy_series_id"])
    if series is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "policy_series_id does not exist")
    if series["status"] == "RETIRED":
        raise E.err(E.ERR_SERIES_RETIRED, "Policy series is RETIRED")
    if campaign["status"] != "OPEN":
        raise E.err(E.ERR_INVALID_STATE, f"Campaign is {campaign['status']}")
    now = clock.now()
    ws = parse_iso(campaign["window_start"])
    we = parse_iso(campaign["window_end"])
    if not (ws <= now < we):
        raise E.err(E.ERR_WINDOW_EXPIRED, "Current clock is outside the enrollment window")
    premium_mode = body.get("premium_mode", "POST_TAX")
    if premium_mode not in ("PRE_TAX", "POST_TAX"):
        raise E.err(E.ERR_INVALID_REQUEST, "premium_mode must be PRE_TAX or POST_TAX")
    rec = db.stamp_created({
        "campaign_id": campaign["id"],
        "employee_id": employee["id"],
        "policy_series_id": series["id"],
        "benefit_schedule_id": None,
        "certificate_number": None,
        "premium_mode": premium_mode,
        "monthly_premium_cents": None,
        "issue_date": None,
        "coverage_start_date": None,
        "lifetime_paid_cents": 0,
        "paid_occurrences_by_year": {},
        "status": "APPLIED",
    })
    STORE[rec["id"]] = rec
    return success_object(policy_ser(rec), status=201)


@bp.route("/policies/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor", "ClaimsAdjuster", "PolicyholderServices"})
    rec = get_or_404(STORE, rid)
    return success_object(policy_ser(rec))


@bp.route("/policies", methods=["GET"])
def list_all(role, user_id):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor", "ClaimsAdjuster", "PolicyholderServices"})
    filters = {
        "campaign_id": request.args.get("campaign_id"),
        "employee_id": request.args.get("employee_id"),
        "policy_series_id": request.args.get("policy_series_id"),
        "benefit_schedule_id": request.args.get("benefit_schedule_id"),
        "status": request.args.get("status"),
    }
    return list_response(STORE, filters, policy_ser)


@bp.route("/policies/<rid>/issue", methods=["POST"])
def issue(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "APPLIED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot issue from {rec['status']}")
    result = services.issue_policy(rec)
    if result and result[0] == "DECLINED":
        services.decline_policy(rec)
    return success_object(policy_ser(rec))


@bp.route("/policies/<rid>/activate", methods=["POST"])
def activate(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "ISSUED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot activate from {rec['status']}")
    employee = db.STORES["employees"][rec["employee_id"]]
    if employee["status"] != "ACTIVE":
        raise E.err(E.ERR_EMPLOYEE_INACTIVE, "Employee is not ACTIVE")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success_object(policy_ser(rec))


@bp.route("/policies/<rid>/lapse", methods=["POST"])
def lapse(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] not in ("ISSUED", "ACTIVE"):
        raise E.err(E.ERR_INVALID_STATE, f"Cannot lapse from {rec['status']}")
    services.lapse_policy(rec)
    return success_object(policy_ser(rec))


@bp.route("/policies/<rid>/reinstate", methods=["POST"])
def reinstate(role, user_id, rid):
    require_role(role, {"BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "LAPSED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot reinstate from {rec['status']}")
    lapsed_at = parse_iso(rec.get("_lapsed_at"), "_lapsed_at") if rec.get("_lapsed_at") else clock.now()
    now = clock.now()
    if now - lapsed_at > timedelta(days=60):
        raise E.err(E.ERR_REINSTATEMENT_WINDOW_EXPIRED, "Lapsed more than 60 days ago")
    employee = db.STORES["employees"][rec["employee_id"]]
    if employee["status"] != "ACTIVE":
        raise E.err(E.ERR_EMPLOYEE_INACTIVE, "Employee is not ACTIVE")
    campaign = db.STORES["enrollment_campaigns"][rec["campaign_id"]]
    group = db.STORES["employer_groups"][campaign["employer_group_id"]]
    if group["status"] != "ACTIVE":
        raise E.err(E.ERR_GROUP_INACTIVE, "Employer group is not ACTIVE")
    rec["status"] = "ACTIVE"
    # coverage_start_date unchanged (continuous coverage)
    db.touch(rec)
    return success_object(policy_ser(rec))


@bp.route("/policies/<rid>/port", methods=["POST"])
def port(role, user_id, rid):
    require_role(role, {"PolicyholderServices"})
    rec = get_or_404(STORE, rid)
    if rec["status"] not in ("ISSUED", "ACTIVE"):
        raise E.err(E.ERR_INVALID_STATE, f"Cannot port from {rec['status']}")
    employee = db.STORES["employees"][rec["employee_id"]]
    if employee["status"] != "TERMINATED":
        raise E.err(E.ERR_PORT_NOT_ELIGIBLE, "Employee is not TERMINATED")
    body = request.get_json(silent=True) or {}
    new_mode = body.get("new_premium_mode")
    if new_mode not in ("PRE_TAX", "POST_TAX"):
        raise E.err(E.ERR_INVALID_REQUEST, "new_premium_mode must be PRE_TAX or POST_TAX")
    # Ported policies are direct-billed: premium_mode forced to POST_TAX regardless
    rec["premium_mode"] = "POST_TAX"
    rec["status"] = "PORTED"
    db.touch(rec)
    return success_object(policy_ser(rec))


@bp.route("/policies/<rid>/cancel", methods=["POST"])
def cancel(role, user_id, rid):
    require_role(role, {"PolicyholderServices"})
    rec = get_or_404(STORE, rid)
    if rec["status"] not in ("LAPSED", "PORTED"):
        raise E.err(E.ERR_INVALID_STATE, f"Cannot cancel from {rec['status']}")
    for c in db.STORES["claims"].values():
        if c["policy_id"] == rec["id"] and c["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPEALED", "APPROVED"):
            raise E.err(E.ERR_CLAIMS_IN_FLIGHT, "Policy has claims in flight")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success_object(policy_ser(rec))
