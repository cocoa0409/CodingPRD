"""Payload factories — one per creatable resource, input fields only.

Default timestamps are all at or after the logical-clock default of
2026-09-01T00:00:00Z (PRD §2.4), so every factory is usable against a fresh
server without advancing the clock first. The valuation and third-party
interest factories build the method- and kind-correct shapes from PRD §3.3 /
§3.5; tests that need a deliberately mixed shape mutate the returned dict.
"""

import itertools
from typing import Optional

from .constants import CLOCK_EPOCH, TEST_DEFAULTS

_case_counter = itertools.count(1)
_petitioner_counter = itertools.count(1)


def unique_case_number() -> str:
    """Globally-unique government case number (case_number is unique per PRD
    §3.1), safe for tests that open several cases."""
    return f"26-MJ-{next(_case_counter):04d}"


def unique_petitioner_ref() -> str:
    return f"cl-{next(_petitioner_counter):04d}"


# ─── SeizureCase (PRD §3.1) ──────────────────────────────────────────────────

def create_case_payload(**overrides) -> dict:
    defaults = {
        "case_number": unique_case_number(),
        "judicial_district": TEST_DEFAULTS["JUDICIAL_DISTRICT"],
        "forfeiture_type": "CIVIL",
        "lead_agency_code": TEST_DEFAULTS["LEAD_AGENCY_CODE"],
    }
    defaults.update(overrides)
    return defaults


# ─── Asset (PRD §3.2) ────────────────────────────────────────────────────────

def create_asset_payload(seizure_case_id: str, **overrides) -> dict:
    defaults = {
        "seizure_case_id": seizure_case_id,
        "asset_type": "VEHICLE",
        "description": "seized vehicle",
        "seized_on": CLOCK_EPOCH,
        "seizure_condition_grade": "EXCELLENT",
    }
    defaults.update(overrides)
    return defaults


# ─── CustodyTransfer (PRD §3.2) ──────────────────────────────────────────────

def create_custody_transfer_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "from_location_ref": "impound-1",
        "to_location_ref": "warehouse-1",
        "to_location_kind": "STORAGE",
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


# ─── Valuation (PRD §3.3) ────────────────────────────────────────────────────

def create_valuation_payload(
    asset_id: str, expected_asset_version: int, method: str = "CERTIFIED_APPRAISAL",
    **overrides,
) -> dict:
    """Method-consistent payload: INCOME_APPROACH carries exactly three annual
    net revenues and no raw figure; every other method carries raw_value_cents
    plus assessed_condition_grade and no revenue array."""
    defaults: dict = {
        "asset_id": asset_id,
        "method": method,
        "expected_asset_version": expected_asset_version,
    }
    if method == "INCOME_APPROACH":
        defaults["annual_net_revenues_cents"] = [100_000, 120_000, 140_000]
    else:
        defaults["raw_value_cents"] = 1_000_000
        defaults["assessed_condition_grade"] = "EXCELLENT"
    defaults.update(overrides)
    return defaults


# ─── ExpenseEntry (PRD §3.4) ─────────────────────────────────────────────────

def create_expense_entry_payload(asset_id: str, **overrides) -> dict:
    """Manual ledger posting. ``incurred_on`` is omitted by default so the
    server applies its logical-clock default (PRD §3.4); pass a value to pin it."""
    defaults: dict = {
        "asset_id": asset_id,
        "entry_kind": "COST",
        "expense_type": "STORAGE",
        "amount_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


# ─── InterlocutorySaleRequest (PRD §3.4) ─────────────────────────────────────

def create_isr_payload(
    asset_id: str, expected_asset_version: int, **overrides
) -> dict:
    defaults: dict = {
        "asset_id": asset_id,
        "justification": "holding costs threaten to consume the asset's value",
        "expected_asset_version": expected_asset_version,
    }
    defaults.update(overrides)
    return defaults


# ─── ThirdPartyInterest (PRD §3.5) ───────────────────────────────────────────

def create_lien_payload(
    asset_id: str,
    petitioner_ref: str,
    kind: str = "LIEN_MORTGAGE",
    **overrides,
) -> dict:
    """LIEN_* filing: lienholder_name, amount_cents and priority_position are
    all populated (1 is paid first)."""
    defaults: dict = {
        "asset_id": asset_id,
        "kind": kind,
        "petitioner_ref": petitioner_ref,
        "lienholder_name": "Meridian Bank",
        "amount_cents": 100_000,
        "priority_position": 1,
    }
    defaults.update(overrides)
    return defaults


def create_innocent_owner_payload(
    asset_id: str, petitioner_ref: str, **overrides
) -> dict:
    """INNOCENT_OWNER filing: the three lien fields are carried as null."""
    defaults: dict = {
        "asset_id": asset_id,
        "kind": "INNOCENT_OWNER",
        "petitioner_ref": petitioner_ref,
        "lienholder_name": None,
        "amount_cents": None,
        "priority_position": None,
    }
    defaults.update(overrides)
    return defaults


# ─── SaleEvent (PRD §3.6) ────────────────────────────────────────────────────

def create_sale_event_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "sale_method": "PUBLIC_AUCTION",
        "auctioneer_ref": TEST_DEFAULTS["AUCTIONEER_REF"],
        "slot_start": TEST_DEFAULTS["SLOT_START"],
        "slot_end": TEST_DEFAULTS["SLOT_END"],
        "reserve_price_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


# ─── Distribution (PRD §3.7) ─────────────────────────────────────────────────

def create_distribution_payload(seizure_case_id: str, **overrides) -> dict:
    """Manually created distributions are EQUITABLE_SHARE and must carry a
    usage_restriction (PRD §3.7)."""
    defaults = {
        "seizure_case_id": seizure_case_id,
        "payee_ref": TEST_DEFAULTS["PAYEE_REF"],
        "amount_cents": 50_000,
        "usage_restriction": "EQUIPMENT",
    }
    defaults.update(overrides)
    return defaults


__all__ = [
    "unique_case_number",
    "unique_petitioner_ref",
    "create_case_payload",
    "create_asset_payload",
    "create_custody_transfer_payload",
    "create_valuation_payload",
    "create_expense_entry_payload",
    "create_isr_payload",
    "create_lien_payload",
    "create_innocent_owner_payload",
    "create_sale_event_payload",
    "create_distribution_payload",
]
