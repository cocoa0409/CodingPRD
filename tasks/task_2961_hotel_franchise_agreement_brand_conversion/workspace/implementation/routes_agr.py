"""License drafting, execution, the onboarding ladders, opening, the fee ledger
and the whole exit path (PRD 3.6, 3.8 and 3.9)."""

from flask import Blueprint

import calc
import domain
import envelope
import store
import validation
from auth import ALL_ROLES, ROLE_BSD, ROLE_FDM, ROLE_OWNER, ROLE_QA, authenticate
from common import (
    ZERO,
    add_days,
    clock_now,
    fmt_date,
    fmt_instant,
    month_span,
    parse_date,
    parse_instant,
)
from errors import ApiError
from serialize import dump, dump_all
from store import touch

bp = Blueprint("agreements", __name__)

TERMINATION_CAUSES = ("FOR_CAUSE_QA", "FOR_CAUSE_PIP", "MUTUAL")
LD_FORMULA_BY_CAUSE = {
    "FOR_CAUSE_QA": "CONTRACTUAL_MULTIPLE",
    "FOR_CAUSE_PIP": "CONTRACTUAL_MULTIPLE",
    "MUTUAL": "DISCOUNTED_PV",
}
TERMINATION_PRECONDITION = {
    "FOR_CAUSE_QA": ("TERMINATION_ELIGIBLE",),
    "FOR_CAUSE_PIP": ("DEFAULT_NOTICE", "TERMINATION_ELIGIBLE"),
    "MUTUAL": None,
}
OPENABLE_PIP_STATUSES = ("ACCEPTED", "IN_PROGRESS", "COMPLETED")
SUSPENDABLE_PIP_STATUSES = ("ACCEPTED", "IN_PROGRESS", "DEFAULTED")


def _pips_of(agreement):
    return store.ordered(store.pips, lambda p: p["agreement_id"] == agreement["id"])


# ---------------------------------------------------------------------------
# Drafting and reads
# ---------------------------------------------------------------------------


@bp.post("/applications/<application_id>/agreements")
def draft_agreement(application_id):
    authenticate((ROLE_FDM,))
    application = store.get_application(application_id)
    payload = validation.body()
    fields = validation.take(
        payload, [{"name": "effective_date", "type": "date", "required": True}]
    )
    if application["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_STAGE_INVALID")
    if application["financial_review_status"] != "PASSED":
        raise ApiError("ERR_FINANCIAL_REVIEW_NOT_PASSED")

    brand = domain.brand_of_application(application)
    owner = domain.owner_of_application(application)
    effective_date = fields["effective_date"]
    royalty, marketing, term_years, expiry = calc.license_terms(
        application, brand, owner, effective_date
    )
    row = domain.new_agreement_row()
    row["application_id"] = application["id"]
    row["brand_code"] = brand["code"]
    row["royalty_rate_pct"] = royalty
    row["marketing_fund_rate_pct"] = marketing
    row["term_years"] = term_years
    row["effective_date"] = fmt_date(effective_date)
    row["expiry_date"] = fmt_date(expiry)
    store.agreements[row["id"]] = row
    return envelope.created(dump(row))


@bp.get("/applications/<application_id>/agreements")
def list_application_agreements(application_id):
    principal = authenticate((ROLE_FDM, ROLE_BSD, ROLE_OWNER))
    application = store.get_application(application_id)
    domain.require_application_owner(principal, application)
    limit, offset = envelope.pagination()
    status = validation.query_filter("status")
    rows = store.ordered(
        store.agreements,
        lambda a: a["application_id"] == application["id"]
        and (status is None or a["status"] == status),
    )
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.get("/agreements/<agreement_id>")
def read_agreement(agreement_id):
    principal = authenticate(ALL_ROLES)
    agreement = store.get_agreement(agreement_id)
    domain.require_agreement_owner(principal, agreement)
    return envelope.ok(dump(agreement))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@bp.post("/agreements/<agreement_id>/execute")
