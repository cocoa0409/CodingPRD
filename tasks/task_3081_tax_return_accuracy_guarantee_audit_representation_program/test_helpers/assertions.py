"""Entity assertions: structural checks on API payloads per the PRD contract."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity_name}.version must be a positive int"


def assert_office(data: dict):
    _assert_common(data, "Office")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert data["posture"] in ["OK", "WATCH", "PROBATION"]


def assert_preparer(data: dict):
    _assert_common(data, "Preparer")
    assert data["tier"] in ["ASSOCIATE", "SENIOR", "MASTER", "ENROLLED_AGENT"]
    assert data["credential_status"] in ["ACTIVE", "SUSPENDED"]
    assert data["remediation_status"] in ["NONE", "ACTIVE", "COMPLETED"]


def assert_client(data: dict):
    _assert_common(data, "Client")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_tax_return(data: dict):
    _assert_common(data, "TaxReturn")
    assert data["status"] in ["PREPARING", "FILED"]
    assert isinstance(data["components"], list) and len(data["components"]) >= 1
    assert isinstance(data["quoted_fee_cents"], int)
    if data["status"] == "FILED":
        assert isinstance(data["final_fee_cents"], int), "FILED return must have final_fee_cents"
    else:
        assert data.get("final_fee_cents") is None, "PREPARING return keeps final_fee_cents null"


def assert_protection_product(data: dict):
    _assert_common(data, "ProtectionProduct")
    assert data["tier"] in ["STANDARD", "PLUS"]
    assert data["status"] in ["ACTIVE", "VOID"]
    assert isinstance(data["premium_cents"], int)


def assert_authority_notice(data: dict):
    _assert_common(data, "AuthorityNotice")
    assert data["authority_type"] in ["FEDERAL", "STATE"]
    assert data["status"] in ["OPEN", "PAID", "ABATED", "WITHDRAWN"]
    assert isinstance(data["tax_delta_cents"], int) and data["tax_delta_cents"] >= 0
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0
    if data["status"] == "OPEN":
        assert data.get("interest_cents") is None
        assert data.get("paid_at") is None


def assert_claim(data: dict):
    _assert_common(data, "Claim")
    assert data["status"] in [
        "TRIAGE", "INFO_NEEDED", "SCOPE_CONFIRMED", "ASSIGNED",
        "REPRESENTING", "RESOLVED", "REOPENED", "DENIED",
    ]
    assert isinstance(data["payout_base_cents"], int)
    assert isinstance(data["payout_interest_cents"], int)
    assert isinstance(data["payout_penalty_cents"], int)
    assert isinstance(data["payout_total_cents"], int)


def assert_enrolled_agent(data: dict):
    _assert_common(data, "EnrolledAgent")
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["max_parallel"], int) and data["max_parallel"] >= 1


def assert_representation_assignment(data: dict):
    _assert_common(data, "RepresentationAssignment")
    assert data["status"] in ["ACTIVE", "COMPLETED", "CANCELLED"]


def assert_power_of_attorney(data: dict):
    _assert_common(data, "PowerOfAttorney")
    assert data["status"] in ["DRAFT", "EXECUTED", "REVOKED", "EXPIRED"]


def assert_remediation_action(data: dict):
    _assert_common(data, "RemediationAction")
    assert data["status"] in ["OPEN", "COMPLETED"]


def assert_office_escrow(data: dict):
    _assert_common(data, "OfficeEscrow")
    assert isinstance(data["funded_cents"], int) and data["funded_cents"] > 0
    assert isinstance(data["paid_out_cents"], int) and data["paid_out_cents"] >= 0
    assert isinstance(data["expected_accrual_cents"], int) and data["expected_accrual_cents"] >= 0


def assert_office_quality_snapshot(data: dict):
    _assert_common(data, "OfficeQualitySnapshot")
    assert isinstance(data["returns_examined"], int) and data["returns_examined"] > 0
    assert isinstance(data["returns_with_defects"], int)
    assert 0 <= data["returns_with_defects"] <= data["returns_examined"]
    assert isinstance(data["quality_score"], int)
    assert 0 <= data["quality_score"] <= 100
    assert data["posture_after"] in ["OK", "WATCH", "PROBATION"]
