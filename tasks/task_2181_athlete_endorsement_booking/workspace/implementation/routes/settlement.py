"""Payout statements, disbursement and renewal options."""

from flask import Blueprint

import calc
import domain
import validation as V
from auth import require
from envelope import created, ok
from errors import ApiError
from store import db, new_record, now, stamp, touch
from validation import parse_date

bp = Blueprint("settlement", __name__)


@bp.post("/payout-statements")
def create_statement():
    require("FinanceManager")
    payload = V.body()
    engagement_id = V.id_field(payload, "engagement_id")
    expected_version = V.int_field(payload, "expected_engagement_version", minimum=0)

    engagement = domain.must_get("engagements", engagement_id)

    if expected_version != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION",
                       "expected_engagement_version does not match the engagement")

    if engagement["settlement_status"] not in ("BILLABLE", "INVOICED"):
        raise ApiError("ERR_SETTLEMENT_NOT_BILLABLE", "the engagement is not billable")

    lines = [d for d in domain.engagement_deliverables(engagement_id)
             if d["status"] == "APPROVED"]
    if not lines:
        raise ApiError("ERR_NO_BILLABLE_DELIVERABLES", "no APPROVED deliverable to bill")

    # A newer statement supersedes the standing DRAFT.
    if engagement["settlement_status"] == "INVOICED":
        for standing in domain.engagement_statements(engagement_id):
            if standing["status"] == "DRAFT":
                standing["status"] = "VOIDED"
                touch(standing)

    athlete = db.athletes[engagement["athlete_id"]]
    line_values, gross, commission, penalty, net = calc.payout_distribution(
        lines, engagement.get("binding_fee_cents") or 0,
        athlete["commission_pct"], domain.penalty_sum(engagement_id),
    )

    for deliverable, value in zip(lines, line_values):
        deliverable["line_value_cents"] = value
        touch(deliverable)

    statement = new_record({
        "engagement_id": engagement_id,
        "line_count": len(lines),
        "gross_amount_cents": gross,
        "agency_commission_cents": commission,
        "penalty_cents": penalty,
        "athlete_net_cents": net,
        "status": "DRAFT",
        "disbursed_at": None,
    })
    db.payout_statements[statement["id"]] = statement

    engagement["settlement_status"] = "INVOICED"
    domain.refresh_gross_settled(engagement)
    touch(engagement)
    return created(statement)


@bp.post("/payout-statements/<statement_id>/disburse")
def disburse_statement(statement_id):
    require("FinanceManager")
    statement = domain.must_get("payout_statements", statement_id)

    if statement["status"] != "DRAFT":
        raise ApiError("ERR_PAYOUT_INVALID_STATE", "statement is not DRAFT")

    engagement = db.engagements[statement["engagement_id"]]
    statement["status"] = "DISBURSED"
    statement["disbursed_at"] = stamp()
    touch(statement)

    domain.append_ledger(engagement, "DISBURSEMENT", -statement["athlete_net_cents"],
                         "Payout disbursed to athlete", "PayoutStatement", statement["id"])
    domain.refresh_gross_settled(engagement)
    if engagement["settlement_status"] == "INVOICED":
        engagement["settlement_status"] = "SETTLED"
    touch(engagement)
    return ok(statement)


@bp.post("/renewal-options")
def create_renewal_option():
    require("TalentAgent")
    payload = V.body()
    engagement_id = V.id_field(payload, "engagement_id")
    deadline_raw, _deadline = V.date_field(payload, "option_deadline_date")
    proposed_base_fee_cents = V.int_field(payload, "proposed_base_fee_cents", minimum=1)

    engagement = domain.must_get("engagements", engagement_id)

    if engagement["contract_status"] not in ("COMPLETED", "TERMINATED") \
            or engagement.get("binding_fee_cents") is None:
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE",
                       "renewal options open only on a finished, countersigned engagement")

    athlete = db.athletes[engagement["athlete_id"]]
    figures = calc.bonus_and_renewal(
        engagement["binding_fee_cents"],
        engagement["approved_deliverable_count"],
        engagement["required_deliverable_count"],
        athlete["market_tier"],
        proposed_base_fee_cents,
    )

    option = new_record({
        "engagement_id": engagement_id,
        "option_deadline_date": deadline_raw,
        "proposed_base_fee_cents": proposed_base_fee_cents,
        "base_value_cents": figures["base_value_cents"],
        "approval_rate": figures["approval_rate"],
        "bonus_tier": figures["bonus_tier"],
        "bonus_cents": figures["bonus_cents"],
        "total_engagement_value_cents": figures["total_engagement_value_cents"],
        "renewal_fee_cents": figures["renewal_fee_cents"],
        "status": "OPEN",
        "decided_at": None,
    })
    db.renewal_options[option["id"]] = option
    return created(option)


@bp.post("/renewal-options/<option_id>/decide")
def decide_renewal_option(option_id):
    caller = require("BrandRep")
    option = domain.must_get("renewal_options", option_id)
    payload = V.body()
    decision = V.enum_field(payload, "decision", calc.RENEWAL_DECISIONS)

    engagement = db.engagements[option["engagement_id"]]
    if caller.user_id != engagement["brand_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller is not the brand on this engagement")

    if option["status"] != "OPEN":
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", "the option is no longer OPEN")

    deadline = parse_date(option["option_deadline_date"], "option_deadline_date")
    if now().date() > deadline:
        option["status"] = "LAPSED"
        touch(option)
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", "the option deadline has passed")

    option["decided_at"] = stamp()
    if decision == "EXERCISE":
        option["status"] = "EXERCISED"
        touch(option)
        domain.append_ledger(engagement, "BONUS", option["bonus_cents"],
                             "Performance bonus accrued by exercised renewal option",
                             "RenewalOption", option["id"])
        touch(engagement)
    else:
        option["status"] = "DECLINED"
        touch(option)
    return ok(option)
