"""Coverage routes: applications, loans, cancellation notices, delinquency
reports and independent validation reports.
"""

from flask import Blueprint

from common import fmt_utc, now_iso as _now_iso, parse_utc
from db import db, new_row, touch
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PATH_MISMATCH,
    ERR_UNDERWRITING_DECLINED,
)
from middleware import (
    ROLE_BORROWER,
    ROLE_LENDER,
    ROLE_MASTER_POLICY_ADMIN,
    ROLE_SERVICER,
    ROLE_UNDERWRITER,
    authenticate,
    body,
    optional_list,
    require_bool,
    require_enum,
    require_instant,
    require_int,
    require_roles,
    require_string,
    require_owner,
)
from response import ok_array, ok_list, ok_object
from services import serializers as ser
from services import workflows as wf
from services.views import (
    filter_value,
    get_application,
    get_external_report,
    get_loan,
    list_response,
    loan_cancellation_notices,
    loan_delinquency_reports,
    nested_list_response,
    resolve_body_application,
    resolve_body_lender,
    resolve_body_master_policy,
    resolve_body_rate_card,
    resolve_body_servicer,
    resolve_body_treaty,
)

bp = Blueprint("coverage", __name__)

CREDIT_GRADES = ("A", "B", "C", "D")
PREMIUM_PLANS = ("BPM", "SPM", "LPM")
OCCUPANCY_VALUES = ("OWNER_OCCUPIED", "SECOND_HOME", "INVESTMENT")
REQUEST_KINDS = ("BORROWER_REQUEST", "SERVICER_LOSS_MITIGATION_FAILURE")
REQUESTED_BY = ("BORROWER", "SERVICER")


def _require_loan_owner(identity, loan):
    """PRD 2.1: a Lender caller's X-User-ID is compared to the loan's lender_id."""
    require_owner(identity, loan["lender_id"], "lender")


def _require_loan_servicer(identity, loan):
    require_owner(identity, loan["servicer_id"], "servicer")


# =============================================================================
# Coverage applications
# =============================================================================

@bp.route("/mortgage-insurance/coverage-applications", methods=["POST"])
def submit_application():
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    payload = body()
    lender_id = require_string(payload, "lender_id")
    master_policy_id = require_string(payload, "master_policy_id")
    rate_card_id = require_string(payload, "rate_card_id")

    lender = resolve_body_lender(lender_id)
    resolve_body_master_policy(master_policy_id)
    resolve_body_rate_card(rate_card_id)

    require_owner(identity, lender["id"], "lender")

    row = new_row()
    row.update({
        "lender_id": lender_id,
        "master_policy_id": master_policy_id,
        "rate_card_id": rate_card_id,
        "borrower_reference": require_string(payload, "borrower_reference"),
        "loan_amount_cents": require_int(payload, "loan_amount_cents"),
        "property_value_cents": require_int(payload, "property_value_cents"),
        "credit_grade": require_enum(payload, "credit_grade", CREDIT_GRADES),
        "coverage_percent": require_int(payload, "coverage_percent"),
        "premium_plan": require_enum(payload, "premium_plan", PREMIUM_PLANS),
        "borrower_paid": require_bool(payload, "borrower_paid"),
        "financed_premium": require_bool(payload, "financed_premium"),
        "borrower_reserves_months": require_int(
            payload, "borrower_reserves_months", required=False, default=0
        ),
        "county_code": require_string(payload, "county_code"),
        "term_months": require_int(payload, "term_months"),
        "underwriting_path": "NON_DELEGATED",
        "submitted_utc": None,
        "underwritten_utc": None,
        "resubmission_count": 0,
        "approved_coverage_percent": 0,
        "rate_bps_applied": 0,
        "coverage_base_upb_cents": None,
        "status": "SUBMITTED",
    })
    row["submitted_utc"] = _now_iso()
    db.coverage_applications[row["id"]] = row
    return ok_object(ser.coverage_application(row), 201)


