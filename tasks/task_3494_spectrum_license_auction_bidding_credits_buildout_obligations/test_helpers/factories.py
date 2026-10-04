"""Payload factories — one per creatable entity, input fields only.

Computed/system fields (credit_pct, attributable_revenue_cents,
eligibility_units, units_snapshot, prices, aggregate_demand, net prices,
unjust_enrichment_cents, shares arrays, ...) are never sent; PRD says
client-supplied computed values are ignored everywhere.

Ownership-interest defaults always sum to exactly 100 so factories are
PRD-legal out of the box; override `ownership_interests` to probe the
sum-to-100 validation.
"""
from .constants import (
    DEFAULT_APPLICATION_DEADLINE_ISO,
    UPFRONT_CENTS_PER_ELIGIBILITY_UNIT,
)

# Canonical product parameters (area populations and block shapes used across
# the fixture chains; opening price = mhz_size * population * coefficient).
CANONICAL_AREAS = {
    "PEA001": {"area_code": "PEA001", "name": "Metro X", "population": 1_000_000},
    "PEA002": {"area_code": "PEA002", "name": "Rural Y", "population": 500_000},
    "PEA003": {"area_code": "PEA003", "name": "Plains Z", "population": 2_000_000},
}
CANONICAL_BLOCKS = {
    "CATEGORY_A": {
        "category": "CATEGORY_A", "mhz_size": 10, "supply_per_area": 2,
        "price_per_mhz_pop_cents": 50,
    },
    "CATEGORY_B": {
        "category": "CATEGORY_B", "mhz_size": 20, "supply_per_area": 1,
        "price_per_mhz_pop_cents": 30,
    },
    "CATEGORY_C": {
        "category": "CATEGORY_C", "mhz_size": 5, "supply_per_area": 4,
        "price_per_mhz_pop_cents": 100,
    },
    "CATEGORY_D": {
        "category": "CATEGORY_D", "mhz_size": 5, "supply_per_area": 4,
        "price_per_mhz_pop_cents": 100,
    },
}

# Canonical upfront amounts (all exact multiples of 2500 except where a floor
# remainder is the point of the test):
#   25,000,000,000 -> 10,000,000 units   31,250,000,000 -> 12,500,000 units
#   50,000,000,000 -> 20,000,000 units  100,000,000,000 -> 40,000,000 units
#   200,000,000,000 -> 80,000,000 units           2,500 -> 1 unit
UPFRONT_10M_UNITS = 25_000_000_000
UPFRONT_12_5M_UNITS = 31_250_000_000
UPFRONT_20M_UNITS = 50_000_000_000
UPFRONT_40M_UNITS = 100_000_000_000
UPFRONT_80M_UNITS = 200_000_000_000
UPFRONT_ONE_UNIT = UPFRONT_CENTS_PER_ELIGIBILITY_UNIT  # 2,500 cents


def sole_owner_interests(holder_name="Sole Owner", holder_annual_revenue_cents=0):
    return [
        {
            "holder_name": holder_name,
            "stake_pct": 100,
            "holder_annual_revenue_cents": holder_annual_revenue_cents,
        }
    ]


def create_band_plan_payload(**overrides) -> dict:
    defaults = {
        "band_name": "3.5 GHz",
        "frequency_start_mhz": 3550,
        "frequency_end_mhz": 3700,
        "technical_rules": "50W EIRP max",
    }
    defaults.update(overrides)
    return defaults


def create_license_area_payload(band_plan_id: str, **overrides) -> dict:
    defaults = {
        "band_plan_id": band_plan_id,
        "area_code": "PEA001",
        "name": "Metro X",
        "population": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_license_block_payload(band_plan_id: str, **overrides) -> dict:
    defaults = {
        "band_plan_id": band_plan_id,
        "category": "CATEGORY_A",
        "mhz_size": 10,
        "supply_per_area": 2,
        "price_per_mhz_pop_cents": 50,
    }
    defaults.update(overrides)
    return defaults


def create_auction_payload(band_plan_id: str, **overrides) -> dict:
    defaults = {
        "band_plan_id": band_plan_id,
        "name": "Auction 3494",
        "application_deadline": DEFAULT_APPLICATION_DEADLINE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(auction_id: str, **overrides) -> dict:
    """Registration payload. Defaults: no credit claims, zero revenue, zero
    service population, single 100% owner (stakes sum to exactly 100)."""
    defaults = {
        "auction_id": auction_id,
        "legal_name": "Test Bidder LLC",
        "claims_small_business": False,
        "claims_rural_credit": False,
        "own_annual_revenue_cents": 0,
        "service_population": 0,
        "ownership_interests": sole_owner_interests(),
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_patch_payload(expected_applicant_version: int, **overrides) -> dict:
    """OCC-guarded disclosure update; expected_applicant_version is mandatory."""
    defaults = {"expected_applicant_version": expected_applicant_version}
    defaults.update(overrides)
    return defaults


def create_resubmit_payload(expected_applicant_version: int, **overrides) -> dict:
    defaults = {"expected_applicant_version": expected_applicant_version}
    defaults.update(overrides)
    return defaults


def create_bid_payload(area_code: str, category: str, quantity: int, **overrides) -> dict:
    defaults = {"area_code": area_code, "category": category, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_assignment_bid_payload(
    area_code: str, category: str, amount_cents: int, **overrides
) -> dict:
    defaults = {"area_code": area_code, "category": category, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_settlement_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_file_notice_payload(
    covered_population: int, expected_milestone_version: int, **overrides
) -> dict:
    """OCC-guarded coverage filing; expected_milestone_version is mandatory."""
    defaults = {
        "covered_population": covered_population,
        "expected_milestone_version": expected_milestone_version,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_application_payload(
    transferee_applicant_id: str, transfer_type: str = "FULL_ASSIGNMENT", **overrides
) -> dict:
    """LEASE additionally requires lease_start and lease_end (end > start)."""
    defaults = {
        "transfer_type": transfer_type,
        "transferee_applicant_id": transferee_applicant_id,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_review_payload(action: str, **overrides) -> dict:
    """APPROVE with unjust_enrichment_cents > 0 additionally needs
    confirm_unjust_enrichment_repayment=True."""
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_incumbent_payload(band_plan_id: str, area_id: str, **overrides) -> dict:
    defaults = {
        "band_plan_id": band_plan_id,
        "area_id": area_id,
        "callsign": "KNEW100",
        "relocation_cost_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_incumbent_transition_payload(
    action: str,
    transition_window_start: str = None,
    transition_window_end: str = None,
    **overrides,
) -> dict:
    """BEGIN_RELOCATION additionally carries the window; end must be > start."""
    defaults = {"action": action}
    if transition_window_start is not None:
        defaults["transition_window_start"] = transition_window_start
    if transition_window_end is not None:
        defaults["transition_window_end"] = transition_window_end
    defaults.update(overrides)
    return defaults
