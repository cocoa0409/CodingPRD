"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_title_isbn_counter = [0]


def _next_isbn() -> str:
    _title_isbn_counter[0] += 1
    return f"978{_title_isbn_counter[0]:010d}"


def create_consortium_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["CONSORTIUM_NAME"],
        "cpc_discount_pct": TEST_DEFAULTS["CPC_DISCOUNT_PCT"],
        "host_share_floor_pct": TEST_DEFAULTS["HOST_SHARE_FLOOR_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_library_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["LIBRARY_NAME"],
        "residency_region_codes": list(TEST_DEFAULTS["RESIDENCY_REGION_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_patron_payload(**overrides) -> dict:
    defaults = {
        "external_card_number": "P-0",
        "full_name": "Patron Zero",
        "postal_code": "94301",
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(**overrides) -> dict:
    defaults = {
        "isbn": _next_isbn(),
        "name": "Title T",
        "author": "Author A",
        "price_ocou_cents": TEST_DEFAULTS["PRICE_OCOU_CENTS"],
        "metered_time_price_cents": TEST_DEFAULTS["METERED_TIME_PRICE_CENTS"],
        "metered_time_days": TEST_DEFAULTS["METERED_TIME_DAYS"],
        "metered_circ_price_cents": TEST_DEFAULTS["METERED_CIRC_PRICE_CENTS"],
        "metered_circ_count": TEST_DEFAULTS["METERED_CIRC_COUNT"],
        "cpc_price_per_circ_cents": TEST_DEFAULTS["CPC_PRICE_PER_CIRC_CENTS"],
        "simultaneous_use_price_cents": TEST_DEFAULTS["SIMULTANEOUS_USE_PRICE_CENTS"],
        "simultaneous_use_days": TEST_DEFAULTS["SIMULTANEOUS_USE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "model": "OCOU",
        "copies": 1,
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_checkout_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
