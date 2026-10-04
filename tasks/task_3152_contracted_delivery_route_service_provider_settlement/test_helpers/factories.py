"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_service_provider_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "tax_id": TEST_DEFAULTS["TAX_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_service_area_payload(**overrides) -> dict:
    defaults = {
        "area_code": TEST_DEFAULTS["AREA_CODE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "zip_prefix_low": TEST_DEFAULTS["ZIP_LOW"],
        "zip_prefix_high": TEST_DEFAULTS["ZIP_HIGH"],
        "stop_capacity_weekly": TEST_DEFAULTS["STOP_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(provider_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "policy_type": "AUTO_LIABILITY",
        "coverage_cents": TEST_DEFAULTS["POLICY_COVERAGE_CENTS"],
        "expires_at": TEST_DEFAULTS["POLICY_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(provider_id, service_area_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "service_area_id": service_area_id,
        "vehicle_class": "BOX_TRUCK",
        "gvwr_pounds": 26000,
        "is_temporary": False,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(provider_id, service_area_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "service_area_id": service_area_id,
        "full_name": "Dana Cruz",
        "license_class": "CLASS_B",
        "qualification_status": "QUALIFIED",
        "is_temporary": False,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(provider_id, service_area_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "service_area_id": service_area_id,
        "base_rate_cents_per_stop": TEST_DEFAULTS["BASE_RATE_CENTS_PER_STOP"],
        "package_rate_cents": TEST_DEFAULTS["PACKAGE_RATE_CENTS"],
        "peak_surcharge_cents": TEST_DEFAULTS["PEAK_SURCHARGE_CENTS"],
        "insurance_coverage_cents": TEST_DEFAULTS["INSURANCE_COVERAGE_CENTS"],
        "negotiated_by": TEST_DEFAULTS["NEGOTIATED_BY"],
    }
    defaults.update(overrides)
    return defaults


def create_route_assignment_payload(service_area_id, provider_id, expected_service_area_version, **overrides) -> dict:
    defaults = {
        "service_area_id": service_area_id,
        "provider_id": provider_id,
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
        "transfer_price_cents": 0,
        "expected_service_area_version": expected_service_area_version,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_period_payload(provider_id, service_area_id, expected_provider_version, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "service_area_id": service_area_id,
        "week_start_at": "2026-09-07T00:00:00Z",
        "is_peak_week": False,
        "fuel_rate_cents_per_mile": TEST_DEFAULTS["FUEL_RATE_CENTS_PER_MILE"],
        "expected_provider_version": expected_provider_version,
    }
    defaults.update(overrides)
    return defaults


def create_stop_observation_payload(**overrides) -> dict:
    defaults = {
        "observed_date": "2026-09-08T00:00:00Z",
        "recorded_at": "2026-09-08T18:00:00Z",
        "stops_count": 300,
        "packages_count": 250,
        "miles_driven": 0,
        "accessorial_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_deduction_payload(deduction_type, amount_cents, **overrides) -> dict:
    defaults = {
        "deduction_type": deduction_type,
        "amount_cents": amount_cents,
        "performance_factor_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_performance_metric_payload(provider_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "service_score": 90,
        "safety_score": 90,
        "customer_experience_score": 90,
    }
    defaults.update(overrides)
    return defaults


def create_chargeback_claim_payload(provider_id, settlement_period_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "settlement_period_id": settlement_period_id,
        "claim_type": "DAMAGE",
        "amount_cents": 20000,
        "recovery_rate_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "reason_code": "DEDUCTION",
        "disputed_amount_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_peak_declaration_payload(service_area_id, **overrides) -> dict:
    defaults = {
        "service_area_id": service_area_id,
        "declaration_code": "PEAK-2026-Q4",
        "starts_on": "2026-08-01T00:00:00Z",
        "ends_on": "2026-12-31T00:00:00Z",
        "authorized_vehicles": 5,
        "authorized_drivers": 4,
    }
    defaults.update(overrides)
    return defaults


def create_duty_shift_payload(starts_at, ends_at) -> dict:
    return {"starts_at": starts_at, "ends_at": ends_at}