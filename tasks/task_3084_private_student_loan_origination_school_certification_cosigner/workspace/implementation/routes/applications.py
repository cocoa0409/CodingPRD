"""Loan application and school certification routes."""

from datetime import datetime

from flask import Blueprint, request

from db import db, iso, parse_iso
from common import stamp, touch, body_of, required, enum
from errors import fail
from middleware import guard, require_borrower_owns, require_school_is
from response import object_body, array_body, paginate
import engine
import calc

bp = Blueprint("applications", __name__)
PREFIX = "/private-student-loans"


# ---------------------------------------------------------------------------
# applications
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loan-applications", methods=["POST"])
@guard("Borrower")
def create_application(_user_id=None, _role=None):
    data = body_of(request)
    borrower = engine.get_borrower(_user_id)
    school = engine.get_school(required(data, "school_id"))
    policy = engine.get_policy(required(data, "policy_id"))
    cosigner = None
    cosigner_id = data.get("cosigner_id")
    if cosigner_id:
        # Existence only: an unresolved cosigner (or one already RELEASED) is
        # ERR_COSIGNER_NOT_FOUND. The eligible-cosigner gate is applied by
        # combined_credit_underwriting, which excludes any cosigner that is not
        # ELIGIBLE from the evaluation.
        cosigner = engine.get_cosigner(cosigner_id)
    option = required(data, "interest_accrual_option")
    enum(option, engine.ACCRUAL_OPTIONS)

    coa = int(required(data, "cost_of_attendance_cents"))
    other_aid = int(data.get("other_aid_cents") or 0)
    record = {
        "borrower_id": borrower["id"],
        "cosigner_id": cosigner_id,
        "school_id": school["id"],
        "policy_id": policy["id"],
        "requested_amount_cents": int(required(data, "requested_amount_cents")),
        "cost_of_attendance_cents": coa,
        "other_aid_cents": other_aid,
        "interest_accrual_option": option,
        "repayment_term_months": int(required(data, "repayment_term_months")),
        "certified_limit_cents": max(0, coa - other_aid),
        "decision_path": "COSIGNER_PRIMARY" if cosigner_id else "BORROWER_STANDALONE",
        "application_status": "SUBMITTED",
    }
    stamp(record, new=True)
    # Submission is not a resting state: created in SUBMITTED and immediately
    # advanced to UNDER_REVIEW with the provisional pricing.
    record["application_status"] = "UNDER_REVIEW"
    db.applications[record["id"]] = record
    _price(record, "provisional")
    return object_body(engine.ser_application(record), 201)


def _price(app, variant):
    borrower = db.borrowers.get(app["borrower_id"])
    cosigner = db.cosigners.get(app.get("cosigner_id")) if app.get("cosigner_id") else None
    score, tier, margin = calc.price_application(borrower, cosigner, variant)
    app["combined_credit_score"] = score
    app["tier"] = tier
    app["margin_rate_pct"] = float(margin) if margin is not None else None
    return score, tier, margin


@bp.route(PREFIX + "/loan-applications/<aid>", methods=["GET"])
@guard("Borrower", "Underwriter", "School", "Servicer")
def read_application(aid, _user_id=None, _role=None):
    engine.sweep()
    record = engine.get_application(aid)
    return object_body(engine.ser_application(record))


@bp.route(PREFIX + "/loan-applications", methods=["GET"])
@guard("Underwriter", "Servicer", "PlatformAdmin")
def list_applications(_user_id=None, _role=None):
    limit = int(request.args.get("limit", 10))
    limit = max(1, min(100, limit))
    offset = max(0, int(request.args.get("offset", 0)))
    records = engine.sort_by_created(db.applications.values())
    borrower_id = request.args.get("borrower_id")
    school_id = request.args.get("school_id")
    if borrower_id:
        records = [r for r in records if r["borrower_id"] == borrower_id]
    if school_id:
        records = [r for r in records if r["school_id"] == school_id]
    page, limit, offset, total = paginate(records, limit, offset)
    return array_body([engine.ser_application(r) for r in page], limit, offset, total)


