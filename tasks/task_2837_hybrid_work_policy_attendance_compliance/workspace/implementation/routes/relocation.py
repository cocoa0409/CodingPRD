"""RemoteLocationRequest routes: two parallel review dimensions and their join."""
from flask import Blueprint

import calc
import db
import guards
import middleware
import recompute
from errors import fail
from middleware import (ALL_ROLES, COMPLIANCE_AUDITOR, EMPLOYEE, HR_BUSINESS_PARTNER,
                        PEOPLE_MANAGER, WORKPLACE_PROGRAM_OFFICE)

bp = Blueprint("relocation", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != EMPLOYEE)
JURISDICTIONS = ("US_CA", "US_TX", "US_NY", "IE", "IN", "BR")
TIERS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
OUTCOMES = ("CLEARED", "BLOCKED")
TERMINAL = ("APPROVED", "DENIED")


@bp.route("/remote-location-requests", methods=["POST"])
def create_request():
    actor = middleware.authorize((EMPLOYEE, PEOPLE_MANAGER, HR_BUSINESS_PARTNER))
    payload = middleware.body()
    employee_id = middleware.req_present(payload, "employee_id")
    employee = middleware.must_exist("employee", employee_id)
    guards.require_owner(actor, employee["id"])

    jurisdiction = middleware.req_enum(payload, "jurisdiction_code", JURISDICTIONS)
    tier = middleware.req_enum(payload, "data_classification_tier", TIERS)
    proposed_start_date = middleware.req_date(payload, "proposed_start_date")

    guards.gate_employee_active(employee)
    if not calc.approved_classifications(employee):
        fail("ERR_NO_APPROVED_CLASSIFICATION", "employee holds no APPROVED classification")
    if employee["current_eligibility_class"] == "ONSITE_REQUIRED":
        fail("ERR_CLASS_NOT_REMOTE_ELIGIBLE", "employee's eligibility class is ONSITE_REQUIRED")

    row = db.insert("remote_location_request", {
        "employee_id": employee["id"],
        "jurisdiction_code": jurisdiction,
        "data_classification_tier": tier,
        "proposed_start_date": proposed_start_date.isoformat(),
        "status": "SUBMITTED",
        "tax_review_status": "PENDING",
        "security_review_status": "PENDING",
        "licensing_gap_count": 0,
        "tax_nexus_registration_cost_cents": 0,
        "control_gap_count": 0,
        "preliminary_risk_score": calc.preliminary_risk_score(jurisdiction, tier),
        "final_risk_score": 0,
        "decision_reason": None,
    })
    return guards.single("remote_location_request", row, 201)


@bp.route("/remote-location-requests/<request_id>/tax-review", methods=["POST"])
def tax_review(request_id):
    middleware.authorize((HR_BUSINESS_PARTNER, WORKPLACE_PROGRAM_OFFICE))
    row = middleware.must_exist("remote_location_request", request_id)
    payload = middleware.body()
    outcome = middleware.req_enum(payload, "review_outcome", OUTCOMES)
    licensing_gap_count = middleware.req_int(payload, "licensing_gap_count", 0, 20)
    nexus_cents = middleware.req_int(payload, "tax_nexus_registration_cost_cents",
                                    0, 100000000)

    if row["status"] in TERMINAL or row["tax_review_status"] != "PENDING":
        fail("ERR_REVIEW_ALREADY_RECORDED", "the tax review dimension is already recorded")
    if nexus_cents > calc.TAX_NEXUS_BUDGET_CENTS:
        fail("ERR_TAX_NEXUS_BUDGET_EXCEEDED",
             "tax_nexus_registration_cost_cents exceeds the per-request budget")

    changes = {
        "tax_review_status": outcome,
        "licensing_gap_count": licensing_gap_count,
        "tax_nexus_registration_cost_cents": nexus_cents,
    }
    if row["status"] == "SUBMITTED":
        changes["status"] = "UNDER_REVIEW"
    if not db.apply_changes(row, changes):
        db.touch(row)
    return guards.single("remote_location_request", row)


@bp.route("/remote-location-requests/<request_id>/security-review", methods=["POST"])
def security_review(request_id):
    middleware.authorize((COMPLIANCE_AUDITOR, WORKPLACE_PROGRAM_OFFICE))
    row = middleware.must_exist("remote_location_request", request_id)
    payload = middleware.body()
    outcome = middleware.req_enum(payload, "review_outcome", OUTCOMES)
    control_gap_count = middleware.req_int(payload, "control_gap_count", 0, 20)

    if row["status"] in TERMINAL or row["security_review_status"] != "PENDING":
        fail("ERR_REVIEW_ALREADY_RECORDED", "the security review dimension is already recorded")

    changes = {"security_review_status": outcome, "control_gap_count": control_gap_count}
    if row["status"] == "SUBMITTED":
        changes["status"] = "UNDER_REVIEW"
    if not db.apply_changes(row, changes):
        db.touch(row)
    return guards.single("remote_location_request", row)


@bp.route("/remote-location-requests/<request_id>/decide", methods=["POST"])
def decide(request_id):
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    row = middleware.must_exist("remote_location_request", request_id)
    payload = middleware.body()
    decision = middleware.req_enum(payload, "decision", ("APPROVE", "DENY"))

    if row["status"] in TERMINAL:
        fail("ERR_RELOCATION_DECISION_FINAL", "relocation decision is already final")
    if row["tax_review_status"] == "PENDING" or row["security_review_status"] == "PENDING":
        fail("ERR_REVIEWS_INCOMPLETE", "both review dimensions must be recorded first")

    if (decision == "APPROVE"
            and row["data_classification_tier"] == "RESTRICTED"
            and row["jurisdiction_code"] not in calc.ALLOWED_RESTRICTED_JURISDICTIONS):
        fail("ERR_DATA_RESIDENCY_PROHIBITED",
             "RESTRICTED data may not be approved into this jurisdiction")

    final_score = calc.final_risk_score(row)
    if decision == "APPROVE" and final_score >= calc.APPROVAL_RISK_CEILING:
        fail("ERR_RELOCATION_RISK_CEILING",
             "final risk score has reached the approval ceiling")

    blocked = ("BLOCKED" in (row["tax_review_status"], row["security_review_status"]))
    if decision == "APPROVE" and not blocked:
        changes = {
            "status": "APPROVED",
            "final_risk_score": final_score,
            "decision_reason": "BOTH_REVIEWS_CLEARED",
        }
    else:
        changes = {
            "status": "DENIED",
            "final_risk_score": final_score,
            "decision_reason": "REVIEW_BLOCKED" if blocked else "RISK_CEILING_REACHED",
        }
    db.apply_changes(row, changes)
    return guards.single("remote_location_request", row)


@bp.route("/remote-location-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    actor = middleware.authorize(ALL_ROLES)
    row = middleware.must_exist("remote_location_request", request_id)
    guards.require_owner(actor, row["employee_id"])
    return guards.single("remote_location_request", row)


@bp.route("/remote-location-requests", methods=["GET"])
def list_requests():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("remote_location_request")
    for arg in ("employee_id", "status", "jurisdiction_code"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("remote_location_request", rows)
