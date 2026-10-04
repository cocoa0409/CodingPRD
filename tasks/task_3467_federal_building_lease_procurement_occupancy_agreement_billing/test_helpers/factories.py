"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
import itertools

from .constants import (
    CANONICAL_BASE_YEAR_TAX, CANONICAL_COMMENCEMENT_DATE,
    CANONICAL_FREE_RENT_MONTHS, CANONICAL_OPERATING_RATE,
    CANONICAL_SHELL_RATE, CANONICAL_TERM_YEARS,
    CANONICAL_TI_ALLOWANCE_PER_SF, CANONICAL_TI_BUILDOUT_COST,
    OWNED_ASSIGNED_SF, OWNED_OA_END, OWNED_OA_START,
    OWNED_OPERATING_RATE, OWNED_SHELL_EQUIVALENT_RATE,
)

_bureau_seq = itertools.count(1)


def next_bureau_code(prefix="BUR"):
    """Unique bureau codes so parallel tests never collide on uniqueness."""
    return f"{prefix}-{next(_bureau_seq):04d}"


def create_agency_payload(**overrides) -> dict:
    defaults = {"bureau_code": next_bureau_code(), "name": "Forest Service"}
    defaults.update(overrides)
    return defaults


def create_building_payload(**overrides) -> dict:
    defaults = {
        "building_name": "Metro Tower",
        "address": "100 Federal Plaza",
        "region_code": "R9",
        "ownership_type": "LEASED_STOCK",
        "security_capability": 5,
        "total_sf": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_owned_building_payload(**overrides) -> dict:
    defaults = {
        "building_name": "Legacy Federal",
        "address": "1 Constitution Ave",
        "region_code": "R11",
        "ownership_type": "FEDERALLY_OWNED",
        "security_capability": 4,
        "total_sf": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_requirement_payload(agency_id, **overrides) -> dict:
    """The canonical programming inputs: 400 base headcount growing 2% to 2031,
    150 sf/person plus a 2,000 sf SCIF, 53 ISC points (20+15+10+8)."""
    defaults = {
        "agency_id": agency_id,
        "title": "HQ Consolidation",
        "base_headcount": 400,
        "annual_growth_pct": 0.02,
        "target_occupancy_year": 2031,
        "sf_per_person": 150,
        "special_needs": [{"need_type": "SCIF", "sf": 2000}],
        "region_code": "R9",
        "mission_points": 20,
        "population_points": 15,
        "size_points": 10,
        "criticality_points": 8,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(building_id, **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "lessor_name": "Metro REIT LLC",
        "shell_rate_per_sf_yr_cents": CANONICAL_SHELL_RATE,
        "operating_rate_per_sf_yr_cents": CANONICAL_OPERATING_RATE,
        "base_year_tax_per_sf_yr_cents": CANONICAL_BASE_YEAR_TAX,
        "escalation_method": "BASE_YEAR_STOP",
        "ti_allowance_per_sf_cents": CANONICAL_TI_ALLOWANCE_PER_SF,
        "free_rent_months": CANONICAL_FREE_RENT_MONTHS,
        "term_years": CANONICAL_TERM_YEARS,
        "valid_until": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def commence_lease_payload(**overrides) -> dict:
    defaults = {
        "commencement_date": CANONICAL_COMMENCEMENT_DATE,
        "ti_buildout_cost_cents": CANONICAL_TI_BUILDOUT_COST,
        "ti_amort_method": "ANNUITY",
    }
    defaults.update(overrides)
    return defaults


def create_leased_oa_payload(lease_id, agency_id, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "agency_id": agency_id,
        "assigned_sf": 68300,
        "start_date": "2027-01-01",
        "end_date": "2036-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_owned_oa_payload(building_id, agency_id, **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "agency_id": agency_id,
        "assigned_sf": OWNED_ASSIGNED_SF,
        "start_date": OWNED_OA_START,
        "end_date": OWNED_OA_END,
        "shell_equivalent_rate_per_sf_yr_cents": OWNED_SHELL_EQUIVALENT_RATE,
        "operating_rate_per_sf_yr_cents": OWNED_OPERATING_RATE,
    }
    defaults.update(overrides)
    return defaults


def create_tax_statement_payload(tax_year, actual_tax_per_sf_yr_cents, **overrides) -> dict:
    defaults = {
        "tax_year": tax_year,
        "actual_tax_per_sf_yr_cents": actual_tax_per_sf_yr_cents,
    }
    defaults.update(overrides)
    return defaults


def select_option_payload(option="SUCCEEDING_LEASE", **overrides) -> dict:
    """Full cost-parameter set required at select-option (PRD §3.9)."""
    defaults = {
        "option": option,
        "succeeding_shell_rate": 3200,
        "succeeding_operating_rate": 950,
        "succeeding_term_years": 10,
        "relocation_move_cost_cents": 50000000,
        "relocation_downtime_cost_cents": 0,
        "market_shell_rate": 3300,
        "market_operating_rate": 900,
        "construction_cost_cents": 5000000000,
        "construction_operating_rate": 700,
    }
    defaults.update(overrides)
    return defaults


def create_alteration_payload(**overrides) -> dict:
    defaults = {
        "title": "Kitchenette",
        "description": "Break room upgrade",
        "scope_sf": 400,
    }
    defaults.update(overrides)
    return defaults


def estimate_alteration_payload(**overrides) -> dict:
    defaults = {
        "estimated_cost_cents": 800000,
        "work_start_date": "2028-03-01",
        "work_end_date": "2028-03-31",
    }
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(reported_oa_id, **overrides) -> dict:
    defaults = {
        "reported_oa_id": reported_oa_id,
        "category": "MAINTENANCE",
        "severity": "CRITICAL",
        "description": "Elevator bank outage",
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(**overrides) -> dict:
    defaults = {
        "method": "SPACE_BASED",
        "measured_headcount": 100,
        "utilized_sf": 12000,
        "measured_at": "2027-03-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def pay_bill_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
