"""Payload factories — one per entity, input fields only."""
import itertools

_code_counter = itertools.count(1)

DEFAULTS = {
    "BASE_UNIT_PRICE_CENTS": 50_000_000,
    "BASE_CONTRACT_YEAR": 2027,
    "COMPONENT_COST": 800_000,
    "TRANSITION_TARGET_YEAR": 2035,
}


def create_agency_payload(**overrides) -> dict:
    n = next(_code_counter)
    defaults = {
        "name": f"Test Transit {n}",
        "agency_code": f"TT{n:04d}",
        "federally_funded": True,
        "transition_target_year": DEFAULTS["TRANSITION_TARGET_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(agency_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "base_quantity": 1,
        "base_unit_price_cents": DEFAULTS["BASE_UNIT_PRICE_CENTS"],
        "base_contract_year": DEFAULTS["BASE_CONTRACT_YEAR"],
        "escalation_index": "PPI_1413",
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    n = next(_code_counter)
    defaults = {
        "name": f"Component {n}",
        "category": "PROPULSION",
        "unit_cost_cents": DEFAULTS["COMPONENT_COST"],
        "is_domestic": True,
    }
    defaults.update(overrides)
    return defaults


def create_bus_configuration_payload(contract_id, component_ids, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "propulsion_type": "DIESEL",
        "seating_layout": {"rows": 10},
        "fare_equipment": {},
        "accessibility_features": ["WHEELCHAIR_LIFT"],
        "component_ids": list(component_ids),
    }
    defaults.update(overrides)
    return defaults


def create_bus_unit_payload(contract_id, bus_configuration_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "bus_configuration_id": bus_configuration_id,
        "assembly_location": "US_MAIN",
    }
    defaults.update(overrides)
    return defaults


def create_production_slot_payload(**overrides) -> dict:
    defaults = {
        "line_id": "LINE_A",
        "start_ts": "2026-09-01T00:00:00Z",
        "end_ts": "2026-09-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_record_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "audit_type": "PRE_AWARD",
        "auditor_id": "aud-1",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "variant": "COST_BASED",
        "issued_by": "co-1",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_record_payload(bus_unit_id, **overrides) -> dict:
    defaults = {
        "bus_unit_id": bus_unit_id,
        "inspection_type": "PLANT",
        "inspector_id": "insp-1",
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(bus_unit_id, component_id, **overrides) -> dict:
    defaults = {
        "bus_unit_id": bus_unit_id,
        "defect_code": "DEFECT",
        "component_id": component_id,
        "claimed_amount_cents": 150_000,
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(agency_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "propulsion_type": "BEV",
        "scheduled_date": "2026-09-10T09:00:00Z",
        "attendee_count": 3,
    }
    defaults.update(overrides)
    return defaults


def create_parts_stock_payload(agency_id, component_id, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "component_id": component_id,
        "quantity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_parts_kit_payload(bus_unit_id, component_ids, **overrides) -> dict:
    defaults = {
        "bus_unit_id": bus_unit_id,
        "component_ids": list(component_ids),
    }
    defaults.update(overrides)
    return defaults
