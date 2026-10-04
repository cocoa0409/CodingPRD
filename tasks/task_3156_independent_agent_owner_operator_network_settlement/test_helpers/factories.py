"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "AGENT_NAME": "Test Freight Agency",
    "OWNER_NAME": "Test Trucking LLC",
    "HOME_STATE": "TX",
    "HOME_TERMINAL_CITY": "Amarillo",
    "SHIPPER_NAME": "Test Shipper Co",
    "UNIT_NUMBER": "T-900",
}


def create_agent_payload(**overrides) -> dict:
    payload = {
        "agent_code": "AG-TEST-01",
        "legal_name": DEFAULTS["AGENT_NAME"],
        "home_state": DEFAULTS["HOME_STATE"],
        "commission_rate_pct": TEST_DEFAULTS["AGENT_COMMISSION_RATE"],
        "territory_codes": ["TX", "OK"],
        "customer_ownership_days": 365,
    }
    payload.update(overrides)
    return payload


def create_capacity_owner_payload(**overrides) -> dict:
    payload = {
        "owner_code": "BCO-TEST-01",
        "legal_name": DEFAULTS["OWNER_NAME"],
        "home_terminal_city": DEFAULTS["HOME_TERMINAL_CITY"],
        "revenue_split_pct": TEST_DEFAULTS["REVENUE_SPLIT_PCT"],
        "oa_enrolled": True,
        "liability_insurance_deductible_cents": 250000,
    }
    payload.update(overrides)
    return payload


def create_equipment_payload(capacity_owner_id: str, **overrides) -> dict:
    payload = {
        "capacity_owner_id": capacity_owner_id,
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "equipment_type": "TRACTOR",
        "model_year": 2021,
        "inspection_due_at": TEST_DEFAULTS["INSPECTION_DUE_AT"],
    }
    payload.update(overrides)
    return payload


def create_compliance_document_payload(capacity_owner_id: str, **overrides) -> dict:
    payload = {
        "capacity_owner_id": capacity_owner_id,
        "document_type": "CDL",
        "document_number": "TX-CDL-90001",
        "issued_at": "2026-01-05T00:00:00Z",
        "expires_at": "2027-01-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_customer_account_payload(agent_id: str, **overrides) -> dict:
    payload = {
        "agent_id": agent_id,
        "customer_ref": "CUST-TEST-01",
        "shipper_name": DEFAULTS["SHIPPER_NAME"],
        "first_booked_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_load_payload(agent_id: str, **overrides) -> dict:
    payload = {
        "agent_id": agent_id,
        "customer_ref": "CUST-TEST-01",
        "origin_state": "TX",
        "destination_state": "OK",
        "linehaul_revenue_cents": TEST_DEFAULTS["LINEHAUL_CENTS"],
        "fuel_surcharge_cents": TEST_DEFAULTS["FUEL_SURCHARGE_CENTS"],
        "accessorial_revenue_cents": TEST_DEFAULTS["ACCESSORIAL_CENTS"],
        "dispatched_miles": TEST_DEFAULTS["DISPATCHED_MILES"],
    }
    payload.update(overrides)
    return payload


def create_load_offer_payload(load_id: str, capacity_owner_id: str, **overrides) -> dict:
    payload = {
        "load_id": load_id,
        "capacity_owner_id": capacity_owner_id,
        "offered_pay_cents": 126000,
        "offered_at": "2026-09-01T01:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_trip_payload(load_id: str, capacity_owner_id: str, equipment_id: str, **overrides) -> dict:
    payload = {
        "load_id": load_id,
        "capacity_owner_id": capacity_owner_id,
        "equipment_id": equipment_id,
        "departed_at": "2026-09-01T03:00:00Z",
        "deadline_at": "2026-09-02T03:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_settlement_payload(trip_id: str, **overrides) -> dict:
    payload = {
        "trip_id": trip_id,
        "settlement_method": "FINAL",
    }
    payload.update(overrides)
    return payload


def create_escrow_transaction_payload(capacity_owner_id: str, **overrides) -> dict:
    payload = {
        "capacity_owner_id": capacity_owner_id,
        "transaction_type": "ESCROW_DEPOSIT",
        "amount_cents": TEST_DEFAULTS["ESCROW_DEPOSIT_CENTS"],
        "effective_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_advance_post_payload(capacity_owner_id: str, **overrides) -> dict:
    payload = {
        "capacity_owner_id": capacity_owner_id,
        "amount_cents": 200000,
        "effective_at": "2026-09-01T05:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides) -> dict:
    payload = {
        "inspected_at": "2026-08-15T00:00:00Z",
        "result": "PASS",
        "inspector_certificate": "CERT-TEST-001",
    }
    payload.update(overrides)
    return payload