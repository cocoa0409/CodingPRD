"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULT_BIN_PROFILE = [
    {"bin_code": "B1", "wattage": 480.0, "fraction": 0.5},
    {"bin_code": "B2", "wattage": 470.0, "fraction": 0.5},
]

DEFAULT_WINDOW_START = "2027-03-01T00:00:00Z"
DEFAULT_WINDOW_END = "2027-04-01T00:00:00Z"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Acme Solar Dev",
        "credit_tier": "TIER_A",
        "tax_credit_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_module_series_payload(**overrides) -> dict:
    defaults = {
        "series_code": "S6",
        "technology": "CDTE_THIN_FILM",
        "nominal_wattage": 480.0,
        "bin_profile": [dict(entry) for entry in DEFAULT_BIN_PROFILE],
        "temp_coefficient": -0.0028,
    }
    defaults.update(overrides)
    return defaults


def create_production_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "OH-L3",
        "site_country": "US",
        "annual_capacity_mw": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    defaults = {
        "delivery_year": 2027,
        "contracted_mw": 10.0,
        "price_usd_per_w": 0.25,
        "deposit_usd": 200000.0,
        "term_years": 1,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(**overrides) -> dict:
    defaults = {
        "quarter": 0,
        "input_modules": 100,
        "good_modules": 70,
        "bin_counts": [
            {"bin_code": "B1", "count": 35},
            {"bin_code": "B2", "count": 35},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(**overrides) -> dict:
    defaults = {
        "scheduled_window_start": DEFAULT_WINDOW_START,
        "scheduled_window_end": DEFAULT_WINDOW_END,
        "volume_mw": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_component_lot_payload(**overrides) -> dict:
    defaults = {
        "supplier_name": "GlassCo",
        "lot_code": "LOT-US-1",
        "component_type": "GLASS",
        "country_of_origin": "US",
        "lot_cost_usd": 400.0,
    }
    defaults.update(overrides)
    return defaults


def create_attestation_payload(**overrides) -> dict:
    defaults = {
        "period_year": 2026,
        "labor_cost_usd": 100.0,
        "feedstock_cost_usd": 50.0,
        "glass_cost_usd": 30.0,
        "balance_of_system_cost_usd": 20.0,
        "overhead_cost_usd": 10.0,
        "total_manufactured_cost_usd": 500.0,
    }
    defaults.update(overrides)
    return defaults


def create_recycling_obligation_payload(**overrides) -> dict:
    defaults = {
        "period_year": 2026,
        "shipped_volume_mw": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "PRODUCT_DEFECT",
        "claimed_mw": 1.0,
    }
    defaults.update(overrides)
    return defaults
