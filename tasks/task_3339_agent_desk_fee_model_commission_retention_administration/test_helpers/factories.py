"""Payload factories — one per entity, input fields only (PRD §4)."""
from .constants import FIXTURE, OPEN_ENDED_SENTINEL, REVIEW_LADDER


def create_office_payload(**overrides) -> dict:
    defaults = {
        "office_name": FIXTURE["OFFICE_NAME"],
        "market_code": FIXTURE["OFFICE_MARKET"],
        "recruiting_target_agents": FIXTURE["OFFICE_TARGET"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "schedule_name": FIXTURE["SCHEDULE_NAME"],
        "desk_fee_cents": FIXTURE["DESK_FEE_CENTS"],
        "overhead_share_bps": FIXTURE["OVERHEAD_SHARE_BPS"],
        "retention_bps": FIXTURE["RETENTION_BPS"],
        "referral_fee_bps": FIXTURE["REFERRAL_FEE_BPS"],
        "tech_subscription_monthly_cents": FIXTURE["TECH_MONTHLY_CENTS"],
        "marketing_monthly_cents": FIXTURE["MARKETING_MONTHLY_CENTS"],
        "effective_from": FIXTURE["SCHED_FROM"],
        "effective_to": OPEN_ENDED_SENTINEL,
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": FIXTURE["ALICE_NAME"],
        "email": FIXTURE["ALICE_EMAIL"],
        "license_number": FIXTURE["ALICE_LICENSE"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_assignment_payload(fee_schedule_id, expected_agent_version, **overrides) -> dict:
    defaults = {
        "fee_schedule_id": fee_schedule_id,
        "effective_from": FIXTURE["SCHED_FROM"],
        "effective_to": OPEN_ENDED_SENTINEL,
        "expected_agent_version": expected_agent_version,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "listing_reference": FIXTURE["OFFER_LISTING"],
        "buyer_name": FIXTURE["OFFER_BUYER"],
        "offer_price_cents": FIXTURE["OFFER_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(listing_agent_id, selling_agent_id, offer_id, **overrides) -> dict:
    defaults = {
        "listing_agent_id": listing_agent_id,
        "selling_agent_id": selling_agent_id,
        "offer_id": offer_id,
        "sale_price_cents": FIXTURE["TXN_SALE_PRICE_CENTS"],
        "gross_commission_cents": FIXTURE["TXN_GCI_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_cda_payload(**overrides) -> dict:
    defaults = {"review_ladder": list(REVIEW_LADDER)}
    defaults.update(overrides)
    return defaults


def pay_invoice_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def advance_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def generate_invoices_payload(billing_month=FIXTURE["BILLING_MONTH"], **overrides) -> dict:
    defaults = {"billing_month": billing_month}
    defaults.update(overrides)
    return defaults


def create_manual_invoice_payload(office_id, agent_id, billing_month, lines, **overrides) -> dict:
    defaults = {
        "office_id": office_id,
        "agent_id": agent_id,
        "billing_month": billing_month,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_referral_agreement_payload(referring_office_id, receiving_office_id,
                                      agent_id, referral_fee_bps, **overrides) -> dict:
    defaults = {
        "referring_office_id": referring_office_id,
        "receiving_office_id": receiving_office_id,
        "agent_id": agent_id,
        "referral_fee_bps": referral_fee_bps,
    }
    defaults.update(overrides)
    return defaults


def compute_retention_payload(period_month, **overrides) -> dict:
    defaults = {"period_month": period_month, "report_variant": "CHURN"}
    defaults.update(overrides)
    return defaults


def review_payload(verdict) -> dict:
    return {"verdict": verdict}