@bp.route("/mortgage-insurance/coverage-applications", methods=["GET"])
def list_applications():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)

    rows = list(db.coverage_applications.values())
    for name in ("lender_id", "master_policy_id", "rate_card_id", "status"):
        value = filter_value(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    items, limit, offset, total = list_response(ser.coverage_application, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/coverage-applications/<application_id>", methods=["GET"])
def get_application_route(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    return ok_object(ser.coverage_application(get_application(application_id)))


@bp.route("/mortgage-insurance/coverage-applications/<application_id>/underwrite", methods=["POST"])
def underwrite_application(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_UNDERWRITER)

    application = get_application(application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The application is not in a state from which underwriting may begin.",
        )

    lender = resolve_body_lender(application["lender_id"])
    if lender["delegated_underwriting"]:
        raise ApiError(
            ERR_PATH_MISMATCH,
            "A lender holding delegated authority may not use the non-delegated path.",
        )

    application["status"] = "IN_UNDERWRITING"
    application["underwriting_path"] = "NON_DELEGATED"
    application["underwritten_utc"] = _now_iso()
    touch(application)
    return ok_object(ser.coverage_application(application))


@bp.route(
    "/mortgage-insurance/coverage-applications/<application_id>/delegated-approve",
    methods=["POST"],
)
def delegated_approve(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    application = get_application(application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The application is not in a state from which delegated approval is declared.",
        )

    lender = resolve_body_lender(application["lender_id"])
    if not lender["delegated_underwriting"]:
        raise ApiError(
            ERR_PATH_MISMATCH,
            "The lender does not hold delegated underwriting authority.",
        )
    require_owner(identity, lender["id"], "lender")

    wf.approve_delegated(application)
    return ok_object(ser.coverage_application(application))


@bp.route(
    "/mortgage-insurance/coverage-applications/<application_id>/request-info", methods=["POST"]
)
def request_info(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_UNDERWRITER)

    application = get_application(application_id)
    if application["status"] != "IN_UNDERWRITING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The application is not in a state from which information may be requested.",
        )

    payload = body()
    require_string(payload, "info_requested")

    application["status"] = "INFO_REQUESTED"
    application["resubmission_count"] += 1
    touch(application)
    return ok_object(ser.coverage_application(application))


@bp.route(
    "/mortgage-insurance/coverage-applications/<application_id>/submit-info", methods=["POST"]
)
def submit_info(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    application = get_application(application_id)
    if application["status"] != "INFO_REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The application is not awaiting borrower information.",
        )
    lender = resolve_body_lender(application["lender_id"])
    require_owner(identity, lender["id"], "lender")

    payload = body()
    if payload.get("borrower_reserves_months") is not None:
        application["borrower_reserves_months"] = require_int(payload, "borrower_reserves_months")

    application["status"] = "IN_UNDERWRITING"
    application["underwriting_path"] = "NON_DELEGATED"
    touch(application)
    return ok_object(ser.coverage_application(application))


@bp.route("/mortgage-insurance/coverage-applications/<application_id>/approve", methods=["POST"])
def approve_application(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_UNDERWRITER)

    application = get_application(application_id)
    if application["status"] != "IN_UNDERWRITING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The application is not in a state from which approval is declared.",
        )

    wf.approve_non_delegated(application)
    return ok_object(ser.coverage_application(application))


@bp.route("/mortgage-insurance/coverage-applications/<application_id>/decline", methods=["POST"])
def decline_application(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_UNDERWRITER)

    application = get_application(application_id)
    if application["status"] != "IN_UNDERWRITING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The application is not in a state from which decline is declared.",
        )

    payload = body()
    require_string(payload, "decline_reason")

    from services.pricing import ALLOWED_COVERAGE_PERCENTS

    if application["coverage_percent"] not in ALLOWED_COVERAGE_PERCENTS:
        raise ApiError(
            ERR_UNDERWRITING_DECLINED,
            "The requested coverage percentage is outside the master policy's allowed set.",
        )

    application["status"] = "DECLINED"
    touch(application)
    return ok_object(ser.coverage_application(application))


@bp.route("/mortgage-insurance/coverage-applications/<application_id>/withdraw", methods=["POST"])
def withdraw_application(application_id):
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    application = get_application(application_id)
    if application["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The application is not in a state from which withdrawal is declared.",
        )
    lender = resolve_body_lender(application["lender_id"])
    require_owner(identity, lender["id"], "lender")

    application["status"] = "WITHDRAWN"
    touch(application)
    return ok_object(ser.coverage_application(application))


# =============================================================================
# Loans
# =============================================================================

@bp.route("/mortgage-insurance/loans", methods=["POST"])
def create_loan():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    payload = body()
    application_id = require_string(payload, "application_id")
    servicer_id = require_string(payload, "servicer_id")
    # The treaty election is declared as an input, but SCAFFOLD 1.1 documents the
    # loan's reinsurance_treaty_id as one that "may reference a treaty that is not
    # yet in force", so an explicit null is admissible: issuance records no treaty
    # and cession is tested at settlement time against that absent reference
    # (rejected_reason NO_TREATY), never at issuance.
    reinsurance_treaty_id = payload.get("reinsurance_treaty_id")
    if reinsurance_treaty_id is not None and not isinstance(reinsurance_treaty_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'reinsurance_treaty_id' must be a string.")

    application = resolve_body_application(application_id)
    servicer = resolve_body_servicer(servicer_id)
    treaty = resolve_body_treaty(reinsurance_treaty_id)

    if application["status"] != "APPROVED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Only an approved coverage application can be issued as a loan.",
        )

    loan = wf.issue_loan(application, servicer, treaty)
    return ok_object(ser.loan(loan), 201)


@bp.route("/mortgage-insurance/loans", methods=["GET"])
def list_loans():
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )

    rows = list(db.loans.values())
    for name in (
        "lender_id",
        "servicer_id",
        "master_policy_id",
        "reinsurance_treaty_id",
        "application_id",
        "coverage_status",
    ):
        value = filter_value(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]

    if identity.role == ROLE_LENDER:
        rows = [r for r in rows if r["lender_id"] == identity.user_id]
    elif identity.role == ROLE_SERVICER:
        rows = [r for r in rows if r["servicer_id"] == identity.user_id]

    items, limit, offset, total = list_response(ser.loan, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/loans/<loan_id>", methods=["GET"])
def get_loan_route(loan_id):
    identity = authenticate()
    # PRD 2.1: a Borrower reads its own loan. The Borrower identity is opaque and
    # is never resolved against a table, so no ownership comparison is made.
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER,
        ROLE_SERVICER, ROLE_BORROWER,
    )
    loan = get_loan(loan_id)
    _assert_read_scope(identity, loan)
    return ok_object(ser.loan(loan))


