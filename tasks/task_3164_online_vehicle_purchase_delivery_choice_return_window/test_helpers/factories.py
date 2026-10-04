"""Payload factories — one per entity, input fields only."""

import uuid


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": f"customer-{uuid.uuid4().hex[:8]}@example.com",
        "state_code": "GA",
    }
    defaults.update(overrides)
    return defaults


def create_center_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Center",
        "market_code": "ATL-A",
        "daily_capacity": 5,
        "slot_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "vin": f"VIN{uuid.uuid4().hex[:14].upper()}",
        "make": "Honda",
        "model": "Accord",
        "year": 2022,
        "mileage": 20000,
        "base_price_cents": 2000000,
        "market_code": "ATL-A",
    }
    defaults.update(overrides)
    return defaults


def create_annotation_payload(**overrides) -> dict:
    defaults = {
        "area": "door",
        "severity": "MINOR",
        "deduction_cents": 30000,
        "image_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_prequalify_payload(**overrides) -> dict:
    defaults = {
        "annual_income_cents": 8000000,
        "credit_band": "A",
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(**overrides) -> dict:
    defaults = {
        "vin": f"TRADE{uuid.uuid4().hex[:11].upper()}",
        "questionnaire": {
            "vehicle_band": "MID",
            "accident_history": False,
            "mechanical_issues": False,
            "tire_condition": "GOOD",
            "odometer": 45000,
            "smoker_vehicle": False,
        },
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "fulfillment_choice": "HOME_DELIVERY",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "market_code": "ATL-A",
        "address_region": "ATL-CORE",
        "start_at": "2026-09-02T10:00:00Z",
        "end_at": "2026-09-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {
        "return_mileage": 10000,
        "reason_code": "CHANGED_MIND",
    }
    defaults.update(overrides)
    return defaults


def create_defect_claim_payload(**overrides) -> dict:
    defaults = {
        "defect_description": "rattle",
        "defect_area": "dashboard",
    }
    defaults.update(overrides)
    return defaults
