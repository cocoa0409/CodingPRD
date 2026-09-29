"""Transfer applications, publication, protests and the decision (PRD 3.6-3.7)."""

from flask import Blueprint

import calc
import domain
from authz import (ALL_ROLES, BROKER, PLATFORM_ADMIN, REGULATOR, SELLER,
                   agreement_or_404, application_or_404, authenticate, county_or_404,
                   license_or_404, premises_or_404, protest_or_404, require_brokerage)
from envelope import apply_filters, created, ok, ok_list, pagination_args, paginate
from errors import ApiError
from store import (add_days, bump, db, make_record, now, public, public_list,
                   sorted_by_created)
from validation import F, json_body, validate

bp = Blueprint("applications", __name__)

APPLICATION_TERMINAL = ("APPROVED", "DENIED")
PROTEST_TERMINAL = ("SUSTAINED", "OVERRULED")
GROUNDS = ("UNDUE_CONCENTRATION", "DISTANCE_RESTRICTION", "PUBLIC_WELFARE", "ZONING")
DECISIONS = ("APPROVED", "DENIED")


def _regulatory_gates(agreement, premises, county, buyer, check_distance=True):
    """Ordered regulatory re-checks shared by filing (PRD 2.9 items 12-15, 17)."""
    if check_distance and not calc.distances_ok(premises, county):
        raise ApiError("ERR_DISTANCE_RESTRICTION_VIOLATION",
                       "The premises does not clear the county's distance minima.")
    if premises["suitability_status"] == "UNSUITABLE":
        raise ApiError("ERR_PREMISES_UNSUITABLE", "The premises is UNSUITABLE.")
    if not calc.buyer_is_qualified(buyer):
        raise ApiError("ERR_BUYER_NOT_QUALIFIED",
                       "The buyer has no qualifying FINAL_REVIEW qualification on file.")
    if domain.fully_acked_disclosure(agreement["id"]) is None:
        raise ApiError("ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED",
                       "A FULLY_ACKED agency disclosure is required.")
    seller = db.sellers.get(agreement["seller_id"])
    if seller is None or seller["tax_clearance_status"] != "CLEARED":
        raise ApiError("ERR_SELLER_TAX_CLEARANCE_MISSING",
                       "The selling licensee's tax clearance is not CLEARED.")


@bp.route("/transfer-applications", methods=["POST"])
def create_application():
    user_id, role = authenticate((BROKER,))
    data = validate(json_body(), [
        F("agreement_id", "string"),
        F("fee_paid_cents", "integer"),
        F("applicant_statement_ref", "string", required=False, default=None),
    ])
    agreement = agreement_or_404(data["agreement_id"])
    require_brokerage(user_id, role, agreement["brokerage_id"])
    if (agreement["agreement_status"] != "EXECUTED"
            and agreement["agreement_status"] not in ("CLOSED", "TERMINATED")):
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "The agreement must be EXECUTED before the transfer application is filed.")
    if agreement["agreement_status"] in ("CLOSED", "TERMINATED"):
        raise ApiError("ERR_ALREADY_TERMINAL", "The agreement is already in a terminal state.")
    if agreement["escrow_status"] == "AWAITING_DEPOSIT":
        raise ApiError("ERR_ESCROW_NOT_HELD", "The escrow deposit must be held.")
    if agreement["escrow_status"] in ("RELEASED", "REFUNDED", "FORFEITED"):
        raise ApiError("ERR_ESCROW_ALREADY_SETTLED", "The escrow has already been settled.")
    lic = license_or_404(agreement["license_id"])
    premises = premises_or_404(agreement["premises_id"])
    county = county_or_404(lic["county_id"])
    buyer = db.buyers.get(agreement["buyer_id"])
    _regulatory_gates(agreement, premises, county, buyer)
    fee = calc.transfer_filing_fee(lic["license_class"], 0)
    if data["fee_paid_cents"] != fee:
        raise ApiError("ERR_FILING_FEE_MISMATCH",
                       "The tendered fee must equal the computed filing fee exactly.")
    application = make_record({
        "agreement_id": agreement["id"],
        "license_id": lic["id"],
        "premises_id": premises["id"],
        "status": "SUBMITTED",
        "applicant_statement_ref": data["applicant_statement_ref"],
        "filing_fee_cents": fee,
        "fee_paid_cents": data["fee_paid_cents"],
        "fee_paid_total_cents": data["fee_paid_cents"],
        "deficiency_round_count": 0,
        "accepted_by_analyst_id": None,
        "last_deficiency_codes": None,
        "posting_started_at": None,
        "posting_ends_at": None,
        "protest_deadline_at": None,
        "decision": None,
        "decided_at": None,
        "decision_note": None,
    })
    db.applications[application["id"]] = application
    return created(public(application))


