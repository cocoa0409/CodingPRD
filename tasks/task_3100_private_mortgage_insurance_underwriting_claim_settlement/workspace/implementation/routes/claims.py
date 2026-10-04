"""Claim, dispute and reinsurance-cession routes."""

from flask import Blueprint

from common import fmt_utc, new_id, now_iso
from db import db, new_row, touch
from errors import ApiError, ERR_INVALID_STATE_TRANSITION, ERR_RESOURCE_NOT_FOUND
from middleware import (
    ROLE_BORROWER,
    ROLE_LENDER,
    ROLE_MASTER_POLICY_ADMIN,
    ROLE_SERVICER,
    ROLE_UNDERWRITER,
    authenticate,
    body,
    require_enum,
    require_instant,
    require_int,
    require_owner,
    require_roles,
    require_string,
)
from response import ok_array, ok_list, ok_object
from services import serializers as ser
from services import workflows as wf
from services.claim_arithmetic import SETTLEMENT_OPTION_KINDS
from services.views import (
    claim_options,
    filter_value,
    get_cession,
    get_claim,
    get_dispute,
    get_loan,
    list_response,
    resolve_body_lender,
    resolve_body_loan,
    resolve_body_claim,
)

bp = Blueprint("claims", __name__)

EVENT_KINDS = ("FORECLOSURE", "SHORT_SALE", "DEED_IN_LIEU")
GROUNDS = (
    "ORIGINATION_OMISSION",
    "OCCUPANCY_MISREPRESENTATION",
    "VALUATION_ERROR",
    "LOSS_MITIGATION_EXCUSE",
)


def _require_claim_owner(identity, claim):
    loan = db.loans.get(claim["loan_id"])
    if loan is None:
        return
    require_owner(identity, loan["lender_id"], "lender")


# =============================================================================
# Claims
# =============================================================================

@bp.route("/mortgage-insurance/claims", methods=["POST"])
def file_claim():
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    payload = body()
    loan_id = require_string(payload, "loan_id")
    loan = resolve_body_loan(loan_id)
    require_owner(identity, loan["lender_id"], "lender")

    row = new_row()
    row.update({
        "loan_id": loan_id,
        "event_kind": require_enum(payload, "event_kind", EVENT_KINDS),
        "event_completed_utc": ser_instant(payload, "event_completed_utc", not_future=True),
        "unpaid_principal_cents": require_int(payload, "unpaid_principal_cents"),
        "accrued_interest_cents": require_int(payload, "accrued_interest_cents"),
        "allowable_advances_cents": require_int(payload, "allowable_advances_cents"),
        "gross_proceeds_cents": require_int(payload, "gross_proceeds_cents"),
        "expenses_of_sale_cents": require_int(payload, "expenses_of_sale_cents"),
        "filed_utc": None,
        "curtailment_rate_applied": None,
        "permitted_interest_cents": None,
        "permitted_advances_cents": None,
        "net_unpaid_balance_cents": None,
        "recoverable_amount_cents": None,
        "coverage_ceiling_cents": None,
        "covered_claim_amount_cents": None,
        "post_curtailment_cents": None,
        "claim_deductible_cents": None,
        "net_claim_amount_cents": None,
        "trace_number": "CLM-" + new_id().replace("-", "").upper()[:12],
        "settlement_option_kind": None,
        "settlement_amount_cents": None,
        "status": "FILED",
    })
    row["filed_utc"] = now_iso()
    db.claims[row["id"]] = row
    return ok_object(ser.claim(row), 201)


def ser_instant(payload, name, not_future=False):
    """Parse and normalize an instant supplied in a claim body.

    PRD 2.12 places "an event instant set in the future" among the malformed-body
    cases that "is refused with `ERR_INVALID_REQUEST` (HTTP 400)", and PRD 3.7
    names `event_completed_utc` as "the `event_completed_utc` instant at which the
    title-transferring event completed" - an instant that has already happened
    relative to the logical clock every temporal rule is evaluated against
    (PRD 2.5). The reference point is therefore the logical clock, never real
    time, so the two are compared at the moment the body is deserialized, ahead
    of the numbered business gates.
    """
    return fmt_utc(require_instant(payload, name, not_future=not_future))


@bp.route("/mortgage-insurance/claims", methods=["GET"])
def list_claims():
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )
    rows = list(db.claims.values())
    loan_id = filter_value("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    if identity.role == ROLE_LENDER:
        rows = [r for r in rows if _claim_lender(r) == identity.user_id]
    elif identity.role == ROLE_SERVICER:
        rows = [r for r in rows if _claim_servicer(r) == identity.user_id]

    items, limit, offset, total = list_response(ser.claim, rows)
    return ok_array(items, limit, offset, total)


def _claim_lender(claim):
    loan = db.loans.get(claim["loan_id"])
    return loan["lender_id"] if loan else None


def _claim_servicer(claim):
    loan = db.loans.get(claim["loan_id"])
    return loan["servicer_id"] if loan else None


@bp.route("/mortgage-insurance/claims/<claim_id>", methods=["GET"])
def get_claim_route(claim_id):
    identity = authenticate()
    # PRD 2.1: a Borrower reads the claims on its own loan.
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER,
        ROLE_SERVICER, ROLE_BORROWER,
    )
    claim = get_claim(claim_id)
    if identity.role == ROLE_LENDER:
        require_owner(identity, _claim_lender(claim), "lender")
    elif identity.role == ROLE_SERVICER:
        require_owner(identity, _claim_servicer(claim), "servicer")
    return ok_object(ser.claim(claim))


@bp.route("/mortgage-insurance/claims/<claim_id>/begin-review", methods=["POST"])
def begin_review(claim_id):
    identity = authenticate()
    require_roles(identity, ROLE_UNDERWRITER)

    claim = get_claim(claim_id)
    if claim["status"] != "FILED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The claim is not in a state from which review may begin.",
        )

    loan = get_loan(claim["loan_id"])
    wf._assert_claim_time_bar(claim, loan)

    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok_object(ser.claim(claim))


