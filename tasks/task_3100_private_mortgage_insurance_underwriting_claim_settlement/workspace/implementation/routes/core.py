"""Configuration and counterparty routes: the logical clock, master policies,
rate cards, reinsurance treaties, servicers, lenders, exposure reconciliation
and portfolio snapshots.
"""

from flask import Blueprint

from common import fmt_utc, parse_utc, set_clock
from db import db, new_row, touch
from errors import ERR_INVALID_REQUEST, ApiError
from middleware import (
    ROLE_BORROWER,
    ROLE_LENDER,
    ROLE_MASTER_POLICY_ADMIN,
    ROLE_SERVICER,
    ROLE_UNDERWRITER,
    authenticate,
    body,
    require_bool,
    require_enum,
    require_instant,
    require_int,
    require_number,
    require_roles,
    require_string,
)
from response import ok_array, ok_object
from services import serializers as ser
from services import workflows as wf
from services.views import (
    get_lender,
    get_master_policy,
    get_rate_card,
    get_snapshot,
    get_servicer,
    get_treaty,
    filter_value,
    list_response,
    resolve_body_loan,
    resolve_body_master_policy,
)

bp = Blueprint("core", __name__)

COVERAGE_PERCENT_SET = (12, 25, 30)
CREDIT_GRADES = ("A", "B", "C", "D")
LTV_BANDS = ("831_TO_85", "851_TO_90", "901_TO_95")
PREMIUM_PLANS = ("BPM", "SPM", "LPM")
LOSS_MITIGATION_STANDARDS = ("PARTICIPATION", "PARTICIPATION_COMPLETE")


# --- logical clock ------------------------------------------------------------

@bp.route("/mortgage-insurance/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    payload = body()
    current_utc = require_string(payload, "current_utc")
    try:
        parse_utc(current_utc)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 instant.")

    moved = set_clock(current_utc)
    # Advancing the clock can satisfy conditions that fire system-driven
    # transitions (PRD 2.5).
    wf.advance_clock_and_fire_transitions(moved)
    return ok_object({"current_utc": moved})


# --- master policies ----------------------------------------------------------

@bp.route("/mortgage-insurance/master-policies", methods=["POST"])
def create_master_policy():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    payload = body()
    row = new_row()
    row.update({
        "policy_number": require_string(payload, "policy_number"),
        "anniversary_utc": fmt_utc(require_instant(payload, "anniversary_utc", not_future=False)),
        "coverage_percent_default": require_int(
            payload, "coverage_percent_default", required=False, default=25
        ),
        "delegated_curtailment_rate": require_number(payload, "delegated_curtailment_rate"),
        "nondelagated_curtailment_rate": require_number(payload, "nondelagated_curtailment_rate"),
        "ltv_variance_tolerance": require_number(payload, "ltv_variance_tolerance"),
        "servicer_loss_mitigation_standard": require_enum(
            payload, "servicer_loss_mitigation_standard", LOSS_MITIGATION_STANDARDS
        ),
        "rescission_relief_cycles": require_int(payload, "rescission_relief_cycles"),
        "min_third_party_net_bps": require_int(payload, "min_third_party_net_bps"),
        "two_year_effective_flag": require_bool(payload, "two_year_effective_flag"),
        "exposure_contribution_rate": require_number(payload, "exposure_contribution_rate"),
        "status": "ACTIVE",
    })
    if row["coverage_percent_default"] not in COVERAGE_PERCENT_SET:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "coverage_percent_default may only be 12, 25 or 30.",
        )
    db.master_policies[row["id"]] = row
    return ok_object(ser.master_policy(row), 201)


@bp.route("/mortgage-insurance/master-policies", methods=["GET"])
def list_master_policies():
    identity = authenticate()
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_SERVICER
    )
    rows = list(db.master_policies.values())
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = list_response(ser.master_policy, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/master-policies/<policy_id>", methods=["GET"])
def get_master_policy_route(policy_id):
    identity = authenticate()
    # PRD 2.1: a Borrower is limited to reading the master policy governing its
    # loan, alongside its own loan and claims.
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER,
        ROLE_SERVICER, ROLE_BORROWER,
    )
    return ok_object(ser.master_policy(get_master_policy(policy_id)))


# --- rate cards ---------------------------------------------------------------

@bp.route("/mortgage-insurance/rate-cards", methods=["POST"])
def create_rate_card():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    payload = body()
    master_policy_id = require_string(payload, "master_policy_id")
    resolve_body_master_policy(master_policy_id)

    row = new_row()
    row.update({
        "master_policy_id": master_policy_id,
        "credit_grade": require_enum(payload, "credit_grade", CREDIT_GRADES),
        "ltv_band": require_enum(payload, "ltv_band", LTV_BANDS),
        "coverage_percent": require_int(payload, "coverage_percent"),
        "premium_plan": require_enum(payload, "premium_plan", PREMIUM_PLANS),
        "rate_bps": require_int(payload, "rate_bps"),
        "min_borrower_reserves_months": require_int(
            payload, "min_borrower_reserves_months", required=False, default=0
        ),
    })
    db.rate_cards[row["id"]] = row
    return ok_object(ser.rate_card(row), 201)


