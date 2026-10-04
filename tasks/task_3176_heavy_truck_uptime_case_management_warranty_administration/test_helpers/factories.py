"""Payload factories — one per entity, input fields only.

Defaults are valid-but-plain values; unique fields (VINs, campaign codes) are
randomized per call so tests never collide on uniqueness constraints.
"""
import uuid


def _vin() -> str:
    """17-character VIN, unique per call."""
    return ("1FUJGBDV8CL" + uuid.uuid4().hex[:6].upper())[:17]


def _campaign_code() -> str:
    return "RCL-" + uuid.uuid4().hex[:8].upper()


DEFAULTS = {
    "FLEET_NAME": "Test Fleet",
    "HOME_REGION": "SE",
    "MODEL_CODE": "CASCADIA_126",
    "IN_SERVICE_ON": "2026-01-01T00:00:00Z",
    "ODOMETER_MILES": 50000,
    "BASE_WARRANTY_UNTIL_MILES": 250000,
    "BASE_WARRANTY_UNTIL_ON": "2028-01-01T00:00:00Z",
    "DEALER_NAME": "Test Freightliner",
    "DEALER_REGION": "SE",
    "HOURLY_LABOR_RATE_CENTS": 18500,
    "BAY_CODE": "B1",
    "FAULT_CODE": "SPN3216_FMI4",
    "FAULT_SEVERITY": "WARNING",
    "FAULT_RECOMMENDED_ACTION": "SCHEDULE_SERVICE",
    "FAULT_OCCURRED_AT": "2026-09-01T00:00:00Z",
    "SCHEDULED_START_AT": "2026-09-01T13:00:00Z",
    "SCHEDULED_END_AT": "2026-09-01T17:00:00Z",
    "DIAGNOSTIC_MINUTES": 30,
    "PART_NUMBER": "A0001404439",
    "PART_QUANTITY": 1,
    "PART_WEIGHT_KG": 5.0,
    "PART_COST_CENTS": 50000,
    "CLAIM_TYPE": "BASE_WARRANTY",
    "LABOR_MINUTES_CLAIMED": 100,
    "PARTS_CLAIMED_CENTS": 50000,
    "CONTRACT_TYPE": "EXTENDED_POWERTRAIN",
    "CONTRACT_STARTS_ON": "2026-01-01T00:00:00Z",
    "CONTRACT_ENDS_ON": "2027-01-01T00:00:00Z",
    "CONTRACT_MAX_MILES": 200000,
    "CONTRACT_PREMIUM_CENTS": 1000000,
    "CAMPAIGN_KIND": "RECALL",
    "CAMPAIGN_FAULT_CODE": "SPN3216_FMI4",
    "CAMPAIGN_OPENS_ON": "2026-08-01T00:00:00Z",
    "CAMPAIGN_CLOSES_ON": "2027-08-01T00:00:00Z",
}


def create_fleet_payload(**overrides) -> dict:
    defaults = {
        "fleet_name": DEFAULTS["FLEET_NAME"],
        "home_region": DEFAULTS["HOME_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    defaults = {
        "vin": _vin(),
        "model_code": DEFAULTS["MODEL_CODE"],
        "in_service_on": DEFAULTS["IN_SERVICE_ON"],
        "odometer_miles": DEFAULTS["ODOMETER_MILES"],
        "base_warranty_until_miles": DEFAULTS["BASE_WARRANTY_UNTIL_MILES"],
        "base_warranty_until_on": DEFAULTS["BASE_WARRANTY_UNTIL_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "dealer_name": DEFAULTS["DEALER_NAME"],
        "region": DEFAULTS["DEALER_REGION"],
        "hourly_labor_rate_cents": DEFAULTS["HOURLY_LABOR_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_bay_payload(**overrides) -> dict:
    defaults = {"bay_code": DEFAULTS["BAY_CODE"]}
    defaults.update(overrides)
    return defaults


def create_fault_event_payload(**overrides) -> dict:
    defaults = {
        "fault_code": DEFAULTS["FAULT_CODE"],
        "severity": DEFAULTS["FAULT_SEVERITY"],
        "recommended_action": DEFAULTS["FAULT_RECOMMENDED_ACTION"],
        "occurred_at": DEFAULTS["FAULT_OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {"fault_code": DEFAULTS["FAULT_CODE"]}
    defaults.update(overrides)
    return defaults


def schedule_case_payload(dealer_id, bay_id, expected_truck_version, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "bay_id": bay_id,
        "scheduled_start_at": DEFAULTS["SCHEDULED_START_AT"],
        "scheduled_end_at": DEFAULTS["SCHEDULED_END_AT"],
        "expected_truck_version": expected_truck_version,
    }
    defaults.update(overrides)
    return defaults


def authorize_work_order_payload(**overrides) -> dict:
    defaults = {"diagnostic_minutes_authorized": DEFAULTS["DIAGNOSTIC_MINUTES"]}
    defaults.update(overrides)
    return defaults


def complete_work_order_payload(**overrides) -> dict:
    defaults = {"labor_minutes_actual": 60, "repair_outcome": "FIXED"}
    defaults.update(overrides)
    return defaults


def create_part_order_payload(**overrides) -> dict:
    defaults = {
        "part_number": DEFAULTS["PART_NUMBER"],
        "quantity": DEFAULTS["PART_QUANTITY"],
        "part_weight_kg_per_unit": DEFAULTS["PART_WEIGHT_KG"],
        "part_cost_cents": DEFAULTS["PART_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def evaluate_expedite_payload(**overrides) -> dict:
    defaults = {
        "dealer_repair_hours_est": 10,
        "downtime_rate_cents_per_hour": 100000,
        "distance_band": "INTRA_REGION",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": DEFAULTS["CLAIM_TYPE"],
        "labor_minutes_claimed": DEFAULTS["LABOR_MINUTES_CLAIMED"],
        "parts_claimed_cents": DEFAULTS["PARTS_CLAIMED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_coverage_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_type": DEFAULTS["CONTRACT_TYPE"],
        "starts_on": DEFAULTS["CONTRACT_STARTS_ON"],
        "ends_on": DEFAULTS["CONTRACT_ENDS_ON"],
        "max_miles": DEFAULTS["CONTRACT_MAX_MILES"],
        "premium_cents": DEFAULTS["CONTRACT_PREMIUM_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "campaign_code": _campaign_code(),
        "campaign_kind": DEFAULTS["CAMPAIGN_KIND"],
        "affected_model_codes": [DEFAULTS["MODEL_CODE"]],
        "fault_code": DEFAULTS["CAMPAIGN_FAULT_CODE"],
        "opens_on": DEFAULTS["CAMPAIGN_OPENS_ON"],
        "closes_on": DEFAULTS["CAMPAIGN_CLOSES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_recovery_payload(part_return_id, **overrides) -> dict:
    defaults = {
        "part_return_id": part_return_id,
        "supplier_id": "supplier-A",
        "claimed_amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults
