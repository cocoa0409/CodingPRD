"""Payload factories — one per creatable resource, input fields only.

Defaults are chosen so a no-override payload is always valid against the
PRD's shape rules (positive weights, tare below gross, window start before
end, frozen trailer setpoint, exactly one lot source id is left to the
caller, and so on).
"""

DEFAULT_WINDOW_START = "2026-09-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-10-15T00:00:00Z"
DEFAULT_TERM_START = "2026-09-01T00:00:00Z"
DEFAULT_TERM_END = "2027-03-01T00:00:00Z"


def create_grower_payload(**overrides) -> dict:
    defaults = {
        "grower_code": "GR-100",
        "legal_name": "Columbia Basin Farms LLC",
        "region": "COLUMBIA_BASIN",
    }
    defaults.update(overrides)
    return defaults


def create_crop_contract_payload(grower_id: str, **overrides) -> dict:
    defaults = {
        "grower_id": grower_id,
        "variety": "RUSSET_BURBANK",
        "contracted_acres": 100,
        "expected_yield_cwt_per_acre": 400,
        "base_price_per_cwt_cents": 2500,
        "delivery_window_start": DEFAULT_WINDOW_START,
        "delivery_window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    defaults = {
        "contracted_acres": 120,
        "expected_yield_cwt_per_acre": 400,
        "base_price_per_cwt_cents": 2700,
        "delivery_window_start": DEFAULT_WINDOW_START,
        "delivery_window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_contracted_lot_payload(contract_id: str, facility_id: str, **overrides) -> dict:
    """CONTRACTED-mode intake: grade-A metrics, 1000.0 net cwt by default."""
    defaults = {
        "contract_id": contract_id,
        "facility_id": facility_id,
        "variety": "RUSSET_BURBANK",
        "gross_weight_cwt": 1050.0,
        "tare_weight_cwt": 50.0,
        "defect_pct": 2.0,
        "specific_gravity": 1.085,
        "sugar_end_rating": 1.5,
    }
    defaults.update(overrides)
    return defaults


def create_import_lot_payload(shortage_event_id: str, facility_id: str, **overrides) -> dict:
    """IMPORT-mode intake: grade-B metrics, 2000.0 net cwt by default."""
    defaults = {
        "shortage_event_id": shortage_event_id,
        "facility_id": facility_id,
        "variety": "RUSSET_BURBANK",
        "gross_weight_cwt": 2020.0,
        "tare_weight_cwt": 20.0,
        "defect_pct": 3.0,
        "specific_gravity": 1.075,
        "sugar_end_rating": 2.5,
    }
    defaults.update(overrides)
    return defaults


def create_storage_facility_payload(**overrides) -> dict:
    defaults = {
        "facility_code": "CELL-1",
        "capacity_cwt": 50000,
        "target_temp_f": 38.0,
        "target_co2_pct": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(**overrides) -> dict:
    """Defaults are below every WATCH threshold (posture stays NORMAL)."""
    defaults = {
        "recorded_at": "2026-09-02T00:00:00Z",
        "temperature_f": 38.0,
        "humidity_pct": 90.0,
        "co2_pct": 3.0,
        "sprout_index": 1.0,
        "disease_incidence_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_processing_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "LINE-1",
        "supported_cut_families": ["STRAIGHT", "CRINKLE"],
        "rated_throughput_cases_per_hour": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_cut_specification_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "spec_code": "SP-A-1",
        "cut_family": "STRAIGHT",
        "cut_size_mm": 9.5,
        "coating_type": "CLEAR",
        "target_color_units": 2.5,
        "max_cook_time_sec": 195,
    }
    defaults.update(overrides)
    return defaults


def create_customer_chain_payload(**overrides) -> dict:
    defaults = {
        "chain_code": "CH-ALPHA",
        "legal_name": "Alpha Burger Co",
        "priority_tier": "TIER_1_STRATEGIC",
    }
    defaults.update(overrides)
    return defaults


def create_supply_agreement_payload(customer_id: str, spec_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "spec_id": spec_id,
        "weekly_contracted_cases": 10000,
        "price_per_case_cents": 299,
        "term_start": DEFAULT_TERM_START,
        "term_end": DEFAULT_TERM_END,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(line_id: str, spec_id: str, agreement_id: str,
                                  input_lot_ids: list, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "spec_id": spec_id,
        "agreement_id": agreement_id,
        "input_lot_ids": list(input_lot_ids),
        "scheduled_start": "2026-09-02T08:00:00Z",
        "scheduled_end": "2026-09-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(agreement_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "carrier_name": "FrostLine Logistics",
        "trailer_setpoint_f": -5.0,
        "route_type": "DIRECT_CHAIN",
        "lines": list(lines),
    }
    defaults.update(overrides)
    return defaults


def create_shortage_event_payload(**overrides) -> dict:
    defaults = {
        "scope_variety": "RUSSET_BURBANK",
        "declared_deficit_cwt": 5000,
        "available_week_cases": 1000,
        "response_mode": "PRO_RATA",
    }
    defaults.update(overrides)
    return defaults