@bp.route("/mortgage-insurance/rate-cards", methods=["GET"])
def list_rate_cards():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    rows = list(db.rate_cards.values())
    master_policy_id = filter_value("master_policy_id")
    if master_policy_id is not None:
        rows = [r for r in rows if r["master_policy_id"] == master_policy_id]
    items, limit, offset, total = list_response(ser.rate_card, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/rate-cards/<rate_card_id>", methods=["GET"])
def get_rate_card_route(rate_card_id):
    identity = authenticate()
    # PRD 2.1: a Borrower may read the rate card governing its loan.
    require_roles(
        identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER, ROLE_BORROWER
    )
    return ok_object(ser.rate_card(get_rate_card(rate_card_id)))


# --- reinsurance treaties -----------------------------------------------------

@bp.route("/mortgage-insurance/reinsurance-treaties", methods=["POST"])
def create_treaty():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    payload = body()
    row = new_row()
    row.update({
        "treaty_number": require_string(payload, "treaty_number"),
        "inception_utc": fmt_utc(require_instant(payload, "inception_utc", not_future=False)),
        "expiration_utc": fmt_utc(require_instant(payload, "expiration_utc", not_future=False)),
        "retention_per_claim_cents": require_int(payload, "retention_per_claim_cents"),
        "exhaustion_per_claim_cents": require_int(payload, "exhaustion_per_claim_cents"),
        "aggregate_ceded_cap_cents": require_int(payload, "aggregate_ceded_cap_cents"),
        "status": "ACTIVE",
    })
    db.reinsurance_treaties[row["id"]] = row
    return ok_object(ser.reinsurance_treaty(row), 201)


@bp.route("/mortgage-insurance/reinsurance-treaties", methods=["GET"])
def list_treaties():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)
    rows = list(db.reinsurance_treaties.values())
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = list_response(ser.reinsurance_treaty, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/reinsurance-treaties/<treaty_id>", methods=["GET"])
def get_treaty_route(treaty_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)
    return ok_object(ser.reinsurance_treaty(get_treaty(treaty_id)))


@bp.route("/mortgage-insurance/reinsurance-treaties/<treaty_id>/cancel", methods=["POST"])
def cancel_treaty(treaty_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)
    treaty = get_treaty(treaty_id)
    treaty["status"] = "CANCELLED"
    touch(treaty)
    return ok_object(ser.reinsurance_treaty(treaty))


# --- servicers ----------------------------------------------------------------

@bp.route("/mortgage-insurance/servicers", methods=["POST"])
def create_servicer():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    payload = body()
    row = new_row()
    row.update({
        "servicer_name": require_string(payload, "servicer_name"),
        "tier": require_enum(payload, "tier", ("TIER_1", "TIER_2", "TIER_3")),
        "loss_mitigation_capability": require_enum(
            payload, "loss_mitigation_capability", LOSS_MITIGATION_STANDARDS
        ),
        "status": "ACTIVE",
    })
    db.servicers[row["id"]] = row
    return ok_object(ser.servicer(row), 201)


@bp.route("/mortgage-insurance/servicers", methods=["GET"])
def list_servicers():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_SERVICER)
    rows = list(db.servicers.values())
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = list_response(ser.servicer, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/servicers/<servicer_id>", methods=["GET"])
def get_servicer_route(servicer_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_SERVICER)
    return ok_object(ser.servicer(get_servicer(servicer_id)))


@bp.route("/mortgage-insurance/servicers/<servicer_id>/suspend", methods=["POST"])
def suspend_servicer(servicer_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)
    servicer = get_servicer(servicer_id)
    servicer["status"] = "SUSPENDED"
    touch(servicer)
    return ok_object(ser.servicer(servicer))


# --- lenders ------------------------------------------------------------------

@bp.route("/mortgage-insurance/lenders", methods=["POST"])
def create_lender():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN)

    payload = body()
    row = new_row()
    row.update({
        "lender_name": require_string(payload, "lender_name"),
        "delegated_underwriting": require_bool(payload, "delegated_underwriting"),
        "policy_exposure_cap_cents": require_int(payload, "policy_exposure_cap_cents"),
        "status": "ACTIVE",
    })
    db.lenders[row["id"]] = row
    return ok_object(ser.lender(row), 201)


@bp.route("/mortgage-insurance/lenders", methods=["GET"])
def list_lenders():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    rows = list(db.lenders.values())
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = list_response(ser.lender, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/lenders/<lender_id>", methods=["GET"])
def get_lender_route(lender_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER, ROLE_LENDER)
    return ok_object(ser.lender(get_lender(lender_id)))


@bp.route("/mortgage-insurance/lenders/<lender_id>/exposure-reconciliations", methods=["POST"])
def reconcile_exposure(lender_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)

    lender = get_lender(lender_id)

    payload = body()
    loan_id = require_string(payload, "loan_id")
    expected_loan_version = require_int(payload, "expected_loan_version")
    loan = resolve_body_loan(loan_id)

    result = wf.reconcile_lender_exposure(lender, loan, expected_loan_version)
    return ok_object(result)


# --- portfolio snapshots ------------------------------------------------------

@bp.route("/mortgage-insurance/portfolio-snapshots", methods=["POST"])
def create_snapshot():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)

    payload = body()
    snapshot_utc = fmt_utc(require_instant(payload, "snapshot_utc", not_future=False))
    threshold = require_int(payload, "cluster_in_force_threshold_cents")

    snapshot = wf.create_portfolio_snapshot(snapshot_utc, threshold)
    return ok_object(ser.portfolio_snapshot(snapshot), 201)


@bp.route("/mortgage-insurance/portfolio-snapshots", methods=["GET"])
def list_snapshots():
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)
    rows = list(db.portfolio_snapshots.values())
    status = filter_value("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = list_response(ser.portfolio_snapshot, rows)
    return ok_array(items, limit, offset, total)


@bp.route("/mortgage-insurance/portfolio-snapshots/<snapshot_id>", methods=["GET"])
def get_snapshot_route(snapshot_id):
    identity = authenticate()
    require_roles(identity, ROLE_MASTER_POLICY_ADMIN, ROLE_UNDERWRITER)
    return ok_object(ser.portfolio_snapshot(get_snapshot(snapshot_id)))