@bp.route(PREFIX + "/borrowers/<bid>/loan-applications", methods=["GET"])
@guard("Borrower", "Underwriter", "Servicer")
def borrower_applications(bid, _user_id=None, _role=None):
    engine.get_borrower(bid)
    records = [a for a in engine.sort_by_created(db.applications.values())
               if a["borrower_id"] == bid]
    return array_body([engine.ser_application(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/loan-applications/<aid>/loans", methods=["GET"])
@guard("Underwriter", "Servicer", "Borrower")
def application_loans(aid, _user_id=None, _role=None):
    engine.get_application(aid)
    engine.sweep()
    records = engine.loans_of_application(aid)
    return array_body([engine.ser_loan(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/loan-applications/<aid>/decision", methods=["POST"])
@guard("Underwriter")
def decide_application(aid, _user_id=None, _role=None):
    app = engine.get_application(aid)
    data = body_of(request)
    decision = required(data, "decision")
    if app.get("application_status") != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE",
             "application %s is not UNDER_REVIEW" % aid)

    if decision == "APPROVE":
        # Validation precedence (SCAFFOLD 1.4): standalone-borrower policy
        # gate (24) -> credit decline (25) -> amount floor (26).
        policy = engine.get_policy(app["policy_id"])
        if not app.get("cosigner_id"):
            if not policy.get("allows_standalone_borrower",
                              engine.POLICY_DEFAULTS["allows_standalone_borrower"]):
                fail("ERR_COSIGNER_REQUIRED",
                     "policy does not permit a standalone borrower file")
        score, tier, margin = _price(app, "final")
        if tier == "DECLINED":
            fail("ERR_CREDIT_DECLINED", "final combined underwriting declined the file")
        approved = min(int(app["requested_amount_cents"]), int(app["certified_limit_cents"]))
        if approved < 100000:
            fail("ERR_AMOUNT_OUT_OF_RANGE",
                 "approved amount %s is below the 100000-cent floor" % approved)
        app["approved_amount_cents"] = approved
        app["application_status"] = "APPROVED"
        app["decision_path"] = "COSIGNER_PRIMARY" if app.get("cosigner_id") else "BORROWER_STANDALONE"
        touch(app)
        _open_loan(app, margin)
        return object_body(engine.ser_application(app))

    if decision == "DENY":
        app["denial_reason"] = "CREDIT_SCORE"
        app["application_status"] = "DENIED"
        cos = db.cosigners.get(app.get("cosigner_id")) if app.get("cosigner_id") else None
        if cos is not None:
            cos["underwriting_status"] = "INELIGIBLE"
            touch(cos)
        touch(app)
        return object_body(engine.ser_application(app))

    fail("ERR_INVALID_REQUEST", "decision must be APPROVE or DENY")


def _open_loan(app, margin):
    loan = {
        "borrower_id": app["borrower_id"],
        "application_id": app["id"],
        "cosigner_id": app.get("cosigner_id"),
        "policy_id": app["policy_id"],
        "interest_accrual_option": app["interest_accrual_option"],
        "repayment_option": app["interest_accrual_option"],
        "certification_limit_cents": app["certified_limit_cents"],
        "loan_status": "APPROVED",
        "principal_cents": 0,
        "disbursed_amount_cents": 0,
        "certified_amount_cents": 0,
        "unpaid_interest_cents": 0,
        "lifetime_accrued_interest_cents": 0,
        "lifetime_capitalized_interest_cents": 0,
        "current_balance_cents": 0,
        "cumulative_deferment_months": 0,
        "earned_capitalization_count": 0,
        "lifetime_principal_reduction_cents": 0,
        "autodebit_enrolled": False,
        "days_past_due": 0,
        "delinquency_stage": "CURRENT",
        "notice_obligation_status": "NONE",
        "disburse_blocked": False,
        "_margin_rate_pct": float(margin) if margin is not None else 0.0,
        "_refunded_amount_cents": 0,
        "_principal_repaid_cents": 0,
    }
    stamp(loan, new=True)
    loan["_created_dt"] = db.now()
    db.loans[loan["id"]] = loan
    engine.refresh_loan(loan)
    engine.run_waterfall(app)
    return loan


@bp.route(PREFIX + "/loan-applications/<aid>/reconsider", methods=["POST"])
@guard("Borrower")
def reconsider_application(aid, _user_id=None, _role=None):
    app = engine.get_application(aid)
    require_borrower_owns(_user_id, app["borrower_id"])
    if app.get("application_status") != "DENIED":
        fail("ERR_INVALID_STATE", "application %s is not DENIED" % aid)
    app["application_status"] = "UNDER_REVIEW"
    app["denial_reason"] = None
    cos = db.cosigners.get(app.get("cosigner_id")) if app.get("cosigner_id") else None
    if cos is not None and cos.get("underwriting_status") == "INVITED":
        cos["underwriting_status"] = "UNDER_REVIEW"
        touch(cos)
    touch(app)
    _price(app, "provisional")
    return object_body(engine.ser_application(app))


@bp.route(PREFIX + "/loan-applications/<aid>/cancel", methods=["POST"])
@guard("Borrower")
def cancel_application(aid, _user_id=None, _role=None):
    app = engine.get_application(aid)
    require_borrower_owns(_user_id, app["borrower_id"])
    if app.get("application_status") not in ("SUBMITTED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE", "application %s cannot be cancelled" % aid)
    app["application_status"] = "CANCELLED"
    touch(app)
    for cert in engine.certs_of_application(aid):
        if cert.get("certification_status") == "REQUESTED":
            cert["certification_status"] = "EXPIRED"
            touch(cert)
    return object_body(engine.ser_application(app))


# ---------------------------------------------------------------------------
# school certifications
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loan-applications/<aid>/school-certifications", methods=["POST"])
@guard("School")
def file_certification(aid, _user_id=None, _role=None):
    app = engine.get_application(aid)
    # The certifying institution is the application's own school_id; the acting
    # school must be that institution (the body carries no school_id).
    school = engine.get_school(app["school_id"])
    require_school_is(_user_id, school["id"])
    if app.get("application_status") not in ("APPROVED", "SCHOOL_CERT_PENDING"):
        fail("ERR_INVALID_STATE", "application %s cannot accept a certification request" % aid)

    data = body_of(request)
    enrollment = required(data, "certified_enrollment_status")
    enum(enrollment, engine.ENROLLMENT_STATUSES)
    period_end = required(data, "period_end_date")
    cert = {
        "application_id": app["id"],
        "school_id": school["id"],
        "academic_period_label": required(data, "academic_period_label"),
        "requested_amount_cents": int(required(data, "certified_amount_cents")),
        "certified_amount_cents": 0,
        "certified_enrollment_status": enrollment,
        "certified_date": None,
        "certification_status": "REQUESTED",
        "rejection_reason": None,
        "period_end_date": parse_iso(period_end),
    }
    stamp(cert, new=True)
    db.certifications[cert["id"]] = cert
    app["application_status"] = "SCHOOL_CERT_PENDING"
    touch(app)
    return object_body(engine.ser_certification(cert), 201)


@bp.route(PREFIX + "/loan-applications/<aid>/school-certifications", methods=["GET"])
@guard("Borrower", "School", "Servicer", "Underwriter")
def list_application_certifications(aid, _user_id=None, _role=None):
    engine.get_application(aid)
    records = engine.certs_of_application(aid)
    return array_body([engine.ser_certification(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/school-certifications", methods=["GET"])
@guard("School", "Servicer", "PlatformAdmin")
def list_certifications(_user_id=None, _role=None):
    limit = max(1, min(100, int(request.args.get("limit", 10))))
    offset = max(0, int(request.args.get("offset", 0)))
    records = engine.sort_by_created(db.certifications.values())
    app_id = request.args.get("application_id")
    school_id = request.args.get("school_id")
    if app_id:
        records = [r for r in records if r["application_id"] == app_id]
    if school_id:
        records = [r for r in records if r["school_id"] == school_id]
    page, limit, offset, total = paginate(records, limit, offset)
    return array_body([engine.ser_certification(r) for r in page], limit, offset, total)


@bp.route(PREFIX + "/school-certifications/<cid>", methods=["GET"])
@guard("Borrower", "School", "Servicer", "Underwriter")
def read_certification(cid, _user_id=None, _role=None):
    record = engine.get_certification(cid)
    return object_body(engine.ser_certification(record))


@bp.route(PREFIX + "/school-certifications/<cid>/certify", methods=["POST"])
@guard("School")
def certify(cid, _user_id=None, _role=None):
    cert = engine.get_certification(cid)
    require_school_is(_user_id, cert["school_id"])
    school = engine.get_school(cert["school_id"])
    app = engine.get_application(cert["application_id"])

    # Request shape (priority 11) is evaluated before state (priority 13).
    data = body_of(request)
    enrollment = required(data, "certified_enrollment_status")
    enum(enrollment, engine.ENROLLMENT_STATUSES)
    amount = int(required(data, "certified_amount_cents"))

    if cert.get("certification_status") != "REQUESTED":
        fail("ERR_INVALID_STATE", "certification %s is not REQUESTED" % cid)
    if app.get("application_status") not in ("APPROVED", "SCHOOL_CERT_PENDING"):
        fail("ERR_INVALID_STATE", "application %s does not permit certification" % app["id"])
    if not school.get("active", True):
        fail("ERR_INVALID_STATE", "school %s is not active" % school["id"])

    # priority 18: standalone per-certification ceiling (INCLUSIVE of equality).
    ceiling = max(0, int(app["cost_of_attendance_cents"]) - int(app.get("other_aid_cents", 0)))
    if amount > ceiling:
        fail("ERR_CERTIFICATION_LIMIT_EXCEEDED",
             "certified amount exceeds the application's certified_limit_cents")

    # priority 19: school per-period capacity ceiling.
    capacity = int(school["certification_capacity_per_period_cents"])
    already = sum(
        int(c.get("certified_amount_cents", 0))
        for c in db.certifications.values()
        if c["school_id"] == school["id"]
        and c["academic_period_label"] == cert["academic_period_label"]
        and c.get("certification_status") in ("CERTIFIED", "PARTIAL_CERTIFIED")
    )
    if already + amount > capacity:
        fail("ERR_SCHOOL_CAPACITY_EXCEEDED",
             "certifying would exceed the school's per-period capacity")

    # priority 20: at most one live certification per period label.
    for sibling in engine.certs_of_application(app["id"]):
        if sibling["id"] == cert["id"]:
            continue
        if (sibling["academic_period_label"] == cert["academic_period_label"]
                and sibling.get("certification_status") in ("CERTIFIED", "PARTIAL_CERTIFIED")):
            fail("ERR_CERTIFICATION_PERIOD_CONFLICT",
                 "period %s already carries a live certification"
                 % cert["academic_period_label"])

    cert["certified_amount_cents"] = amount
    cert["certified_enrollment_status"] = enrollment
    cert["certified_date"] = db.now()
    cert["certification_status"] = "CERTIFIED"
    touch(cert)
    engine.run_waterfall(app)
    engine.sweep()
    return object_body(engine.ser_certification(cert))


@bp.route(PREFIX + "/school-certifications/<cid>/reject", methods=["POST"])
@guard("School")
def reject_certification(cid, _user_id=None, _role=None):
    cert = engine.get_certification(cid)
    require_school_is(_user_id, cert["school_id"])
    # Request shape (priority 11) is evaluated before state (priority 13).
    data = body_of(request)
    reason = required(data, "rejection_reason")
    enum(reason, engine.REJECTION_REASONS)
    if cert.get("certification_status") != "REQUESTED":
        fail("ERR_INVALID_STATE", "certification %s is not REQUESTED" % cid)
    cert["certification_status"] = "REJECTED"
    cert["rejection_reason"] = reason
    touch(cert)
    app = engine.get_application(cert["application_id"])
    engine.run_waterfall(app)
    siblings = engine.certs_of_application(app["id"])
    if siblings and all(s.get("certification_status") in ("REJECTED", "EXPIRED") for s in siblings):
        if app.get("application_status") == "SCHOOL_CERT_PENDING":
            app["application_status"] = "APPROVED"
            touch(app)
    return object_body(engine.ser_certification(cert))


@bp.route(PREFIX + "/school-certifications/<cid>/refile", methods=["POST"])
@guard("School")
def refile_certification(cid, _user_id=None, _role=None):
    cert = engine.get_certification(cid)
    require_school_is(_user_id, cert["school_id"])
    app = engine.get_application(cert["application_id"])
    if cert.get("certification_status") != "REJECTED":
        fail("ERR_INVALID_STATE", "certification %s is not REJECTED" % cid)
    if app.get("application_status") != "APPROVED":
        fail("ERR_INVALID_STATE", "application %s is not APPROVED" % app["id"])
    cert["certification_status"] = "REQUESTED"
    cert["rejection_reason"] = None
    cert["certified_amount_cents"] = 0
    touch(cert)
    app["application_status"] = "SCHOOL_CERT_PENDING"
    touch(app)
    return object_body(engine.ser_certification(cert))