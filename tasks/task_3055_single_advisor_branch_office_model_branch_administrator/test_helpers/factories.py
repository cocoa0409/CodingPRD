"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_advisor_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Advisor {n}",
        "email": f"advisor{n}@example.com",
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_territory_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "community_name": f"Community {n}",
        "household_capacity": TEST_DEFAULTS["HOUSEHOLD_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_branch_payload(territory_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "community_name": f"Branch Community {n}",
        "site_address": f"{n} Main St",
        "territory_id": territory_id,
    }
    defaults.update(overrides)
    return defaults


def create_administrator_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Administrator {n}",
        "email": f"boa{n}@example.com",
        "monthly_salary_cents": TEST_DEFAULTS["MONTHLY_SALARY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_production_payload(advisor_id, gross_commission_cents=200, posted_at=None, **overrides) -> dict:
    defaults = {
        "advisor_id": advisor_id,
        "gross_commission_cents": gross_commission_cents,
        "payout_rate": 1.0,
        "posted_at": posted_at or "2026-01-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_financial_period_payload(branch_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(branch_id, amount_cents, charge_type="LEASE_RENT", **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "charge_type": charge_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_goodwill_transfer_payload(branch_id, retiring_advisor_id, successor_advisor_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "retiring_advisor_id": retiring_advisor_id,
        "successor_advisor_id": successor_advisor_id,
        "valuation_mode": "INTERNAL_SUCCESSION",
        "escrow_deposit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_shelf_entry_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "product_code": f"MF-{n}",
        "asset_class": "MUTUAL_FUND",
        "complexity_level": "PLAIN",
    }
    defaults.update(overrides)
    return defaults


def create_solicitation_payload(advisor_id, product_code, **overrides) -> dict:
    n = _seq()
    defaults = {
        "advisor_id": advisor_id,
        "product_code": product_code,
        "client_household_id": f"HH-{n}",
    }
    defaults.update(overrides)
    return defaults
