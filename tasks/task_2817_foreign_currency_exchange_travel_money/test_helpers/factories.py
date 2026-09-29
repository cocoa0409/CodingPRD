"""Payload factories - one per create/action endpoint, input fields only.

Every money amount is emitted as a Python int, never as a string: PRD 2.5 declares
US amounts in whole cents, foreign cash in whole minor units, rates in micros and
ratios in basis points, and none of them is ever a decimal or a quoted numeral.
"""

from typing import List, Optional

from .constants import TEST_DEFAULTS


def denom(denomination_minor_units: int, note_count: int) -> dict:
    """One entry of a requested/returned/manifest/delivered denomination array."""
    return {
        "denomination_minor_units": int(denomination_minor_units),
        "note_count": int(note_count),
    }


def target_line(currency_code: str, baseline_daily_minor_units: int) -> dict:
    """One entry of an inventory plan's target_lines array."""
    return {
        "currency_code": currency_code,
        "baseline_daily_minor_units": int(baseline_daily_minor_units),
    }


# --------------------------------------------------------------------------- #
# PRD 3.1 - branches, currency profiles, armored routes                        #
# --------------------------------------------------------------------------- #
def create_branch_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["BRANCH_CODE"],
        "name": TEST_DEFAULTS["BRANCH_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "vault_limit_usd_cents": TEST_DEFAULTS["VAULT_LIMIT_USD_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_currency_payload(**overrides) -> dict:
    payload = {
        "iso_code": "EUR",
        "display_name": "Euro",
        "minor_unit_digits": 2,
        "currency_class": "MAJOR",
        "standard_denominations": list(TEST_DEFAULTS["EUR_DENOMINATIONS"]),
        "buyback_eligible": True,
    }
    payload.update(overrides)
    return payload


def eur_currency_payload(**overrides) -> dict:
    return create_currency_payload(**overrides)


def chf_currency_payload(**overrides) -> dict:
    payload = {
        "iso_code": "CHF",
        "display_name": "Swiss Franc",
        "minor_unit_digits": 2,
        "currency_class": "MAJOR",
        "standard_denominations": list(TEST_DEFAULTS["CHF_DENOMINATIONS"]),
    }
    payload.update(overrides)
    return payload


def jpy_currency_payload(**overrides) -> dict:
    payload = {
        "iso_code": "JPY",
        "display_name": "Japanese Yen",
        "minor_unit_digits": 0,
        "currency_class": "MAJOR",
        "standard_denominations": [1000, 5000, 10000],
    }
    payload.update(overrides)
    return payload


def restricted_currency_payload(**overrides) -> dict:
    """A RESTRICTED-class profile: PRD 2.10 requires export_limit_minor_units."""
    payload = {
        "iso_code": "MAD",
        "display_name": "Moroccan Dirham",
        "minor_unit_digits": 2,
        "currency_class": "RESTRICTED",
        "standard_denominations": [2000, 5000, 10000],
        "export_limit_minor_units": 20000,
    }
    payload.update(overrides)
    return payload


def exotic_currency_payload(**overrides) -> dict:
    """An EXOTIC-class profile: PRD 2.10 requires export_limit_minor_units null."""
    payload = {
        "iso_code": "VND",
        "display_name": "Vietnamese Dong",
        "minor_unit_digits": 0,
        "currency_class": "EXOTIC",
        "standard_denominations": [50000, 100000, 500000],
    }
    payload.update(overrides)
    return payload


def create_armored_route_payload(**overrides) -> dict:
    payload = {
        "code": "RT-SOUTH-1",
        "carrier_name": "Brinks South",
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "daily_capacity_usd_cents": 100_000_000,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# PRD 3.2 - wholesale rates and rate cards                                     #
# --------------------------------------------------------------------------- #
def create_wholesale_rate_payload(**overrides) -> dict:
    payload = {
        "currency_code": "EUR",
        "mid_rate_micros": TEST_DEFAULTS["EUR_MID_RATE_MICROS"],
        "effective_at": TEST_DEFAULTS["WHOLESALE_EFFECTIVE_AT"],
        "source_code": TEST_DEFAULTS["SOURCE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_rate_card_payload(
    branch_id: str,
    wholesale_rate_id: str,
    expected_branch_version: int,
    **overrides,
) -> dict:
    payload = {
        "branch_id": branch_id,
        "currency_code": "EUR",
        "wholesale_rate_id": wholesale_rate_id,
        "buy_spread_bps": TEST_DEFAULTS["BUY_SPREAD_BPS"],
        "sell_spread_bps": TEST_DEFAULTS["SELL_SPREAD_BPS"],
        "board_display_label": "EUR Euro",
        "disclosure_text_version": 3,
        "effective_from": TEST_DEFAULTS["WHOLESALE_EFFECTIVE_AT"],
        "expected_branch_version": int(expected_branch_version),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# PRD 3.3 - travel corridors and inventory plans                               #
# --------------------------------------------------------------------------- #
def create_travel_corridor_payload(**overrides) -> dict:
    payload = {
        "code": "LHR-ALPS-WINTER",
        "origin_country_code": "GB",
        "destination_country_code": "CH",
        "destination_currency_code": "CHF",
        "season": "WINTER",
        "season_start_date": "2026-06-01T00:00:00Z",
        "season_end_date": "2026-09-01T00:00:00Z",
        "demand_index_bps": 12500,
    }
    payload.update(overrides)
    return payload


def create_inventory_plan_payload(
    branch_id: str,
    travel_corridor_id: str,
    season_days: int = 10,
    target_lines: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    payload = {
        "branch_id": branch_id,
        "travel_corridor_id": travel_corridor_id,
        "season_days": int(season_days),
    }
    if target_lines is not None:
        payload["target_lines"] = target_lines
    payload.update(overrides)
    return payload


def review_plan_payload(decision: str = "APPROVE", review_note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


# --------------------------------------------------------------------------- #
# PRD 3.4 - inventory positions                                                #
# --------------------------------------------------------------------------- #
def create_inventory_position_payload(
    branch_id: str,
    currency_code: str = "EUR",
    opening_denomination_mix: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    payload = {
        "branch_id": branch_id,
        "currency_code": currency_code,
        "opening_denomination_mix": opening_denomination_mix
        if opening_denomination_mix is not None
        else [denom(10000, 20)],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# PRD 3.5 - customers and exchange transactions                                #
# --------------------------------------------------------------------------- #
def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["CUSTOMER_NAME"],
        "nationality_code": TEST_DEFAULTS["NATIONALITY_CODE"],
    }
    payload.update(overrides)
    return payload


def create_exchange_transaction_payload(
    branch_id: str,
    customer_id: str,
    rate_card_id: str,
    currency_code: str = "EUR",
    direction: str = "SELL_FX_TO_CUSTOMER",
    requested_denominations: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    payload = {
        "branch_id": branch_id,
        "customer_id": customer_id,
        "rate_card_id": rate_card_id,
        "currency_code": currency_code,
        "direction": direction,
        "requested_denominations": requested_denominations
        if requested_denominations is not None
        else [denom(10000, 1)],
    }
    payload.update(overrides)
    return payload


def void_payload(void_reason: str = "customer changed mind") -> dict:
    return {"void_reason": void_reason}


def reverse_payload(reversal_reason: str = "customer dispute") -> dict:
    return {"reversal_reason": reversal_reason}


def compliance_decision_payload(decision: str, decision_note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def compliance_hold_payload(action: str, reason: Optional[str] = None) -> dict:
    payload = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return payload


# --------------------------------------------------------------------------- #
# PRD 3.7 - buy-back contracts                                                 #
# --------------------------------------------------------------------------- #
def create_buyback_contract_payload(
    customer_id: str, origin_transaction_id: str, expected_customer_version: int, **overrides
) -> dict:
    payload = {
        "customer_id": customer_id,
        "origin_transaction_id": origin_transaction_id,
        "expected_customer_version": int(expected_customer_version),
    }
    payload.update(overrides)
    return payload


def redeem_payload(returned_denominations: List[dict]) -> dict:
    return {"returned_denominations": returned_denominations}


def cancel_contract_payload(cancellation_reason: str = "customer no longer travelling") -> dict:
    return {"cancellation_reason": cancellation_reason}


# --------------------------------------------------------------------------- #
# PRD 3.8 - note assessments                                                   #
# --------------------------------------------------------------------------- #
def create_note_assessment_payload(
    branch_id: str,
    inventory_position_id: str,
    exchange_transaction_id: str,
    denomination_minor_units: int = 10000,
    note_count: int = 1,
    defect_type: str = "DAMAGED",
    **overrides,
) -> dict:
    payload = {
        "branch_id": branch_id,
        "inventory_position_id": inventory_position_id,
        "exchange_transaction_id": exchange_transaction_id,
        "denomination_minor_units": int(denomination_minor_units),
        "note_count": int(note_count),
        "defect_type": defect_type,
    }
    payload.update(overrides)
    return payload


def assess_payload(outcome: str, assessment_note: Optional[str] = None) -> dict:
    payload = {"outcome": outcome}
    if assessment_note is not None:
        payload["assessment_note"] = assessment_note
    return payload


# --------------------------------------------------------------------------- #
# PRD 3.6 - compliance reports                                                 #
# --------------------------------------------------------------------------- #
def file_report_payload(filing_reference: str = "REG-ACK-0001") -> dict:
    return {"filing_reference": filing_reference}


def amend_report_payload(amendment_reason: Optional[str] = "restated aggregate") -> dict:
    payload = {}
    if amendment_reason is not None:
        payload["amendment_reason"] = amendment_reason
    return payload


# --------------------------------------------------------------------------- #
# PRD 3.9 - cash shipments                                                     #
# --------------------------------------------------------------------------- #
def create_cash_shipment_payload(
    branch_id: str,
    currency_code: str = "EUR",
    direction: str = "REPATRIATION",
    manifest_denominations: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    payload = {
        "branch_id": branch_id,
        "currency_code": currency_code,
        "direction": direction,
        "manifest_denominations": manifest_denominations
        if manifest_denominations is not None
        else [denom(10000, 5)],
    }
    payload.update(overrides)
    return payload


def schedule_shipment_payload(armored_route_id: str, window_start: str, window_end: str) -> dict:
    return {
        "armored_route_id": armored_route_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def arrive_payload(delivered_denominations: List[dict]) -> dict:
    return {"delivered_denominations": delivered_denominations}