def execute_agreement(agreement_id):
    authenticate((ROLE_FDM,))
    agreement = store.get_agreement(agreement_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [{"name": "expected_application_version", "type": "integer", "required": True}],
    )
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_DRAFT")
    application = domain.application_of_agreement(agreement)
    if application["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_STAGE_INVALID")
    if application["financial_review_status"] != "PASSED":
        raise ApiError("ERR_FINANCIAL_REVIEW_NOT_PASSED")
    owner = domain.owner_of_application(application)
    if application["capacity_basis"] == "PORTFOLIO_ADJUSTED":
        live_band = owner["capacity_band_portfolio_adjusted"]
    else:
        live_band = owner["capacity_band_standalone"]
    if live_band == "INSUFFICIENT":
        raise ApiError("ERR_OWNER_CAPACITY_INSUFFICIENT")
    if fields["expected_application_version"] != application["version"]:
        raise ApiError("ERR_STALE_APPLICATION_VERSION")

    agreement["status"] = "EXECUTED"
    agreement["executed_at"] = domain.now()
    touch(agreement)
    touch(application)
    if owner["status"] == "PROSPECT":
        owner["status"] = "ACTIVE"
        touch(owner)
    return envelope.ok(dump(agreement))


# ---------------------------------------------------------------------------
# The three onboarding ladders
# ---------------------------------------------------------------------------


@bp.post("/agreements/<agreement_id>/onboarding-milestone")
def onboarding_milestone(agreement_id):
    authenticate((ROLE_FDM,))
    agreement = store.get_agreement(agreement_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "track", "type": "string", "required": True, "min_len": 1},
            {"name": "to_status", "type": "string", "required": True, "min_len": 1},
        ],
    )
    if agreement["status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTED")
    rung = domain.ONBOARDING_RUNGS.get((fields["track"], fields["to_status"]))
    if rung is None:
        raise ApiError("ERR_ONBOARDING_SEQUENCE_INVALID")
    field, prereq_field, prereq_value = rung
    if prereq_field is not None and agreement[prereq_field] != prereq_value:
        raise ApiError("ERR_ONBOARDING_SEQUENCE_INVALID")
    agreement[field] = fields["to_status"]
    touch(agreement)
    return envelope.ok(dump(agreement))


# ---------------------------------------------------------------------------
# Opening the hotel
# ---------------------------------------------------------------------------


@bp.post("/agreements/<agreement_id>/open")
def open_agreement(agreement_id):
    authenticate((ROLE_BSD,))
    agreement = store.get_agreement(agreement_id)
    validation.body()
    if agreement["status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTED")

    pip = store.pip_of_agreement(agreement)
    items = store.items_of_pip(pip) if pip is not None else []
    if any(i["category"] == "LIFE_SAFETY" and i["status"] != "VERIFIED" for i in items):
        raise ApiError("ERR_LIFE_SAFETY_ITEM_OPEN")
    if any(i["priority"] == "CRITICAL" and i["status"] != "VERIFIED" for i in items):
        raise ApiError("ERR_CRITICAL_PIP_ITEMS_OPEN")
    if (
        agreement["training_status"] != "COMPLETED"
        or agreement["systems_status"] != "VALIDATED"
    ):
        raise ApiError("ERR_ONBOARDING_INCOMPLETE")
    if agreement["channel_status"] != "CONNECTED":
        raise ApiError("ERR_CHANNEL_NOT_CONNECTED")
    if pip is None or pip["status"] not in OPENABLE_PIP_STATUSES:
        raise ApiError("ERR_PIP_NOT_ACCEPTED")

    agreement["status"] = "OPEN"
    agreement["opened_at"] = domain.now()
    touch(agreement)
    return envelope.ok(dump(agreement))


# ---------------------------------------------------------------------------
# The fee ledger
# ---------------------------------------------------------------------------


