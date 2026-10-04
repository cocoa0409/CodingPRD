"""Payload factories — one per entity, input fields only."""


def create_dealer_payload(**overrides) -> dict:
    payload = {
        "legal_name": "High Plains Machinery Co",
        "home_state_code": "NE",
        "territory_code": "T-410",
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "product_family": "EXCAVATION",
        "territory_code": "T-410",
        "exclusivity_level": "EXCLUSIVE",
        "start_at": "2026-09-01T00:00:00Z",
        "end_at": "2027-09-01T00:00:00Z",
        "performance_plan_share_pct": 20,
        "expected_dealer_version": 1,
    }
    payload.update(overrides)
    return payload


def create_commitment_payload(**overrides) -> dict:
    payload = {
        "agreement_id": None,
        "dealer_id": None,
        "product_family": "EXCAVATION",
        "machine_population_units": 500,
        "machine_population_slope": 1.0,
        "planned_annual_units": 50000,
        "emergency_stocking_target_pct": 50,
        "emergency_fill_window_hours": 24,
        "expected_dealer_version": 1,
    }
    payload.update(overrides)
    return payload


def create_batch_payload(**overrides) -> dict:
    payload = {
        "commitment_id": None,
        "product_family": "EXCAVATION",
        "requested_units": 10,
        "core_units": 0,
        "core_return_required": False,
        "requested_at": "2026-08-28T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_certification_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "technician_name": "T-01",
        "product_family": "EXCAVATION",
        "credential_code": "DEALER_MASTER",
        "certified_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_review_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "agreement_id": None,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "actual_territory_machine_units": 6,
        "territory_market_machine_units": 30,
        "sampled_service_orders": 10,
        "met_sla_service_orders": 9,
        "expected_dealeragreement_version": 1,
    }
    payload.update(overrides)
    return payload


def create_rebuild_claim_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "product_family": "EXCAVATION",
        "machine_serial": "SN-7001",
        "machine_operating_weight_lb": 90000,
        "client_meter_hours": 3000,
        "requested_at": "2026-08-20T00:00:00Z",
        "core_purchase_value_cents": 4000000,
        "rebuild_labor_hours": 10.0,
        "rebuild_labor_rate_cents": 14000,
        "certified_rebuild_spec_code": "CAT_CERTIFIED_2",
    }
    payload.update(overrides)
    return payload


def create_equipment_order_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "product_family": "EXCAVATION",
        "machine_serial": "SN-6100",
        "list_price_cents": 50000000,
        "requested_at": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_support_agreement_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "machine_serial": "SN-3001",
        "plan_tier": "PREMIUM",
        "enrolled_at": "2026-08-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_observation_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "product_family": "EXCAVATION",
        "observed_machine_units": 5,
        "territory_machine_units": 10,
        "recorded_at": "2026-03-01T00:00:00Z",
        "kind": "MACHINE",
    }
    payload.update(overrides)
    return payload


def create_service_order_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "commitment_id": None,
        "kind": "EMERGENCY_FILL",
        "product_family": "EXCAVATION",
        "orderable_ref_enabled": False,
        "restriction_scope": "HOURS_SPENT",
        "sla_hours": 6.0,
    }
    payload.update(overrides)
    return payload


def create_population_record_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "product_family": "EXCAVATION",
        "machine_serial": "SN-3001",
        "machine_operating_weight_lb": 50000,
        "meter_hours": 1000,
    }
    payload.update(overrides)
    return payload


def create_party_registration_payload(**overrides) -> dict:
    payload = {
        "dealer_id": None,
        "territory_code": "T-410",
        "registered_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


__all__ = [
    "create_dealer_payload", "create_agreement_payload", "create_commitment_payload",
    "create_batch_payload", "create_certification_payload", "create_review_payload",
    "create_rebuild_claim_payload", "create_equipment_order_payload",
    "create_support_agreement_payload", "create_observation_payload",
    "create_service_order_payload", "create_population_record_payload",
    "create_party_registration_payload",
]