@bp.route("/transfer-applications/<application_id>", methods=["GET"])
def get_application(application_id):
    authenticate(ALL_ROLES)
    return ok(public(application_or_404(application_id)))


@bp.route("/transfer-applications", methods=["GET"])
def list_applications():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    rows = apply_filters(db.applications.values(), {
        "agreement_id": "agreement_id",
        "license_id": "license_id",
        "premises_id": "premises_id",
        "status": "status",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/transfer-applications/<application_id>/protests", methods=["GET"])
def list_application_protests(application_id):
    authenticate((PLATFORM_ADMIN, BROKER, SELLER, REGULATOR))
    application = application_or_404(application_id)
    limit, offset = pagination_args()
    rows = apply_filters(domain.protests_of(application["id"]), {"status": "status"})
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/transfer-applications/<application_id>/accept-review", methods=["POST"])
def accept_review(application_id):
    user_id, role = authenticate((REGULATOR,))
    application = application_or_404(application_id)
    if application["status"] != "SUBMITTED" and application["status"] not in APPLICATION_TERMINAL:
        raise ApiError("ERR_INVALID_APPLICATION_STATE",
                       "Only a SUBMITTED application can be taken into review.")
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The application is already in a terminal state.")
    application["status"] = "UNDER_REVIEW"
    application["accepted_by_analyst_id"] = user_id
    bump(application)
    return ok(public(application))


@bp.route("/transfer-applications/<application_id>/deficiency", methods=["POST"])
def issue_deficiency(application_id):
    authenticate((REGULATOR,))
    data = validate(json_body(), [F("deficiency_codes", "string_array")])
    application = application_or_404(application_id)
    if application["status"] != "UNDER_REVIEW" and application["status"] not in APPLICATION_TERMINAL:
        raise ApiError("ERR_INVALID_APPLICATION_STATE",
                       "A deficiency notice may only be issued while UNDER_REVIEW.")
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The application is already in a terminal state.")
    if application["deficiency_round_count"] >= calc.MAX_DEFICIENCY_ROUNDS:
        raise ApiError("ERR_DEFICIENCY_LIMIT_EXCEEDED",
                       "The deficiency round limit has been reached.")
    application["status"] = "DEFICIENT"
    application["deficiency_round_count"] = application["deficiency_round_count"] + 1
    application["last_deficiency_codes"] = data["deficiency_codes"]
    bump(application)
    return ok(public(application))


@bp.route("/transfer-applications/<application_id>/resubmit", methods=["POST"])
def resubmit_application(application_id):
    user_id, role = authenticate((BROKER,))
    data = validate(json_body(), [
        F("fee_paid_cents", "integer"),
        F("applicant_statement_ref", "string", required=False, default=None),
    ])
    application = application_or_404(application_id)
    agreement = agreement_or_404(application["agreement_id"])
    require_brokerage(user_id, role, agreement["brokerage_id"])
    if application["status"] != "DEFICIENT" and application["status"] not in APPLICATION_TERMINAL:
        raise ApiError("ERR_INVALID_APPLICATION_STATE",
                       "Only a DEFICIENT application can be refiled.")
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The application is already in a terminal state.")
    if now() > agreement["contingency_deadline_at"]:
        raise ApiError("ERR_CONTINGENCY_DEADLINE_PASSED",
                       "The contingency deadline has passed.")
    lic = license_or_404(application["license_id"])
    fee = calc.transfer_filing_fee(lic["license_class"], application["deficiency_round_count"])
    if data["fee_paid_cents"] != fee:
        raise ApiError("ERR_FILING_FEE_MISMATCH",
                       "The tendered fee must equal the recomputed filing fee exactly.")
    application["status"] = "SUBMITTED"
    application["filing_fee_cents"] = fee
    application["fee_paid_cents"] = data["fee_paid_cents"]
    application["fee_paid_total_cents"] = application["fee_paid_total_cents"] + data["fee_paid_cents"]
    if data["applicant_statement_ref"] is not None:
        application["applicant_statement_ref"] = data["applicant_statement_ref"]
    bump(application)
    return ok(public(application))


@bp.route("/transfer-applications/<application_id>/post-notice", methods=["POST"])
def post_notice(application_id):
    authenticate((REGULATOR,))
    application = application_or_404(application_id)
    if application["status"] != "UNDER_REVIEW" and application["status"] not in APPLICATION_TERMINAL:
        raise ApiError("ERR_INVALID_APPLICATION_STATE",
                       "The statutory notice may only be published from UNDER_REVIEW.")
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The application is already in a terminal state.")
    premises = premises_or_404(application["premises_id"])
    county = county_or_404(premises["county_id"])
    if not calc.distances_ok(premises, county):
        raise ApiError("ERR_DISTANCE_RESTRICTION_VIOLATION",
                       "The premises does not clear the county's distance minima.")
    if premises["suitability_status"] == "UNSUITABLE":
        raise ApiError("ERR_PREMISES_UNSUITABLE", "The premises is UNSUITABLE.")
    if premises["conditional_use_permit_status"] not in ("NOT_REQUIRED", "GRANTED"):
        raise ApiError("ERR_PREMISES_UNSUITABLE",
                       "The conditional-use permit is still outstanding.")
    instant = now()
    for other in db.applications.values():
        if other["id"] == application["id"]:
            continue
        if other["premises_id"] != application["premises_id"]:
            continue
        if other["status"] not in ("POSTED", "PROTESTED", "APPROVED"):
            continue
        if other["posting_ends_at"] is None:
            continue
        buffered = add_days(other["posting_ends_at"], calc.POSTING_QUIET_BUFFER_DAYS)
        if not instant > buffered:
            raise ApiError("ERR_POSTING_WINDOW_CONFLICT",
                           "Another live publication on this premises has not cleared its buffer.")
    application["status"] = "POSTED"
    application["posting_started_at"] = instant
    application["posting_ends_at"] = add_days(instant, county["posting_period_days"])
    application["protest_deadline_at"] = add_days(
        instant, min(county["posting_period_days"], county["protest_window_days"]))
    bump(application)
    return ok(public(application))


@bp.route("/transfer-applications/<application_id>/decision", methods=["POST"])
def application_decision(application_id):
    user_id, role = authenticate((REGULATOR,))
    data = validate(json_body(), [
        F("decision", "enum", values=DECISIONS),
        F("decision_note", "string", required=False, default=None),
    ])
    application = application_or_404(application_id)
    if (application["accepted_by_analyst_id"] is not None
            and user_id == application["accepted_by_analyst_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The accepting analyst may not decide this application.")
    if (application["status"] not in ("POSTED", "PROTESTED")
            and application["status"] not in APPLICATION_TERMINAL):
        raise ApiError("ERR_INVALID_APPLICATION_STATE",
                       "A decision is only reachable from POSTED or PROTESTED.")
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The application is already in a terminal state.")
    if application["posting_ends_at"] is None or not now() > application["posting_ends_at"]:
        raise ApiError("ERR_POSTING_PERIOD_NOT_ELAPSED",
                       "The publication period has not fully elapsed.")
    protests = domain.protests_of(application["id"])
    for p in protests:
        if p["status"] == "OPEN" and now() <= p["response_due_at"]:
            raise ApiError("ERR_PROTEST_RESPONSE_PENDING",
                           "A protest response window is still open.")
    if data["decision"] == "APPROVED":
        for p in protests:
            if p["status"] == "OPEN" and now() > p["response_due_at"]:
                raise ApiError("ERR_UNANSWERED_PROTEST_REQUIRES_DENIAL",
                               "An unanswered protest admits denial only.")
    application["status"] = data["decision"]
    application["decision"] = data["decision"]
    application["decided_at"] = now()
    application["decision_note"] = data["decision_note"]
    bump(application)
    agreement = db.agreements.get(application["agreement_id"])
    if data["decision"] == "APPROVED":
        listing = db.listings.get(agreement["listing_id"]) if agreement is not None else None
        lic = db.licenses.get(application["license_id"])
        domain.approval_cascade(application, agreement, listing, lic)
    else:
        domain.denial_cascade(application)
    return ok(public(application))


# --- protests -------------------------------------------------------------
@bp.route("/protests", methods=["POST"])
def create_protest():
    authenticate((REGULATOR,))
    data = validate(json_body(), [
        F("application_id", "string"),
        F("protestant_name", "string"),
        F("grounds", "enum", values=GROUNDS),
        F("response_due_days", "integer", required=False, default=15),
    ])
    application = application_or_404(data["application_id"])
    if application["status"] != "POSTED" and application["status"] not in APPLICATION_TERMINAL:
        raise ApiError("ERR_INVALID_APPLICATION_STATE",
                       "A protest may only be recorded against a POSTED application.")
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The application is already in a terminal state.")
    if application["protest_deadline_at"] is None or now() > application["protest_deadline_at"]:
        raise ApiError("ERR_PROTEST_WINDOW_CLOSED", "The protest window has closed.")
    filed_at = now()
    protest = make_record({
        "application_id": application["id"],
        "protestant_name": data["protestant_name"],
        "grounds": data["grounds"],
        "filed_at": filed_at,
        "response_due_at": add_days(filed_at, data["response_due_days"]),
        "response_text_ref": None,
        "response_submitted_at": None,
        "status": "OPEN",
    })
    db.protests[protest["id"]] = protest
    application["status"] = "PROTESTED"
    bump(application)
    return created(public(protest))


@bp.route("/protests/<protest_id>", methods=["GET"])
def get_protest(protest_id):
    authenticate((PLATFORM_ADMIN, BROKER, SELLER, REGULATOR))
    return ok(public(protest_or_404(protest_id)))


@bp.route("/protests", methods=["GET"])
def list_protests():
    authenticate((PLATFORM_ADMIN, BROKER, SELLER, REGULATOR))
    limit, offset = pagination_args()
    rows = apply_filters(db.protests.values(), {
        "application_id": "application_id",
        "status": "status",
        "grounds": "grounds",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/protests/<protest_id>/response", methods=["POST"])
def respond_to_protest(protest_id):
    user_id, role = authenticate((BROKER,))
    data = validate(json_body(), [F("response_text_ref", "string")])
    protest = protest_or_404(protest_id)
    application = application_or_404(protest["application_id"])
    agreement = agreement_or_404(application["agreement_id"])
    require_brokerage(user_id, role, agreement["brokerage_id"])
    if protest["status"] != "OPEN" and protest["status"] not in PROTEST_TERMINAL:
        raise ApiError("ERR_INVALID_PROTEST_STATE", "Only an OPEN protest can be answered.")
    if protest["status"] in PROTEST_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The protest is already in a terminal state.")
    if application["status"] != "PROTESTED" and application["status"] not in APPLICATION_TERMINAL:
        raise ApiError("ERR_INVALID_APPLICATION_STATE",
                       "The parent application must be PROTESTED.")
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The application is already in a terminal state.")
    if now() > protest["response_due_at"]:
        raise ApiError("ERR_PROTEST_RESPONSE_WINDOW_CLOSED",
                       "The protest response window has closed.")
    protest["status"] = "RESPONDED"
    protest["response_text_ref"] = data["response_text_ref"]
    protest["response_submitted_at"] = now()
    bump(protest)
    return ok(public(protest))