@bp.route("/mortgage-insurance/loans/<loan_id>/amortization-milestones", methods=["POST"])
def record_milestone(loan_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_SERVICER)

    loan = get_loan(loan_id)
    if identity.role == ROLE_SERVICER:
        _require_loan_servicer(identity, loan)

    payload = body()
    current_upb_cents = require_int(payload, "current_upb_cents")

    wf.record_amortization_milestone(loan, current_upb_cents)
    return ok_object(ser.loan(loan))


@bp.route("/mortgage-insurance/loans/<loan_id>/rescission-relief", methods=["POST"])
def record_rescission_relief(loan_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    loan = get_loan(loan_id)
    payload = body()
    relief_status = require_enum(payload, "relief_status", ("ATTACHED", "REVOKED"))
    waiver_evidence_code = payload.get("waiver_evidence_code")

    # relief_status ATTACHED records the master insurer's attached relief;
    # REVOKED is the loss-mitigation waiver and the revocation of a pending
    # termination (PRD 3.5 / 3.6).
    wf.record_rescission_relief(loan, relief_status, waiver_evidence_code)
    return ok_object(ser.loan(loan))


@bp.route("/mortgage-insurance/loans/<loan_id>/cancellation-notices", methods=["POST"])
def file_cancellation_notice(loan_id):
    identity = authenticate()
    require_roles(identity, ROLE_LENDER, ROLE_SERVICER)

    loan = get_loan(loan_id)
    if identity.role == ROLE_LENDER:
        _require_loan_owner(identity, loan)
    else:
        _require_loan_servicer(identity, loan)

    payload = body()
    request_kind = require_enum(payload, "request_kind", REQUEST_KINDS)
    requested_by_role = require_enum(payload, "requested_by_role", REQUESTED_BY)
    notice_utc = fmt_utc(require_instant(payload, "notice_utc"))
    applied_utc = fmt_utc(require_instant(payload, "applied_utc"))
    evidence_cents = require_int(payload, "evidence_cents", required=False, default=0)

    notice = wf.file_cancellation_notice(
        loan, request_kind, requested_by_role, notice_utc, applied_utc, evidence_cents
    )
    return ok_object(ser.cancellation_notice(notice), 201)


@bp.route("/mortgage-insurance/loans/<loan_id>/cancellation-notices", methods=["GET"])
def list_cancellation_notices(loan_id):
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )
    loan = get_loan(loan_id)
    _assert_read_scope(identity, loan)
    return ok_list(
        nested_list_response(ser.cancellation_notice, loan_cancellation_notices(loan_id))
    )


