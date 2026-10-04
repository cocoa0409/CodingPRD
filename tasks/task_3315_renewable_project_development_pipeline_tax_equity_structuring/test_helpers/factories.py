"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROJECT_NAME": "Test Farm",
    "TECHNOLOGY": "WIND",
    "TARGET_CAPACITY_MW": 100,
    "RESOURCE_CLASS": "A",
    "PARCEL_ID": "PCL-1",
    "INSTRUMENT_TYPE": "LAND_OPTION",
    "START_DATE": "2026-09-01T00:00:00Z",
    "END_DATE": "2028-09-01T00:00:00Z",
    "EXERCISE_PRICE_USD": 50000.00,
    "CLUSTER_ID": "CL-DEFAULT",
    "REQUESTED_CAPACITY_MW": 100,
    "PHASE": "FEASIBILITY",
    "WINDOW_START": "2026-10-01T00:00:00Z",
    "WINDOW_END": "2026-10-31T00:00:00Z",
    "BUYER_TYPE": "UTILITY",
    "BASE_PRICE_USD_MWH": 45.00,
    "ESCALATOR_PCT": 2.0,
    "TERM_YEARS": 20,
    "DELIVERY_START_DATE": "2028-01-01T00:00:00Z",
    "EQUIPMENT_TYPE": "TURBINE",
    "SUPPLIER_NAME": "Vestas",
    "TOTAL_CONTRACT_USD": 5000000.00,
    "ORDER_AMOUNT_USD": 2000000.00,
    "SAFE_HARBOR_METHOD": "FIVE_PERCENT_COST",
    "ELIGIBLE_COST_BASIS_USD": 2000000.00,
    "MILESTONE_TYPE": "FOUNDATION",
    "PLANNED_DATE": "2027-03-01T00:00:00Z",
    "WORK_DATE": "2027-03-01T00:00:00Z",
    "EVIDENCE_URI": "s3://ev/default",
    "INVESTOR_NAME": "Tax Equity Investors LLC",
    "COMMITMENT_USD": 1000000.00,
    "TARGET_IRR_PCT": 8.0,
    "INTEREST_RATE_PCT": 5.0,
    "PROJECTED_CFADS_USD": 800000.00,
    "PERIOD_END_DATE": "2027-03-31T00:00:00Z",
}


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "technology": DEFAULTS["TECHNOLOGY"],
        "target_capacity_mw": DEFAULTS["TARGET_CAPACITY_MW"],
        "resource_class": DEFAULTS["RESOURCE_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_site_control_payload(**overrides) -> dict:
    defaults = {
        "parcel_id": DEFAULTS["PARCEL_ID"],
        "instrument_type": DEFAULTS["INSTRUMENT_TYPE"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
        "exercise_price_usd": DEFAULTS["EXERCISE_PRICE_USD"],
    }
    defaults.update(overrides)
    return defaults


def create_interconnection_request_payload(**overrides) -> dict:
    defaults = {
        "cluster_id": DEFAULTS["CLUSTER_ID"],
        "requested_capacity_mw": DEFAULTS["REQUESTED_CAPACITY_MW"],
    }
    defaults.update(overrides)
    return defaults


def create_study_payload(**overrides) -> dict:
    defaults = {
        "phase": DEFAULTS["PHASE"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_offtake_payload(expected_project_version, **overrides) -> dict:
    defaults = {
        "buyer_type": DEFAULTS["BUYER_TYPE"],
        "base_price_usd_mwh": DEFAULTS["BASE_PRICE_USD_MWH"],
        "escalator_pct": DEFAULTS["ESCALATOR_PCT"],
        "term_years": DEFAULTS["TERM_YEARS"],
        "delivery_start_date": DEFAULTS["DELIVERY_START_DATE"],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_supply_agreement_payload(**overrides) -> dict:
    defaults = {
        "equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
        "supplier_name": DEFAULTS["SUPPLIER_NAME"],
        "total_contract_usd": DEFAULTS["TOTAL_CONTRACT_USD"],
    }
    defaults.update(overrides)
    return defaults


def create_procurement_order_payload(**overrides) -> dict:
    defaults = {
        "order_amount_usd": DEFAULTS["ORDER_AMOUNT_USD"],
        "safe_harbor_method": DEFAULTS["SAFE_HARBOR_METHOD"],
        "eligible_cost_basis_usd": DEFAULTS["ELIGIBLE_COST_BASIS_USD"],
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    defaults = {
        "milestone_type": DEFAULTS["MILESTONE_TYPE"],
        "sequence_no": 1,
        "planned_date": DEFAULTS["PLANNED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_uri": DEFAULTS["EVIDENCE_URI"],
        "work_date": DEFAULTS["WORK_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_partnership_payload(**overrides) -> dict:
    defaults = {
        "investor_name": DEFAULTS["INVESTOR_NAME"],
        "commitment_usd": DEFAULTS["COMMITMENT_USD"],
        "target_irr_pct": DEFAULTS["TARGET_IRR_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(**overrides) -> dict:
    defaults = {
        "amount_usd": DEFAULTS["COMMITMENT_USD"],
        "period_end_date": DEFAULTS["PERIOD_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(**overrides) -> dict:
    defaults = {
        "amount_usd": 100000.00,
        "period_end_date": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_debt_facility_payload(**overrides) -> dict:
    defaults = {
        "commitment_usd": 10000000.00,
        "interest_rate_pct": DEFAULTS["INTEREST_RATE_PCT"],
        "projected_cfads_usd": DEFAULTS["PROJECTED_CFADS_USD"],
    }
    defaults.update(overrides)
    return defaults