@bp.route("/mortgage-insurance/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    identity = authenticate()
    require_roles(identity, ROLE_UNDERWRITER)

    claim = get_claim(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The claim is not in a state from which approval is declared.",
        )

    loan = get_loan(claim["loan_id"])
    wf.approve_claim(claim, loan)
    return ok_object(ser.claim(claim))


@bp.route("/mortgage-insurance/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    identity = authenticate()
    require_roles(identity, ROLE_UNDERWRITER)

    claim = get_claim(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The claim is not in a state from which denial is declared.",
        )

    payload = body()
    require_string(payload, "denial_reason")

    claim["status"] = "DENIED"
    touch(claim)
    return ok_object(ser.claim(claim))


@bp.route("/mortgage-insurance/claims/<claim_id>/reconsideration", methods=["POST"])
def reconsider_claim(claim_id):
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    claim = get_claim(claim_id)
    if claim["status"] not in ("UNDER_REVIEW", "DENIED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The claim is not in a state from which reconsideration is declared.",
        )
    _require_claim_owner(identity, claim)

    payload = body()
    require_string(payload, "reason")

    claim["status"] = "FILED"
    touch(claim)
    return ok_object(ser.claim(claim))


@bp.route("/mortgage-insurance/claims/<claim_id>/settle", methods=["POST"])
def settle_claim(claim_id):
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    claim = get_claim(claim_id)
    if claim["status"] != "APPROVED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The claim is not in a state from which settlement is declared.",
        )
    _require_claim_owner(identity, claim)

    payload = body()
    settlement_option_kind = require_string(payload, "settlement_option_kind")
    expected_claim_version = require_int(payload, "expected_claim_version")
    expected_loan_version = require_int(payload, "expected_loan_version")

    loan = get_loan(claim["loan_id"])
    wf.settle_claim(
        claim, loan, settlement_option_kind, expected_claim_version, expected_loan_version
    )
    return ok_object(ser.claim(claim))


@bp.route("/mortgage-insurance/claims/<claim_id>/settlement-options", methods=["GET"])
def list_settlement_options(claim_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    get_claim(claim_id)
    options = sorted(
        claim_options(claim_id), key=lambda row: SETTLEMENT_OPTION_KINDS.index(row["option_kind"])
    )
    return ok_list([ser.claim_settlement_option(row) for row in options])


# =============================================================================
# Coverage disputes
# =============================================================================

@bp.route("/mortgage-insurance/coverage-disputes", methods=["POST"])
def file_dispute():
    identity = authenticate()
    require_roles(identity, ROLE_LENDER)

    payload = body()
    loan_id = require_string(payload, "loan_id")
    lender_id = require_string(payload, "lender_id")
    target_claim_id = require_string(payload, "target_claim_id")

    loan = resolve_body_loan(loan_id)
    lender = resolve_body_lender(lender_id)
    claim = resolve_body_claim(target_claim_id)

    if claim["loan_id"] != loan["id"]:
        raise ApiError(
            ERR_RESOURCE_NOT_FOUND,
            "The target claim does not belong to the named loan.",
        )
    if loan["lender_id"] != lender["id"]:
        raise ApiError(
            ERR_RESOURCE_NOT_FOUND,
            "The named lender does not own the named loan.",
        )
    require_owner(identity, lender["id"], "lender")

    grounds = require_enum(payload, "grounds", GROUNDS)
    asserted_coverage_percent = require_int(payload, "asserted_coverage_percent")

    dispute = wf.file_dispute(loan, lender, claim, grounds, asserted_coverage_percent)
    return ok_object(ser.curtailment_dispute(dispute), 201)


@bp.route("/mortgage-insurance/coverage-disputes", methods=["GET"])
def list_disputes():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)

    rows = list(db.curtailment_disputes.values())
    for name in ("loan_id", "lender_id", "target_claim_id", "status"):
        value = filter_value(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    if identity.role == ROLE_LENDER:
        rows = [r for r in rows if r["lender_id"] == identity.user_id]

    items, limit, offset, total = list_response(ser.curtailment_dispute, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/coverage-disputes/<dispute_id>", methods=["GET"])
def get_dispute_route(dispute_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    dispute = get_dispute(dispute_id)
    if identity.role == ROLE_LENDER:
        require_owner(identity, dispute["lender_id"], "lender")
    return ok_object(ser.curtailment_dispute(dispute))


@bp.route("/mortgage-insurance/coverage-disputes/<dispute_id>/begin-review", methods=["POST"])
def begin_dispute_review(dispute_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    dispute = get_dispute(dispute_id)
    if dispute["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The dispute is not in a state from which review may begin.",
        )

    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return ok_object(ser.curtailment_dispute(dispute))


@bp.route("/mortgage-insurance/coverage-disputes/<dispute_id>/decide", methods=["POST"])
def decide_dispute(dispute_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    dispute = get_dispute(dispute_id)
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "The dispute is not in a state from which a decision may be recorded.",
        )

    payload = body()
    decision = require_string(payload, "decision")
    require_string(payload, "decision_reason")

    wf.decide_dispute(dispute, decision, payload.get("decision_reason"))
    return ok_object(ser.curtailment_dispute(dispute))


# =============================================================================
# Reinsurance cessions
# =============================================================================

@bp.route("/mortgage-insurance/reinsurance-cessions", methods=["POST"])
def create_cession():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)

    payload = body()
    claim_id = require_string(payload, "claim_id")
    ceded_amount_cents = require_int(payload, "ceded_amount_cents")
    expected_loan_version = require_int(payload, "expected_loan_version")

    claim = resolve_body_claim(claim_id)
    loan = get_loan(claim["loan_id"])

    record = wf.record_cession(claim, loan, ceded_amount_cents, expected_loan_version)
    return ok_object(ser.reinsurance_cession(record), 201)


@bp.route("/mortgage-insurance/reinsurance-cessions", methods=["GET"])
def list_cessions():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)

    rows = list(db.reinsurance_cessions.values())
    for name in ("claim_id", "loan_id", "treaty_id", "status"):
        value = filter_value(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]

    items, limit, offset, total = list_response(ser.reinsurance_cession, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/reinsurance-cessions/<cession_id>", methods=["GET"])
def get_cession_route(cession_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)
    return ok_object(ser.reinsurance_cession(get_cession(cession_id)))