@bp.route("/mortgage-insurance/loans/<loan_id>/delinquency-reports", methods=["GET"])
def list_loan_delinquency_reports(loan_id):
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )
    loan = get_loan(loan_id)
    _assert_read_scope(identity, loan)
    return ok_list(
        nested_list_response(ser.delinquency_report, loan_delinquency_reports(loan_id))
    )


@bp.route("/mortgage-insurance/loans/<loan_id>/claims", methods=["GET"])
def list_loan_claims(loan_id):
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )
    loan = get_loan(loan_id)
    _assert_read_scope(identity, loan)
    from services.views import loan_claims

    return ok_list(nested_list_response(ser.claim, loan_claims(loan_id)))


@bp.route("/mortgage-insurance/loans/<loan_id>/external-reports", methods=["GET"])
def list_loan_external_reports(loan_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    loan = get_loan(loan_id)
    _assert_read_scope(identity, loan)
    from services.views import loan_external_reports

    return ok_list(nested_list_response(ser.external_report, loan_external_reports(loan_id)))


@bp.route("/mortgage-insurance/loans/<loan_id>/coverage-disputes", methods=["GET"])
def list_loan_disputes(loan_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    loan = get_loan(loan_id)
    _assert_read_scope(identity, loan)
    from services.views import loan_disputes

    return ok_list(nested_list_response(ser.curtailment_dispute, loan_disputes(loan_id)))


def _assert_read_scope(identity, loan):
    """A Lender or Servicer reads only the loans it is party to (PRD 2.1)."""
    if identity.role == ROLE_LENDER:
        require_owner(identity, loan["lender_id"], "lender")
    elif identity.role == ROLE_SERVICER:
        require_owner(identity, loan["servicer_id"], "servicer")


# =============================================================================
# Independent validation reports
# =============================================================================

@bp.route("/mortgage-insurance/loans/<loan_id>/external-reports", methods=["POST"])
def file_external_report(loan_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)

    loan = get_loan(loan_id)
    payload = body()

    verified_loan_amount_cents = require_int(payload, "verified_loan_amount_cents")
    verified_property_value_cents = require_int(payload, "verified_property_value_cents")
    if verified_property_value_cents == 0:
        raise ApiError(ERR_INVALID_REQUEST, "verified_property_value_cents must be positive.")
    post_origination_value_cents = require_int(
        payload, "post_origination_value_cents", required=False, default=0
    )
    occupancy_reported = require_enum(payload, "occupancy_reported", OCCUPANCY_VALUES)
    completed_dt = require_instant(payload, "independent_validation_completed_utc")

    report = wf.file_external_report(
        loan,
        payload,
        verified_loan_amount_cents,
        verified_property_value_cents,
        post_origination_value_cents,
        occupancy_reported,
        completed_dt,
    )
    return ok_object(ser.external_report(report), 201)


@bp.route("/mortgage-insurance/external-reports/<report_id>", methods=["GET"])
def get_external_report_route(report_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    return ok_object(ser.external_report(get_external_report(report_id)))


# =============================================================================
# Delinquency reports
# =============================================================================

@bp.route("/mortgage-insurance/delinquency-reports", methods=["POST"])
def file_delinquency_report():
    identity = authenticate()
    require_roles(identity, ROLE_SERVICER)

    payload = body()
    loan_id = require_string(payload, "loan_id")
    servicer_id = require_string(payload, "servicer_id")

    loan = get_loan(loan_id)
    servicer = resolve_body_servicer(servicer_id)
    require_owner(identity, servicer["id"], "servicer")

    as_of_period = require_string(payload, "as_of_period")
    try:
        parse_utc(as_of_period + "-05T00:00:00Z")
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "as_of_period must be formatted YYYY-MM.")

    delinquency_class = require_enum(payload, "delinquency_class", ("A", "B"))
    months_delinquent = require_int(payload, "months_delinquent")
    activities = optional_list(payload, "loss_mitigation_activities", required=True)

    report = wf.file_delinquency_report(
        loan, servicer, as_of_period, delinquency_class, months_delinquent, activities
    )
    return ok_object(ser.delinquency_report(report), 201)


@bp.route("/mortgage-insurance/delinquency-reports", methods=["GET"])
def list_delinquency_reports():
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )
    rows = list(db.delinquency_reports.values())
    for name in ("loan_id", "servicer_id"):
        value = filter_value(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    items, limit, offset, total = list_response(ser.delinquency_report, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/delinquency-reports/<report_id>", methods=["GET"])
def get_delinquency_report_route(report_id):
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )
    from services.views import get_delinquency_report

    return ok_object(ser.delinquency_report(get_delinquency_report(report_id)))