"""Routes: credit applications - intake, decisioning, revision cycle."""
from decimal import Decimal

from flask import Blueprint, g

from core import (
    store, clock, new_rec, bump, stamp, putdt, dtv, fail, ok, list_response,
    require_roles, scope_dealer_id, scope_body_dealer_id, get_body,
    v_str, v_int, v_enum, v_dt, v_id, get_dealer, get_application,
    qfilter, is_dealer_principal, serialize, ALL_ROLES,
    MAX_DTI_PCT, PROGRAM_MAX_MARKUP_BPS, MAX_RESUBMISSIONS,
)
import services as S

bp = Blueprint("applications", __name__)


@bp.route("/lending/applications", methods=["POST"])
def create_application():
    require_roles("DealerPrincipal")
    body = get_body()
    scope_body_dealer_id(body)

    dealer_id = v_id(body, "dealer_id", required=True)
    applicant_reference = v_str(body, "applicant_reference", required=True, min_len=1, max_len=64)
    cohort = v_enum(body, "monitoring_cohort", ("CONTROL", "MONITORED"), required=True)
    credit_score = v_int(body, "credit_score", required=True, minimum=300, maximum=900)
    income = v_int(body, "monthly_income_cents", required=True, minimum=1)
    debt = v_int(body, "monthly_debt_cents", required=True, minimum=0)
    amount = v_int(body, "amount_financed_cents", required=True, minimum=1)
    collateral = v_int(body, "collateral_value_cents", required=True, minimum=1)
    term = v_int(body, "term_months", required=True, minimum=12, maximum=96)
    model_year = v_int(body, "vehicle_model_year", required=True, minimum=1990, maximum=2030)
    requested_apr = v_int(body, "requested_apr_bps", required=True, minimum=0, maximum=3600)

    dealer = get_dealer(dealer_id)
    if dealer["status"] != "ACTIVE":
        fail("ERR_DEALER_NOT_ACTIVE", "The dealership is not ACTIVE.")

    app = new_rec()
    app["dealer_id"] = dealer_id
    app["agreement_id"] = None
    app["rate_sheet_id"] = None
    app["assigned_tier_id"] = None
    app["applicant_reference"] = applicant_reference
    app["monitoring_cohort"] = cohort
    app["credit_score"] = credit_score
    app["monthly_income_cents"] = income
    app["monthly_debt_cents"] = debt
    app["amount_financed_cents"] = amount
    app["collateral_value_cents"] = collateral
    app["term_months"] = term
    app["vehicle_model_year"] = model_year
    app["requested_apr_bps"] = requested_apr
    S.compute_ratios(app)
    app["base_tier_code"] = None
    app["demotion_count"] = 0
    app["assigned_tier_code"] = None
    app["buy_rate_apr_bps"] = None
    app["max_contract_apr_bps"] = None
    app["status"] = "SUBMITTED"
    app["held_from_status"] = None
    app["resubmission_count"] = 0
    app["stipulation_count"] = 0
    app["decisioned_by_user_id"] = None
    stamp(app, "decisioned_at", None)
    app["decline_reason"] = None
    store.applications[app["id"]] = app
    return ok(serialize(app), 201)


@bp.route("/lending/applications/<application_id>", methods=["GET"])
def read_application(application_id):
    require_roles(*ALL_ROLES)
    app = get_application(application_id)
    scope_dealer_id(app["dealer_id"])
    return ok(serialize(app))


@bp.route("/lending/applications", methods=["GET"])
def list_applications():
    require_roles(*ALL_ROLES)
    records = list(store.applications.values())
    if is_dealer_principal():
        records = [a for a in records if a["dealer_id"] == g.user_id]
    for name in ("dealer_id", "status", "agreement_id", "rate_sheet_id", "assigned_tier_id"):
        value = qfilter(name)
        if value is not None:
            records = [a for a in records if a.get(name) == value]
    records.sort(key=lambda a: (a.get("created_at") or "", a.get("_seq") or 0))
    return list_response(records)


def _run_pricing(app, dealer):
    """PRD 3.3 steps one through five, in the pinned order."""
    sheet = S.select_rate_sheet(dealer)
    if sheet is None:
        fail("ERR_NO_EFFECTIVE_RATE_SHEET", "No PUBLISHED rate sheet is effective for this program.")
    agreement = S.select_agreement(dealer)
    if agreement is None:
        fail("ERR_NO_INFORCE_AGREEMENT", "No ACTIVE dealer agreement is in force.")

    tiers = S.sheet_tiers(sheet["id"])
    base_index = None
    for index, tier in enumerate(tiers):
        if tier["min_credit_score"] <= app["credit_score"] <= tier["max_credit_score"]:
            base_index = index
            break
    if base_index is None:
        fail("ERR_NO_ELIGIBLE_TIER", "The credit score falls in no tier band.")

    base_tier = tiers[base_index]
    demotion_count = 0
    if S.ltv_decimal(app) > Decimal(base_tier["max_ltv_pct"]):
        demotion_count += 1
    if app["term_months"] > base_tier["max_term_months"]:
        demotion_count += 1
    final_index = base_index + demotion_count
    if final_index > len(tiers) - 1:
        fail("ERR_NO_ELIGIBLE_TIER", "Demotion pushes the tier index past the last tier.")

    if S.dti_decimal(app) > MAX_DTI_PCT:
        fail("ERR_DTI_EXCEEDED", "The debt-to-income ratio exceeds the ceiling.")

    assigned = tiers[final_index]
    return sheet, agreement, base_tier, demotion_count, assigned


