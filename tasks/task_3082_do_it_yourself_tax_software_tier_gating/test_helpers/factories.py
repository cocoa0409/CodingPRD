"""Payload factories — one per creatable resource, input fields only."""
from .constants import FORM_SPECS, TEST_DEFAULTS, TIER_PRICES, TIER_RANKS


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": "filer@example.com",
        "full_name": "Test Filer",
        "filing_status": TEST_DEFAULTS["FILING_STATUS"],
        "agi_cents": TEST_DEFAULTS["AGI_CENTS"],
        "resident_state_code": TEST_DEFAULTS["RESIDENT_STATE"],
    }
    defaults.update(overrides)
    return defaults


def seed_tier_payload(code, **overrides) -> dict:
    defaults = {
        "code": code,
        "price_cents": TIER_PRICES[code]["price_cents"],
        "state_addon_price_cents": TIER_PRICES[code]["state_addon_price_cents"],
        "supported_forms": [],
        "tier_rank": TIER_RANKS[code],
    }
    defaults.update(overrides)
    return defaults


def seed_form_payload(code, **overrides) -> dict:
    spec = FORM_SPECS[code]
    defaults = {
        "code": code,
        "minimum_tier": spec["minimum_tier"],
        "disqualifies_free_file": spec["disqualifies_free_file"],
    }
    if spec["counts_toward_refund"]:
        defaults["counts_toward_refund"] = True
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {"tax_year": TEST_DEFAULTS["TAX_YEAR"]}
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(tax_year, carryforward_items, **overrides) -> dict:
    defaults = {
        "tax_year": tax_year,
        "carryforward_items": carryforward_items,
    }
    defaults.update(overrides)
    return defaults


def carryforward_item(item_type, asset_tag, remaining_amount_cents) -> dict:
    return {
        "item_type": item_type,
        "asset_tag": asset_tag,
        "remaining_amount_cents": remaining_amount_cents,
    }


def add_state_return_payload(state_code, expected_return_version, **overrides) -> dict:
    defaults = {
        "state_code": state_code,
        "expected_return_version": expected_return_version,
    }
    defaults.update(overrides)
    return defaults
