"""Payload factories -- one per entity, input fields only.

Defaults follow the PRD's own examples: a US citizen lawfully resident outside
the US clears the residence rule without tripping the US/US jurisdiction
override, half-open priced offerings use whole-cent economics, and the custody
facility used throughout is a designated freeport.
"""
from .constants import TEST_DEFAULTS, DEFAULT_CUSTODIAN


def create_artist_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Hollis Vandermeer",
        "attribution_status": "CONFIRMED",
        "nationality_country_code": "US",
        "birth_year": 1948,
    }
    payload.update(overrides)
    return payload


def create_investor_payload(**overrides) -> dict:
    payload = {
        "email": "nadia@x.com",
        "legal_name": "Nadia Okonjo",
        "password": "p",
        "citizenship_country_code": TEST_DEFAULTS["DEFAULT_CITIZENSHIP_COUNTRY"],
        "residency_country_code": TEST_DEFAULTS["DEFAULT_RESIDENCY_COUNTRY"],
        "birth_date": TEST_DEFAULTS["INVESTOR_BIRTH_DATE"],
        "annual_income_cents": TEST_DEFAULTS["INVESTOR_INCOME_CENTS"],
        "net_worth_cents": TEST_DEFAULTS["INVESTOR_NET_WORTH_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_artwork_payload(artist_id: str, **overrides) -> dict:
    payload = {
        "title": "Untitled (Meridian Field)",
        "artist_id": artist_id,
        "creation_year": 1971,
        "medium": "PAINTING",
        "acquisition_cost_cents": TEST_DEFAULTS["ACQUISITION_COST_CENTS"],
        "reserve_price_cents": TEST_DEFAULTS["RESERVE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_asset_report_payload(**overrides) -> dict:
    payload = {
        "report_type": "AUTHENTICATION",
        "outcome": "VERIFIED",
        "firm_name": "Vandermeer Catalogue Raisonne Committee",
    }
    payload.update(overrides)
    return payload


def create_appraisal_payload(expected_artwork_version: int, **overrides) -> dict:
    payload = {
        "appraised_value_cents": TEST_DEFAULTS["APPRAISED_VALUE_CENTS"],
        "appraiser_firm": "Ashgrove Fine Art Appraisals",
        "appraisal_method": "AUCTION_COMPARABLE",
        "expected_artwork_version": expected_artwork_version,
    }
    payload.update(overrides)
    return payload


def create_offering_payload(**overrides) -> dict:
    """Offering economics. `artwork_id` is carried by the path, not the body."""
    payload = {
        "total_shares": TEST_DEFAULTS["TOTAL_SHARES"],
        "price_per_share_cents": TEST_DEFAULTS["PRICE_PER_SHARE_CENTS"],
        "exemption_type": TEST_DEFAULTS["EXEMPTION_TYPE"],
        "registration_cap_pct": TEST_DEFAULTS["REGISTRATION_CAP_PCT"],
        "liquidity_ratio_bps": TEST_DEFAULTS["LIQUIDITY_RATIO_BPS"],
        "hold_period_days": TEST_DEFAULTS["HOLD_PERIOD_DAYS"],
        "management_fee_bps": TEST_DEFAULTS["MANAGEMENT_FEE_BPS"],
        "profit_participation_bps": TEST_DEFAULTS["PROFIT_PARTICIPATION_BPS"],
        "cost_pass_through_bps": TEST_DEFAULTS["COST_PASS_THROUGH_BPS"],
        "preferred_return_bps": TEST_DEFAULTS["PREFERRED_RETURN_BPS"],
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(offering_id: str, investor_id: str, **overrides) -> dict:
    payload = {
        "offering_id": offering_id,
        "investor_id": investor_id,
        "requested_shares": 2000,
    }
    payload.update(overrides)
    return payload


def create_custody_record_payload(**overrides) -> dict:
    payload = dict(DEFAULT_CUSTODIAN)
    payload.update(overrides)
    return payload


def create_insurance_policy_payload(**overrides) -> dict:
    payload = {
        "carrier_name": "Alteza Specialty Insurance",
        "coverage_cents": TEST_DEFAULTS["COVERAGE_CENTS"],
        "annual_premium_cents": TEST_DEFAULTS["ANNUAL_PREMIUM_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_cost_lot_payload(**overrides) -> dict:
    payload = {
        "lot_type": "STORAGE",
        "cost_amount_cents": 6_000_000,
        "incurred_on": "2027-01-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_holding_decision_payload(**overrides) -> dict:
    payload = {"decision_type": "SELL", "proposed_gross_cents": 120_000_000}
    payload.update(overrides)
    return payload


def create_transfer_order_payload(offering_id: str, seller_id: str, **overrides) -> dict:
    payload = {
        "offering_id": offering_id,
        "seller_id": seller_id,
        "shares": 4000,
        "limit_price_cents": 12_000_000,
    }
    payload.update(overrides)
    return payload


def create_platform_account_payload(**overrides) -> dict:
    payload = {"account_name": "Segregated Investor Funds"}
    payload.update(overrides)
    return payload


def create_offering_report_payload(**overrides) -> dict:
    payload = {
        "report_kind": "QUARTERLY",
        "as_of_date": "2026-09-20T00:00:00Z",
        "value_per_share_cents": 2200,
    }
    payload.update(overrides)
    return payload


def create_fee_accrual_payload(**overrides) -> dict:
    payload = {"accrual_type": "MANAGEMENT"}
    payload.update(overrides)
    return payload