@bp.post("/agreements/<agreement_id>/revenue-reports")
def report_revenue(agreement_id):
    principal = authenticate((ROLE_OWNER,))
    agreement = store.get_agreement(agreement_id)
    domain.require_agreement_owner(principal, agreement)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "period_month", "type": "month", "required": True},
            {"name": "gross_room_revenue", "type": "number", "required": True,
             "minimum": "0.00"},
            {"name": "correction", "type": "boolean", "required": False,
             "default": False},
        ],
    )
    if agreement["status"] != "OPEN":
        raise ApiError("ERR_AGREEMENT_NOT_OPEN")

    period_month = fields["period_month"]
    correction = bool(fields["correction"])
    surviving = [
        e
        for e in agreement["revenue_periods"]
        if e["period_month"] == period_month and not e["superseded"]
    ]
    if correction and not surviving:
        raise ApiError("ERR_DUPLICATE_REVENUE_PERIOD")
    if not correction and surviving:
        raise ApiError("ERR_DUPLICATE_REVENUE_PERIOD")

    gross = fields["gross_room_revenue"]
    royalty, marketing, reservation, total = calc.monthly_fees(
        gross, agreement["royalty_rate_pct"], agreement["marketing_fund_rate_pct"]
    )
    if correction:
        for entry in surviving:
            entry["superseded"] = True
    agreement["revenue_periods"].append(
        {
            "period_month": period_month,
            "gross_room_revenue": gross,
            "royalty_fee": royalty,
            "marketing_fee": marketing,
            "reservation_fee": reservation,
            "period_total_fee": total,
            "superseded": False,
        }
    )
    calc.recompute_ledger(agreement)
    touch(agreement)
    return envelope.ok(dump(agreement))


@bp.get("/agreements/<agreement_id>/fee-summary")
def fee_summary(agreement_id):
    principal = authenticate((ROLE_FDM, ROLE_BSD, ROLE_OWNER))
    agreement = store.get_agreement(agreement_id)
    domain.require_agreement_owner(principal, agreement)
    return envelope.ok(
        {
            "agreement_id": agreement["id"],
            "royalty_rate_pct": agreement["royalty_rate_pct"],
            "marketing_fund_rate_pct": agreement["marketing_fund_rate_pct"],
            "reported_period_count": agreement["reported_period_count"],
            "royalty_fee_to_date": agreement["royalty_fee_to_date"],
            "marketing_fund_contributed_total": agreement[
                "marketing_fund_contributed_total"
            ],
            "reservation_fee_to_date": agreement["reservation_fee_to_date"],
            "total_fees_assessed": agreement["total_fees_assessed"],
        }
    )


# ---------------------------------------------------------------------------
# Termination and the post-termination file
# ---------------------------------------------------------------------------


@bp.post("/agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    authenticate((ROLE_BSD,))
    agreement = store.get_agreement(agreement_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "cause", "type": "enum", "required": True,
             "values": TERMINATION_CAUSES},
            {"name": "termination_notes", "type": "string", "required": True,
             "min_len": 1},
        ],
    )
    if agreement["status"] != "OPEN":
        raise ApiError("ERR_AGREEMENT_NOT_OPEN")
    cause = fields["cause"]
    allowed = TERMINATION_PRECONDITION[cause]
    if allowed is not None and agreement["compliance_status"] not in allowed:
        raise ApiError("ERR_TERMINATION_NOT_ELIGIBLE")

    stamp = domain.now()
    formula = LD_FORMULA_BY_CAUSE[cause]
    trailing_avg = calc.trailing_average_fee(agreement)
    remaining = month_span(
        parse_date(agreement["expiry_date"]), parse_instant(stamp)
    )
    capped = min(remaining, int(agreement["liquidated_damages_cap_months"]))

    agreement["status"] = "TERMINATION_PENDING"
    agreement["termination_cause"] = cause
    agreement["termination_notes"] = fields["termination_notes"]
    agreement["terminated_at"] = stamp
    agreement["liquidated_damages_formula"] = formula
    agreement["trailing_avg_monthly_fee"] = trailing_avg
    agreement["remaining_term_months_at_termination"] = remaining
    agreement["liquidated_damages_amount"] = calc.liquidated_damages(
        formula, trailing_avg, capped
    )
    agreement["de_identification_status"] = "PENDING"
    agreement["de_identification_deadline"] = fmt_instant(
        add_days(parse_instant(stamp), calc.DE_IDENTIFICATION_DAYS)
    )
    agreement["post_termination_status"] = "OPEN"
    if agreement["channel_status"] == "CONNECTED":
        agreement["channel_status"] = "SUSPENDED"
    touch(agreement)

    for pip in _pips_of(agreement):
        if pip["status"] in SUSPENDABLE_PIP_STATUSES:
            pip["status"] = "SUSPENDED"
            touch(pip)
    return envelope.ok(dump(agreement))


