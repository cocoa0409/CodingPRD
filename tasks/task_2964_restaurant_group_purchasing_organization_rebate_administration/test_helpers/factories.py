"""Payload factories.

Every money field is an integer number of cents (never a string, never a
float), every proportion is whole basis points, calendar dates are
"YYYY-MM-DD" strings and instants carry exactly three fractional digits.
Each factory accepts **overrides so a test can vary exactly one field.
"""
from . import constants as C
from .types import LetterScope, RateType


def program_tier_payload(**overrides) -> dict:
    payload = dict(C.ELITE_TIER)
    payload.update(overrides)
    return payload


def distributor_payload(**overrides) -> dict:
    payload = {
        "name": C.DISTRIBUTOR_NAME,
        "dba_code": C.DISTRIBUTOR_DBA_CODE,
        "contracted_markup_bps": C.DISTRIBUTOR_MARKUP_BPS,
    }
    payload.update(overrides)
    return payload


def member_payload(tier_id: str, **overrides) -> dict:
    payload = {
        "legal_name": C.MEMBER_LEGAL_NAME,
        "tier_id": tier_id,
        "committed_annual_spend_cents": C.MEMBER_COMMITTED_ANNUAL_SPEND_CENTS,
    }
    payload.update(overrides)
    return payload


def authorization_letter_payload(member_id: str, distributor_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "distributor_id": distributor_id,
        "effective_from": C.LETTER_FROM,
        "effective_to": C.LETTER_TO,
        "signatory_name": C.SIGNATORY_NAME,
        "scope": LetterScope.PURCHASE_DATA_AND_PRICING.value,
    }
    payload.update(overrides)
    return payload


def deal_payload(**overrides) -> dict:
    payload = {
        "manufacturer_name": C.DEAL_MANUFACTURER_NAME,
        "deal_code": C.DEAL_CODE,
        "effective_from": C.DEAL_FROM,
        "effective_to": C.DEAL_TO,
        "required_purchase_window_days": C.REQUIRED_PURCHASE_WINDOW_DAYS,
    }
    payload.update(overrides)
    return payload


def second_deal_payload(**overrides) -> dict:
    payload = deal_payload(
        manufacturer_name=C.SECOND_DEAL_MANUFACTURER_NAME,
        deal_code=C.SECOND_DEAL_CODE,
    )
    payload.update(overrides)
    return payload


def contracted_item_payload(deal_id: str, **overrides) -> dict:
    payload = {
        "deal_id": deal_id,
        "manufacturer_sku": C.BEEF_SKU,
        "normalized_item_key": C.BEEF_KEY,
        "pack_size": C.BEEF_PACK_SIZE,
        "baseline_unit_cost_cents": C.BEEF_BASELINE_UNIT_COST_CENTS,
        "contract_unit_cost_cents": C.BEEF_CONTRACT_UNIT_COST_CENTS,
    }
    payload.update(overrides)
    return payload


def fries_item_payload(deal_id: str, **overrides) -> dict:
    payload = contracted_item_payload(
        deal_id,
        manufacturer_sku=C.FRIES_SKU,
        normalized_item_key=C.FRIES_KEY,
        pack_size=C.FRIES_PACK_SIZE,
        baseline_unit_cost_cents=C.FRIES_BASELINE_UNIT_COST_CENTS,
        contract_unit_cost_cents=C.FRIES_CONTRACT_UNIT_COST_CENTS,
    )
    payload.update(overrides)
    return payload


def chicken_item_payload(deal_id: str, **overrides) -> dict:
    payload = contracted_item_payload(
        deal_id,
        manufacturer_sku=C.CHICKEN_SKU,
        normalized_item_key=C.CHICKEN_KEY,
        pack_size=C.CHICKEN_PACK_SIZE,
        baseline_unit_cost_cents=C.CHICKEN_BASELINE_UNIT_COST_CENTS,
        contract_unit_cost_cents=C.CHICKEN_CONTRACT_UNIT_COST_CENTS,
    )
    payload.update(overrides)
    return payload


def flat_rate_card_payload(item_id: str, expected_version: int, **overrides) -> dict:
    """PER_CASE card: carries flat_rate_cents_per_case and nothing else."""
    payload = {
        "contracted_item_id": item_id,
        "expected_contracted_item_version": expected_version,
        "rate_type": RateType.PER_CASE.value,
        "flat_rate_cents_per_case": C.FLAT_RATE_CENTS_PER_CASE,
        "effective_from": C.CARD_FROM,
        "effective_to": C.CARD_TO,
    }
    payload.update(overrides)
    return payload


def percent_rate_card_payload(
    item_id: str, expected_version: int, percent_bps: int = 250, **overrides
) -> dict:
    """PERCENT_OF_SPEND card: carries percent_bps and nothing else."""
    payload = {
        "contracted_item_id": item_id,
        "expected_contracted_item_version": expected_version,
        "rate_type": RateType.PERCENT_OF_SPEND.value,
        "percent_bps": percent_bps,
        "effective_from": C.CARD_FROM,
        "effective_to": C.CARD_TO,
    }
    payload.update(overrides)
    return payload


def tiered_rate_card_payload(
    item_id: str, expected_version: int, tier_breaks=None, **overrides
) -> dict:
    """TIERED_VOLUME card: carries tier_breaks and nothing else."""
    payload = {
        "contracted_item_id": item_id,
        "expected_contracted_item_version": expected_version,
        "rate_type": RateType.TIERED_VOLUME.value,
        "tier_breaks": [dict(b) for b in (tier_breaks or C.TIER_BREAKS)],
        "effective_from": C.CARD_FROM,
        "effective_to": C.CARD_TO,
    }
    payload.update(overrides)
    return payload


def purchase_batch_payload(distributor_id: str, **overrides) -> dict:
    payload = {
        "distributor_id": distributor_id,
        "period_start": C.JUNE_START,
        "period_end": C.JUNE_END,
        "source_reference": C.JUNE_BATCH_REFERENCE,
    }
    payload.update(overrides)
    return payload


def july_batch_payload(distributor_id: str, **overrides) -> dict:
    payload = purchase_batch_payload(
        distributor_id,
        period_start=C.JULY_START,
        period_end=C.JULY_END,
        source_reference=C.JULY_BATCH_REFERENCE,
    )
    payload.update(overrides)
    return payload


def purchase_line_payload(batch_id: str, member_id: str, **overrides) -> dict:
    payload = {
        "purchase_batch_id": batch_id,
        "member_id": member_id,
        "distributor_sku": C.BEEF_DISTRIBUTOR_SKU,
        "vendor_item_description": C.BEEF_DESCRIPTION,
        "normalized_item_key_reported": C.BEEF_KEY,
        "cases_shipped": C.LINE_A_CASES,
        "invoice_unit_cost_cents": C.INVOICE_UNIT_COST_CENTS,
        "distributor_base_cost_cents": C.LINE_A_BASE_COST_CENTS,
        "invoice_date": C.LINE_A_INVOICE_DATE,
    }
    payload.update(overrides)
    return payload


def fries_line_payload(batch_id: str, member_id: str, **overrides) -> dict:
    payload = purchase_line_payload(
        batch_id,
        member_id,
        distributor_sku=C.FRIES_DISTRIBUTOR_SKU,
        vendor_item_description=C.FRIES_DESCRIPTION,
        normalized_item_key_reported=C.FRIES_KEY,
        cases_shipped=20,
        invoice_unit_cost_cents=8300,
        distributor_base_cost_cents=7500,
        invoice_date="2026-06-20",
    )
    payload.update(overrides)
    return payload


def chicken_line_payload(batch_id: str, member_id: str, **overrides) -> dict:
    payload = purchase_line_payload(
        batch_id,
        member_id,
        distributor_sku=C.CHICKEN_DISTRIBUTOR_SKU,
        vendor_item_description=C.CHICKEN_DESCRIPTION,
        normalized_item_key_reported=C.CHICKEN_KEY,
        cases_shipped=25,
        invoice_unit_cost_cents=7000,
        distributor_base_cost_cents=6600,
        invoice_date="2026-06-12",
    )
    payload.update(overrides)
    return payload


def claim_payload(
    deal_id: str,
    expected_deal_version: int,
    claimed_units: int,
    claimed_amount_cents: int,
    **overrides,
) -> dict:
    payload = {
        "deal_id": deal_id,
        "expected_deal_version": expected_deal_version,
        "period_start": C.JUNE_START,
        "period_end": C.JUNE_END,
        "claimed_units": claimed_units,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def dispute_payload(accrual_id: str, disputed_amount_cents: int, reason_code: str,
                    claim_id=None, **overrides) -> dict:
    payload = {
        "accrual_id": accrual_id,
        "reason_code": reason_code,
        "disputed_amount_cents": disputed_amount_cents,
    }
    if claim_id is not None:
        payload["claim_id"] = claim_id
    payload.update(overrides)
    return payload


def compliance_review_payload(
    member_id: str, deal_id: str, window_start: str, window_end: str, **overrides
) -> dict:
    payload = {
        "member_id": member_id,
        "deal_id": deal_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def savings_report_params(period_start: str, period_end: str, basis=None) -> dict:
    params = {"period_start": period_start, "period_end": period_end}
    if basis is not None:
        params["basis"] = basis
    return params
