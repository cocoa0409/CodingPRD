"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROGRAM_NAME": "FY27 Rural Rollout",
    "FISCAL_YEAR": 2027,
    "BUDGET_CENTS": 2000000000,
    "TA_NAME": "Trade Area A",
    "TA_DRIVE_TIME": 20,
    "TA_HOUSEHOLDS": 1000,
    "TA_INCOME_CENTS": 4500000,
    "TA_GAP_PCT": 20,
    "STORE_NAME": "Store S",
    "DEVELOPER_NAME": "DevCo",
    "DC_NAME": "DC-D",
    "DC_CAPACITY": 2,
    "COMMITTED_DELIVERY_DATE": "2026-11-01T00:00:00Z",
    "BASE_PRICE_CENTS": 24000000,
    "EARNEST_MONEY_CENTS": 2400000,
    "STEM_MILES": 90,
    "DELIVERIES_PER_WEEK": 1,
    "OPENING_DATE": "2026-12-05T00:00:00Z",
}


def create_rollout_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "new_build_capital_budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_area_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TA_NAME"],
        "drive_time_minutes": DEFAULTS["TA_DRIVE_TIME"],
        "household_count": DEFAULTS["TA_HOUSEHOLDS"],
        "median_household_income_cents": DEFAULTS["TA_INCOME_CENTS"],
        "grocery_gap_pct": DEFAULTS["TA_GAP_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["STORE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_existing_store_payload(**overrides) -> dict:
    defaults = {
        "name": "Legacy Store",
        "is_existing": True,
        "format_type": "TRADITIONAL",
        "open_year_sales_cents": 50000000,
    }
    defaults.update(overrides)
    return defaults


def create_developer_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["DEVELOPER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_site_agreement_payload(**overrides) -> dict:
    defaults = {
        "committed_delivery_date": DEFAULTS["COMMITTED_DELIVERY_DATE"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "earnest_money_cents": DEFAULTS["EARNEST_MONEY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_center_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DC_NAME"],
        "store_capacity": DEFAULTS["DC_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_dc_assignment_payload(**overrides) -> dict:
    defaults = {
        "stem_miles": DEFAULTS["STEM_MILES"],
        "deliveries_per_week": DEFAULTS["DELIVERIES_PER_WEEK"],
    }
    defaults.update(overrides)
    return defaults


def create_opening_plan_payload(**overrides) -> dict:
    defaults = {
        "opening_date": DEFAULTS["OPENING_DATE"],
        "peak_season": False,
    }
    defaults.update(overrides)
    return defaults


def create_cannibalization_study_payload(**overrides) -> dict:
    defaults = {"overlap_entries": []}
    defaults.update(overrides)
    return defaults


def create_capital_project_payload(**overrides) -> dict:
    defaults = {"kind": "REMODEL"}
    defaults.update(overrides)
    return defaults
