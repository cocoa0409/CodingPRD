"""Payload factories — one per entity, input fields only."""


def create_mill_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Mill",
        "division": "ENERGY",
        "furnace_capacity_tons": 150,
        "caster_rate_tph": 80,
    }
    defaults.update(overrides)
    return defaults


def publish_index_payload(**overrides) -> dict:
    defaults = {
        "grade_category": "SHREDDED",
        "effective_month": "2026-09",
        "price_per_ton_cents": 38000,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "supplier_name": "River Metals Recycling",
        "grade_category": "SHREDDED",
        "contract_type": "FIXED",
        "contract_price_cents": 39000,
        "committed_tons": 100,
    }
    defaults.update(overrides)
    return defaults


def record_lot_payload(**overrides) -> dict:
    defaults = {
        "received_on": "2026-09-03",
        "tons_received": 20,
        "moisture_pct": 0.0,
        "cu_pct": 0.001,
        "mn_pct": 0.004,
    }
    defaults.update(overrides)
    return defaults


def create_grade_payload(**overrides) -> dict:
    defaults = {
        "grade_code": "GR40",
        "product_form": "BILLET",
        "grade_group": "GROUP_A",
        "certification_class": "STANDARD",
        "cu_max_pct": 0.004,
        "mn_min_pct": 0.002,
        "mn_max_pct": 0.012,
        "requires_energy_certified": False,
    }
    defaults.update(overrides)
    return defaults


def create_heat_payload(**overrides) -> dict:
    defaults = {
        "heat_number": "H-1",
        "target_tap_weight_tons": 8,
        "planned_tap_at": "2026-09-15T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def apply_charge_payload(**overrides) -> dict:
    defaults = {
        "tons": 8,
    }
    defaults.update(overrides)
    return defaults


def create_sheet_payload(**overrides) -> dict:
    defaults = {
        "cu_pct": 0.002,
        "mn_pct": 0.006,
    }
    defaults.update(overrides)
    return defaults


def record_interval_payload(**overrides) -> dict:
    defaults = {
        "interval_start": "2026-09-09T10:00:00Z",
        "interval_end": "2026-09-09T11:00:00Z",
        "kwh": 500,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Camp-1",
        "product_family": "REBAR",
        "grade_group": "GROUP_A",
        "planned_start": "2026-09-15T08:00:00Z",
        "planned_end": "2026-09-15T12:00:00Z",
        "roll_change_budget": 1,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "name": "Contract Builders Inc",
        "market": "CONSTRUCTION",
        "pricing_mode": "CONTRACT",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "product_family": "REBAR",
        "tons": 5,
        "fulfillment_month": "2026-09",
        "base_price_cents_per_ton": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(**overrides) -> dict:
    defaults = {
        "label": "PJM-ECON",
        "start_at": "2026-09-10T12:00:00Z",
        "end_at": "2026-09-10T14:00:00Z",
        "curtailment_credit_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def declare_event_payload(**overrides) -> dict:
    defaults = {
        "grid_operator": "PJM",
        "called_at": "2026-09-10T12:00:00Z",
        "released_at": "2026-09-10T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def grant_waiver_payload(**overrides) -> dict:
    defaults = {
        "scope": "HEAT",
        "reason": "grid-critical order",
    }
    defaults.update(overrides)
    return defaults


def create_scorecard_payload(**overrides) -> dict:
    defaults = {
        "period": "2026-09",
        "headcount": 7,
    }
    defaults.update(overrides)
    return defaults
