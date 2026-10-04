"""Payload factories — one per entity, built from the PRD's input fields only.

Every factory returns a fresh dict so callers can freely mutate it; `**overrides`
replace individual fields.
"""

from .constants import TEST_DEFAULTS


def create_account_payload(**overrides) -> dict:
    payload = {
        "account_name": TEST_DEFAULTS["ACCOUNT_NAME"],
        "idn_group_code": TEST_DEFAULTS["IDN_GROUP_CODE"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "placement_cap": TEST_DEFAULTS["PLACEMENT_CAP"],
        "maximum_procedure_commitment": TEST_DEFAULTS["MAXIMUM_PROCEDURE_COMMITMENT"],
    }
    payload.update(overrides)
    return payload


def create_configuration_payload(**overrides) -> dict:
    payload = {
        "model_code": "DA_V1",
        "base_placement_fee_cents": TEST_DEFAULTS["BASE_PLACEMENT_FEE_CENTS"],
        "max_instrument_lives": TEST_DEFAULTS["MAX_INSTRUMENT_LIVES"],
        "feature_entitlements": [],
        "requires_dark_fiber": False,
        "requires_dedicated_power_circuit": False,
        "integration_tier": TEST_DEFAULTS["INTEGRATION_TIER"],
        "min_operating_room_length_cm": TEST_DEFAULTS["MIN_OR_LENGTH_CM"],
        "min_operating_room_width_cm": TEST_DEFAULTS["MIN_OR_WIDTH_CM"],
        "min_table_throw_radius_cm": TEST_DEFAULTS["MIN_THROW_RADIUS_CM"],
        "min_ceiling_clearance_cm": TEST_DEFAULTS["MIN_CEILING_CLEARANCE_CM"],
    }
    payload.update(overrides)
    return payload


def create_readiness_review_payload(configuration_id: str, **overrides) -> dict:
    payload = {
        "site_code": "SITE-1",
        "operating_room_length_cm": 900,
        "operating_room_width_cm": 800,
        "table_throw_radius_cm": 400,
        "ceiling_clearance_cm": 300,
        "has_dedicated_power_circuit": True,
        "has_dark_fiber_run": True,
        "evaluated_configuration_id": configuration_id,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(account_id: str, configuration_id: str,
                             review_id: str, **overrides) -> dict:
    payload = {
        "hospital_account_id": account_id,
        "system_configuration_id": configuration_id,
        "site_readiness_review_id": review_id,
        "arrangement_type": "PURCHASE",
        "base_monthly_fee_cents": TEST_DEFAULTS["BASE_MONTHLY_FEE_CENTS"],
        "minimum_procedures_per_cycle": 0,
        "interval_months": 1,
        "placement_fee_cents": TEST_DEFAULTS["PLACEMENT_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_training_record_payload(**overrides) -> dict:
    payload = {
        "surgeon_name": TEST_DEFAULTS["SURGEON_NAME"],
        "simulation_modules_completed": 3,
        "required_proctored_cases": TEST_DEFAULTS["REQUIRED_PROCTORED_CASES"],
    }
    payload.update(overrides)
    return payload


def create_procedure_case_payload(training_record_id: str, **overrides) -> dict:
    payload = {
        "training_record_id": training_record_id,
        "procedure_family": "UROLOGY",
        "case_started_at": "2026-09-10T08:00:00Z",
        "duration_minutes": 60,
        "instrument_load": 1,
        "is_emergency": False,
    }
    payload.update(overrides)
    return payload


def create_credentialing_evidence_payload(**overrides) -> dict:
    payload = {
        "evidence_type": "CREDENTIAL_LETTER",
        "issued_utc": TEST_DEFAULTS["EVIDENCE_ISSUED_UTC"],
        "expires_utc": TEST_DEFAULTS["EVIDENCE_EXPIRES_UTC"],
    }
    payload.update(overrides)
    return payload


def create_service_contract_payload(system_id: str, **overrides) -> dict:
    payload = {
        "robot_system_id": system_id,
        "coverage_tier": "COMPREHENSIVE",
        "contract_start_utc": "2026-09-01T00:00:00Z",
        "contract_months": 12,
    }
    payload.update(overrides)
    return payload


def create_incident_payload(system_id: str, **overrides) -> dict:
    payload = {
        "robot_system_id": system_id,
        "incident_started_at": "2026-09-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_loaner_dispatch_payload(system_id: str, **overrides) -> dict:
    payload = {
        "robot_system_id": system_id,
        "loaner_serial_number": "LOAN-1",
        "dispatch_window_start_utc": "2026-09-10T00:00:00Z",
        "dispatch_window_end_utc": "2026-09-24T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_software_release_payload(**overrides) -> dict:
    payload = {
        "release_index": 1,
        "feature_codes": ["FIREFLY"],
    }
    payload.update(overrides)
    return payload


def create_software_deployment_payload(release_id: str, **overrides) -> dict:
    payload = {
        "software_release_id": release_id,
        "scheduled_window_start_utc": "2026-09-20T00:00:00Z",
        "scheduled_window_end_utc": "2026-09-20T04:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_expansion_review_payload(account_id: str, agreement_id: str, **overrides) -> dict:
    payload = {
        "hospital_account_id": account_id,
        "placement_agreement_id": agreement_id,
        "support_request_ranking": 0,
        "requested_case_capacity": 22,
    }
    payload.update(overrides)
    return payload


def create_consumption_ledger_payload(**overrides) -> dict:
    payload = {"maximum_procedure_commitment": 30}
    payload.update(overrides)
    return payload


def create_transfer_payload(source_account_id: str, destination_account_id: str,
                            **overrides) -> dict:
    payload = {
        "source_account_id": source_account_id,
        "destination_account_id": destination_account_id,
        "procedure_units": 5,
        "transfer_window_start_utc": "2026-09-01T00:00:00Z",
        "transfer_window_end_utc": "2026-09-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload