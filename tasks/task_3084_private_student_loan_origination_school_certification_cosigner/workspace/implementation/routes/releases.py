"""CosignerReleaseApplication routes (PRD 3.8)."""

from flask import Blueprint, request

from db import db
from common import stamp, touch, body_of, required
from errors import fail
from middleware import guard, require_borrower_owns
from response import object_body, array_body
import engine
import calc

bp = Blueprint("releases", __name__)
PREFIX = "/private-student-loans"


def _resolve_release(rid):
    record = db.release_applications.get(rid)
    if record is None:
        fail("ERR_LOAN_CHILD_NOT_FOUND", "release application %s does not exist" % rid)
    return record


@bp.route(PREFIX + "/loans/<lid>/cosigner-release-applications", methods=["POST"])
@guard("Borrower", "Cosigner")
def file_release(lid, _user_id=None, _role=None):
    loan = engine.get_loan(lid)
    data = body_of(request)
    cosigner_id = required(data, "cosigner_id")
    cosigner = engine.get_cosigner(cosigner_id)
    if _role == "Cosigner":
        if _user_id != cosigner["id"]:
            fail("ERR_FORBIDDEN", "acting cosigner is not this record")

    # priority 23: the loan must carry this cosigner, ELIGIBLE.
    if loan.get("cosigner_id") != cosigner_id or cosigner.get("underwriting_status") != "ELIGIBLE":
        fail("ERR_COSIGNER_NOT_ELIGIBLE",
             "loan %s does not carry an ELIGIBLE cosigner %s" % (lid, cosigner_id))

    policy = engine.get_policy(loan["policy_id"])
    required_min = int(policy.get("cosigner_release_min_on_time_payments",
                                  engine.POLICY_DEFAULTS["cosigner_release_min_on_time_payments"]))
    borrower = db.borrowers.get(loan["borrower_id"])
    run = int(borrower.get("on_time_payment_run_count", 0)) if borrower else 0

    # priority 30: the frozen run must already reach the required minimum.
    if run < required_min:
        fail("ERR_RELEASE_RUN_INSUFFICIENT",
             "the qualifying payment run is below the required minimum")

    record = {
        "loan_id": loan["id"],
        "cosigner_id": cosigner_id,
        "payments_at_application": run,
        "independent_credit_score": data.get("independent_credit_score"),
        "independent_dti_ratio": data.get("independent_dti_ratio"),
        "required_min_payments": required_min,
        "run_at_submission": run,
        "release_status": "SUBMITTED",
        "deficiency_reason": None,
    }
    stamp(record, new=True)
    record["release_status"] = "UNDER_REVIEW"
    db.release_applications[record["id"]] = record
    touch(loan)
    return object_body(engine.ser_release(record), 201)


@bp.route(PREFIX + "/loans/<lid>/cosigner-release-applications", methods=["GET"])
@guard("Borrower", "Cosigner", "Underwriter", "Servicer")
def list_loan_releases(lid, _user_id=None, _role=None):
    engine.get_loan(lid)
    records = engine.sort_by_created(engine.releases_of(lid))
    return array_body([engine.ser_release(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/cosigner-release-applications/<rid>", methods=["GET"])
@guard("Borrower", "Cosigner", "Underwriter", "Servicer")
def read_release(rid, _user_id=None, _role=None):
    record = _resolve_release(rid)
    return object_body(engine.ser_release(record))


@bp.route(PREFIX + "/cosigner-release-applications/<rid>/decision", methods=["POST"])
@guard("Underwriter")
def decide_release(rid, _user_id=None, _role=None):
    record = _resolve_release(rid)
    loan = engine.get_loan(record["loan_id"])
    data = body_of(request)
    decision = required(data, "decision")
    if record.get("release_status") != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "release application %s is not UNDER_REVIEW" % rid)

    policy = engine.get_policy(loan["policy_id"])
    min_score = int(policy.get("cosigner_release_min_credit_score",
                               engine.POLICY_DEFAULTS["cosigner_release_min_credit_score"]))
    max_dti = float(policy.get("cosigner_release_max_dti_ratio",
                               engine.POLICY_DEFAULTS["cosigner_release_max_dti_ratio"]))

    if decision == "APPROVE":
        # priority 16 (business_safety) is evaluated before priority 33
        # (fiscal): the notification obligation must first be SATISFIED.
        if loan.get("notice_obligation_status") == "PENDING":
            fail("ERR_NOTICE_OBLIGATION_PENDING",
                 "the cosigner notification obligation is still PENDING")
        # priority 33: a DELINQUENT/DEFAULT loan cannot accept a release approval.
        if loan.get("loan_status") in ("DELINQUENT", "DEFAULT"):
            fail("ERR_LOAN_DELINQUENT",
                 "loan %s cannot accept a cosigner-release approval" % loan["id"])
        _evaluate_gates(record, loan, min_score, max_dti)
        record["release_status"] = "APPROVED"
        record["deficiency_reason"] = None
        touch(record)
        _propagate_release(record, loan)
        touch(loan)
        return object_body(engine.ser_release(record))

    if decision == "DECLINE":
        reason = _first_failing_gate(record, loan, min_score, max_dti)
        record["release_status"] = "DECLINED"
        record["deficiency_reason"] = reason
        touch(record)
        touch(loan)
        return object_body(engine.ser_release(record))

    fail("ERR_INVALID_REQUEST", "decision must be APPROVE or DECLINE")


def _first_failing_gate(record, loan, min_score, max_dti):
    required_min = int(record.get("required_min_payments") or 0)
    run = int(record.get("run_at_submission") or 0)
    if run < required_min:
        return "INSUFFICIENT_PAYMENTS"
    score = record.get("independent_credit_score")
    dti = record.get("independent_dti_ratio")
    if score is None or int(score) < min_score:
        return "CREDIT_SCORE"
    if dti is None or float(dti) > max_dti:
        return "DTI"
    if calc.release_score(int(score), float(dti), run, required_min) < 500:
        return "RELEASE_SCORE"
    if loan.get("loan_status") in ("DELINQUENT", "DEFAULT"):
        return "DELINQUENT_LOAN"
    return "RELEASE_SCORE"


def _evaluate_gates(record, loan, min_score, max_dti):
    required_min = int(record.get("required_min_payments") or 0)
    run = int(record.get("run_at_submission") or 0)
    score = record.get("independent_credit_score")
    dti = record.get("independent_dti_ratio")
    if run < required_min:
        fail("ERR_RELEASE_RUN_INSUFFICIENT", "the frozen run is below the required minimum")
    if score is None or int(score) < min_score:
        fail("ERR_RELEASE_UNDERWRITING_FAILED", "independent credit score is below the policy floor")
    if dti is None or float(dti) > max_dti:
        fail("ERR_RELEASE_UNDERWRITING_FAILED", "independent DTI exceeds the policy ceiling")
    if calc.release_score(int(score), float(dti), run, required_min) < 500:
        fail("ERR_RELEASE_UNDERWRITING_FAILED", "release score is below 500")


def _propagate_release(record, loan):
    cosigner = db.cosigners.get(record.get("cosigner_id"))
    if cosigner is not None:
        cosigner["underwriting_status"] = "RELEASED"
        touch(cosigner)
    for other in db.loans.values():
        if other.get("cosigner_id") == record.get("cosigner_id"):
            other["cosigner_id"] = None
            touch(other)


@bp.route(PREFIX + "/cosigner-release-applications/<rid>/reapply", methods=["POST"])
@guard("Borrower")
def reapply_release(rid, _user_id=None, _role=None):
    record = _resolve_release(rid)
    loan = engine.get_loan(record["loan_id"])
    require_borrower_owns(_user_id, loan["borrower_id"])
    if record.get("release_status") != "DECLINED":
        fail("ERR_INVALID_STATE", "release application %s is not DECLINED" % rid)
    borrower = db.borrowers.get(loan["borrower_id"])
    run = int(borrower.get("on_time_payment_run_count", 0)) if borrower else 0
    record["payments_at_application"] = run
    record["run_at_submission"] = run
    record["deficiency_reason"] = None
    record["release_status"] = "SUBMITTED"
    touch(record)
    record["release_status"] = "UNDER_REVIEW"
    return object_body(engine.ser_release(record))


@bp.route(PREFIX + "/cosigner-release-applications/<rid>/withdraw", methods=["POST"])
@guard("Borrower")
def withdraw_release(rid, _user_id=None, _role=None):
    record = _resolve_release(rid)
    loan = engine.get_loan(record["loan_id"])
    require_borrower_owns(_user_id, loan["borrower_id"])
    if record.get("release_status") not in ("SUBMITTED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE", "release application %s cannot be withdrawn" % rid)
    record["release_status"] = "WITHDRAWN"
    touch(record)
    return object_body(engine.ser_release(record))