@bp.post("/agreements/<agreement_id>/de-identification")
def de_identification(agreement_id):
    principal = authenticate((ROLE_OWNER,))
    agreement = store.get_agreement(agreement_id)
    domain.require_agreement_owner(principal, agreement)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "items_completed", "type": "array", "required": True,
             "values": calc.DE_IDENTIFICATION_ITEMS},
        ],
    )
    if agreement["status"] != "TERMINATION_PENDING":
        raise ApiError("ERR_AGREEMENT_NOT_TERMINATION_PENDING")
    submitted = fields["items_completed"]
    if any(code not in submitted for code in calc.DE_IDENTIFICATION_ITEMS):
        raise ApiError("ERR_DEIDENTIFICATION_INCOMPLETE")

    agreement["de_identification_items_completed"] = list(submitted)
    deadline = agreement["de_identification_deadline"]
    if deadline is not None and domain.now() > deadline:
        agreement["de_identification_status"] = "BREACHED"
        agreement["de_identification_breach_penalty"] = (
            calc.DE_IDENTIFICATION_BREACH_PENALTY
        )
    else:
        agreement["de_identification_status"] = "SUBMITTED"
        agreement["de_identification_breach_penalty"] = ZERO
    touch(agreement)
    return envelope.ok(dump(agreement))


@bp.post("/agreements/<agreement_id>/close-out")
def close_out(agreement_id):
    authenticate((ROLE_BSD,))
    agreement = store.get_agreement(agreement_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "liquidated_damages_settlement_amount", "type": "number",
             "required": True, "minimum": "0.00"},
            {"name": "de_identification_verified", "type": "boolean",
             "required": True},
        ],
    )
    if agreement["status"] != "TERMINATION_PENDING":
        raise ApiError("ERR_AGREEMENT_NOT_TERMINATION_PENDING")
    if agreement["de_identification_status"] not in ("SUBMITTED", "BREACHED"):
        raise ApiError("ERR_POST_TERMINATION_OBLIGATIONS_OPEN")
    if not fields["de_identification_verified"]:
        raise ApiError("ERR_POST_TERMINATION_OBLIGATIONS_OPEN")
    floor = calc.D(agreement["liquidated_damages_amount"] or ZERO) + calc.D(
        agreement["de_identification_breach_penalty"]
    )
    tendered = fields["liquidated_damages_settlement_amount"]
    if tendered < floor:
        raise ApiError("ERR_POST_TERMINATION_OBLIGATIONS_OPEN")

    agreement["status"] = "TERMINATED"
    agreement["de_identification_status"] = "VERIFIED"
    agreement["post_termination_status"] = "CLOSED"
    agreement["liquidated_damages_paid_amount"] = tendered
    agreement["closed_out_at"] = domain.now()
    touch(agreement)
    return envelope.ok(dump(agreement))