@bp.route("/lending/applications/<application_id>/decision", methods=["POST"])
def decision_application(application_id):
    require_roles("CreditAnalyst")
    app = get_application(application_id)
    body = get_body()
    outcome = v_enum(body, "outcome", ("APPROVE", "CONDITION", "DECLINE"), required=True)
    stipulation_count = v_int(body, "stipulation_count", required=False, minimum=0, default=None)
    decision_note = v_str(body, "decision_note", required=False, min_len=1, max_len=None, default=None)

    if outcome in ("APPROVE", "CONDITION"):
        if app["status"] not in ("SUBMITTED", "RESUBMITTED"):
            fail("ERR_INVALID_STATE", "This outcome is not permitted from status %s." % app["status"])
    else:
        if app["status"] not in ("SUBMITTED", "RESUBMITTED", "CONDITIONED"):
            fail("ERR_INVALID_STATE", "This outcome is not permitted from status %s." % app["status"])

    dealer = get_dealer(app["dealer_id"])
    if dealer["compliance_hold"]:
        fail("ERR_DEALER_COMPLIANCE_HOLD", "The dealership is under a compliance hold.")
    if dealer["status"] != "ACTIVE":
        fail("ERR_DEALER_NOT_ACTIVE", "The dealership is not ACTIVE.")

    if outcome == "APPROVE":
        sheet, agreement, base_tier, demotion_count, assigned = _run_pricing(app, dealer)
        app["rate_sheet_id"] = sheet["id"]
        app["agreement_id"] = agreement["id"]
        app["assigned_tier_id"] = assigned["id"]
        app["base_tier_code"] = base_tier["tier_code"]
        app["demotion_count"] = demotion_count
        app["assigned_tier_code"] = assigned["tier_code"]
        app["buy_rate_apr_bps"] = assigned["buy_rate_apr_bps"]
        app["max_contract_apr_bps"] = (
            assigned["buy_rate_apr_bps"]
            + min(agreement["max_participation_bps"], PROGRAM_MAX_MARKUP_BPS)
        )
        app["status"] = "APPROVED"
    elif outcome == "CONDITION":
        agreement = S.select_agreement(dealer)
        if agreement is None:
            fail("ERR_NO_INFORCE_AGREEMENT", "No ACTIVE dealer agreement is in force.")
        app["agreement_id"] = agreement["id"]
        app["stipulation_count"] = stipulation_count if stipulation_count is not None else 1
        app["status"] = "CONDITIONED"
    else:
        app["decline_reason"] = decision_note if decision_note else "ANALYST_DECLINE"
        app["status"] = "DECLINED"

    app["decisioned_by_user_id"] = g.user_id
    stamp(app, "decisioned_at", clock.now())
    bump(app)
    return ok(serialize(app))


@bp.route("/lending/applications/<application_id>/resubmit", methods=["POST"])
def resubmit_application(application_id):
    require_roles("DealerPrincipal")
    app = get_application(application_id)
    scope_dealer_id(app["dealer_id"])
    body = get_body()
    credit_score = v_int(body, "credit_score", required=False, minimum=300, maximum=900, default=None)
    amount = v_int(body, "amount_financed_cents", required=False, minimum=1, default=None)
    collateral = v_int(body, "collateral_value_cents", required=False, minimum=1, default=None)
    term = v_int(body, "term_months", required=False, minimum=12, maximum=96, default=None)
    requested_apr = v_int(body, "requested_apr_bps", required=False, minimum=0, maximum=3600, default=None)

    if app["status"] != "CONDITIONED":
        fail("ERR_INVALID_STATE", "Only a CONDITIONED application may be resubmitted.")
    dealer = get_dealer(app["dealer_id"])
    if dealer["status"] != "ACTIVE":
        fail("ERR_DEALER_NOT_ACTIVE", "The dealership is not ACTIVE.")
    if app["resubmission_count"] >= MAX_RESUBMISSIONS:
        fail("ERR_RESUBMISSION_LIMIT", "The revision limit has been reached.")

    if credit_score is not None:
        app["credit_score"] = credit_score
    if amount is not None:
        app["amount_financed_cents"] = amount
    if collateral is not None:
        app["collateral_value_cents"] = collateral
    if term is not None:
        app["term_months"] = term
    if requested_apr is not None:
        app["requested_apr_bps"] = requested_apr

    app["resubmission_count"] += 1
    S.compute_ratios(app)
    app["status"] = "RESUBMITTED"
    bump(app)
    return ok(serialize(app))
