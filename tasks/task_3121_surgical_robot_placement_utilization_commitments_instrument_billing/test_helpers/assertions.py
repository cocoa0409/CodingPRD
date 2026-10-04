"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_system_fields(data: dict):
    """Every top-level resource carries the standard system-managed quartet."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_hospital_account(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert isinstance(data["idn_group_code"], str) and data["idn_group_code"]
    assert data["account_status"] in [
        "PROSPECT", "READINESS", "CONTRACTED", "ACTIVE", "DORMANT", "CLOSED",
    ]
    assert data["account_posture"] in ["ACTIVE", "ONBOARDING_GATE", "EXPANSION_BLOCKED"]


def assert_site_readiness_review(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert data["readiness_status"] in ["PENDING_REVIEW", "PASSED", "CONDITIONAL", "REJECTED"]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1
    assert isinstance(data["conditional_clearance_count"], int)
    assert isinstance(data["construction_uplift_fee_cents"], int)


def assert_system_configuration(data: dict):
    _assert_system_fields(data)
    assert data["model_code"] in ["DA_V1", "DA_V2", "SP_V1", "SP_V2", "SP_V3"]
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert 1 <= data["integration_tier"] <= 3
    assert isinstance(data["max_instrument_lives"], int)
    assert isinstance(data["feature_entitlements"], list)


def assert_placement_agreement(data: dict):
    _assert_system_fields(data)
    assert data["arrangement_type"] in ["PURCHASE", "LEASE", "USAGE_BASED"]
    assert data["agreement_status"] in [
        "DRAFT", "PENDING_ACCEPTANCE", "ACTIVE", "SUSPENDED", "TERMINATED",
    ]
    assert data["compliance_status"] in [
        "MEETS_COMMITMENT", "SHORTFALL_WARNING", "SHORTFALL_CHARGEABLE",
        "NON_COMPLIANT", "REMEDIATION_REQUIRED",
    ]
    assert isinstance(data["minimum_procedures_per_cycle"], int)
    assert isinstance(data["is_shortfall_waived"], bool)
    assert data["committed_cases"] >= 0


def assert_robot_system(data: dict):
    _assert_system_fields(data)
    assert data["service_status"] in [
        "NOT_INSTALLED", "INSTALLED", "IN_SERVICE",
        "SERVICE_ACTION_REQUIRED", "DECOMMISSIONED",
    ]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["instrument_lives_remaining"], int)
    assert data["instrument_lives_remaining"] >= 0, "lives accumulator is floored at 0"
    assert isinstance(data["expansion_eligible"], bool)
    assert isinstance(data["installed_software_release_index"], int)
    assert isinstance(data["entitled_feature_codes"], list)


def assert_surgeon_training_record(data: dict):
    _assert_system_fields(data)
    assert data["training_status"] in [
        "NOT_STARTED", "SIMULATION_COMPLETE", "PROCTORING",
        "SIMULATION_INCOMPLETE", "CREDENTIALED",
    ]
    assert isinstance(data["proctored_cases_completed"], int)
    assert isinstance(data["proctor_approval_pending"], bool)


def assert_credentialing_evidence(data: dict):
    _assert_system_fields(data)
    assert data["evidence_type"] in [
        "CREDENTIAL_LETTER", "PRIVILEGE_ATTESTATION", "PROCTOR_SIGNOFF_SET",
    ]
    assert data["evidence_status"] in ["VALID", "EXPIRING_SOON", "EXPIRED", "REVOKED"]


def assert_utilization_cycle(data: dict):
    _assert_system_fields(data)
    assert data["utilization_band"] in [
        "UNDERUTILIZED", "BASELINE", "HIGH", "EXPANSION_READY",
    ]
    assert isinstance(data["completed_case_count"], int)
    assert isinstance(data["scheduled_case_count"], int)
    assert isinstance(data["reporting_period_index"], int)


def assert_procedure_case(data: dict):
    _assert_system_fields(data)
    assert data["case_status"] in ["SCHEDULED", "COMPLETED", "CANCELLED", "BILLED"]
    assert data["procedure_family"] in [
        "UROLOGY", "GYNECOLOGY", "GENERAL_SURGERY", "THORACIC", "COLORECTAL",
    ]
    assert isinstance(data["instrument_billing_cents"], int)
    assert data["instrument_billing_cents"] >= 0
    assert isinstance(data["approved_instrument_load"], int)
    assert data["approved_instrument_load"] >= 0


def assert_service_contract(data: dict):
    _assert_system_fields(data)
    assert data["coverage_tier"] in ["COMPREHENSIVE", "STANDARD", "LIMITED", "PARTS_ONLY"]
    assert data["contract_status"] in ["ACTIVE", "EXPIRED", "TERMINATED"]
    assert data["response_time_commitment_hours"] in [4, 6, 12, 18, 24]


def assert_incident_service_request(data: dict):
    _assert_system_fields(data)
    assert data["request_status"] in [
        "OPEN", "ACKNOWLEDGED", "LOANER_PENDING", "LOANER_DISPATCHED",
        "SERVICE_ACTION_REQUIRED", "RESOLVED",
    ]
    assert data["incident_severity"] in ["MINOR", "MAJOR", "CRITICAL"]


def assert_loaner_dispatch(data: dict):
    _assert_system_fields(data)
    assert data["reservation_status"] in [
        "PROGRAMMED", "ACTIVATED", "RETURNED", "CANCELLED", "RECLAIMED",
    ]


def assert_software_release(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["release_index"], int)
    assert isinstance(data["deployed"], bool)


def assert_software_deployment(data: dict):
    _assert_system_fields(data)
    assert data["deployment_status"] in [
        "PROGRAMMED", "DELIVERED", "VALIDATED", "COMPLETED", "CANCELLED",
    ]


def assert_expansion_review(data: dict):
    _assert_system_fields(data)
    assert data["review_status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]


def assert_consumption_ledger(data: dict):
    _assert_system_fields(data)
    assert data["remaining_credit_units"] >= 0, "remaining credit is floored at 0"
    assert isinstance(data["consumed_procedure_units"], int)
    assert isinstance(data["supplied_procedure_units"], int)


def assert_transfer_transaction(data: dict):
    _assert_system_fields(data)
    assert data["transaction_status"] in ["COMMITTED", "SETTLED", "REVERSED"]
    assert isinstance(data["procedure_units"], int)


# ─── Domain invariants ───────────────────────────────────────────────────────

def assert_utilization_band_matches_count(cycle: dict):
    """The band is a pure function of the completed-case count."""
    c = cycle["completed_case_count"]
    band = cycle["utilization_band"]
    if c <= 7:
        expected = "UNDERUTILIZED"
    elif c <= 14:
        expected = "BASELINE"
    elif c <= 21:
        expected = "HIGH"
    else:
        expected = "EXPANSION_READY"
    assert band == expected, f"band for {c} completed cases should be {expected}, got {band}"


def assert_monetary_integer_cents(value: int):
    assert isinstance(value, int), f"monetary amounts are integer cents, got {type(value)}"
    assert value >= 0, "monetary amounts are non-negative"


def assert_service_line_tier_index(data: dict, expected_index: int):
    """The account's observed service-line depth index (0..4)."""
    tier = data.get("service_line_tier")
    labels = ["OBSERVATIONAL", "ESTABLISHED", "DEVELOPING", "ADVANCED", "REFERENCE"]
    assert tier == labels[expected_index], (
        f"expected service_line_tier {labels[expected_index]}, got {tier}"
    )


def assert_close_to(actual, expected, tol=1e-9, message=""):
    assert actual == pytest.approx(expected, abs=tol), (
        f"{message}: expected {expected}, got {actual}"
    )