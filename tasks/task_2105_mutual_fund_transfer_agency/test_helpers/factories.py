"""Payload factories — one per resource, carrying only client-supplied fields."""

import itertools

from .constants import (
    DEFAULT_BREAKPOINT_TIERS,
    MONDAY,
    TEST_DEFAULTS,
)

_tax_id_counter = itertools.count(1)


def unique_tax_id() -> str:
    """A distinct taxpayer identification number per call within a test."""
    n = next(_tax_id_counter)
    return f"{100 + n % 800:03d}-{n % 100:02d}-{1000 + n % 9000:04d}"


def create_fund_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["FUND_NAME"],
        "fund_family_code": TEST_DEFAULTS["FUND_FAMILY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_share_class_payload(fund_id: str, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "class_code": "A",
        "seed_nav_per_share": TEST_DEFAULTS["SEED_NAV"],
        "breakpoint_tiers": list(DEFAULT_BREAKPOINT_TIERS),
    }
    defaults.update(overrides)
    return defaults


def create_shareholder_account_payload(**overrides) -> dict:
    defaults = {
        "registration_type": "INDIVIDUAL",
        "account_channel": "DIRECT",
        "state_code": "CA",
        "tax_id": unique_tax_id(),
        "primary_owner_name": "Test Shareholder",
    }
    defaults.update(overrides)
    return defaults


def create_blue_sky_registration_payload(share_class_id: str, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "state_code": "CA",
        "registered_amount": TEST_DEFAULTS["REGISTERED_AMOUNT"],
        "effective_date": TEST_DEFAULTS["WINDOW_EFFECTIVE_DATE"],
        "expiration_date": TEST_DEFAULTS["WINDOW_EXPIRATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_nav_record_payload(share_class_id: str, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "valuation_date": MONDAY,
        "total_net_assets": 0.00,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_payload(account_id: str, share_class_id: str,
                            gross_amount: float, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "share_class_id": share_class_id,
        "trade_type": "PURCHASE",
        "gross_amount": gross_amount,
    }
    defaults.update(overrides)
    return defaults


def create_redemption_payload(account_id: str, share_class_id: str,
                              shares_requested: float, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "share_class_id": share_class_id,
        "trade_type": "REDEMPTION",
        "shares_requested": shares_requested,
    }
    defaults.update(overrides)
    return defaults


def create_exchange_payload(account_id: str, share_class_id: str,
                            shares_requested: float,
                            exchange_target_share_class_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "share_class_id": share_class_id,
        "trade_type": "EXCHANGE",
        "shares_requested": shares_requested,
        "exchange_target_share_class_id": exchange_target_share_class_id,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(share_class_id: str, **overrides) -> dict:
    defaults = {
        "share_class_id": share_class_id,
        "distribution_type": "ORDINARY_INCOME",
        "rate_per_share": 0.1234,
        "record_date": "2026-08-04",
        "ex_date": "2026-08-04",
        "pay_date": "2026-08-05",
    }
    defaults.update(overrides)
    return defaults


def create_systematic_plan_payload(account_id: str, source_share_class_id: str,
                                   expected_account_version: int, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "source_share_class_id": source_share_class_id,
        "plan_type": "SYSTEMATIC_INVESTMENT",
        "amount": 500.00,
        "frequency": "MONTHLY",
        "next_run_date": "2026-09-01",
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_error_case_payload(nav_record_id: str,
                                      corrected_nav_per_share: float,
                                      expected_nav_record_version: int,
                                      **overrides) -> dict:
    defaults = {
        "nav_record_id": nav_record_id,
        "corrected_nav_per_share": corrected_nav_per_share,
        "error_reason": "Security priced with a stale quote",
        "expected_nav_record_version": expected_nav_record_version,
    }
    defaults.update(overrides)
    return defaults


def create_omnibus_reconciliation_payload(account_id: str, as_of_date: str,
                                          dealer_reported_purchase_amount: float,
                                          dealer_reported_redemption_amount: float,
                                          dealer_reported_net_shares: float,
                                          **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "as_of_date": as_of_date,
        "dealer_reported_purchase_amount": dealer_reported_purchase_amount,
        "dealer_reported_redemption_amount": dealer_reported_redemption_amount,
        "dealer_reported_net_shares": dealer_reported_net_shares,
    }
    defaults.update(overrides)
    return defaults
