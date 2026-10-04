"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_organization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data.get("legal_name"), str)
    assert data.get("assurance_tier") in ("STANDARD", "HIGH_ASSURANCE")
    assert data.get("authentication_policy") in ("STANDARD", "PHISHING_RESISTANT")
    assert isinstance(data.get("idp_protocols"), list) and len(data["idp_protocols"]) > 0
    assert isinstance(data.get("approved_firmware_versions"), list)
    assert isinstance(data.get("backup_key_minimum"), int) and data["backup_key_minimum"] >= 1
    assert data.get("status") in ("ACTIVE", "SUSPENDED")


def assert_key_model(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("model_code"), str) and data["model_code"]
    assert isinstance(data.get("connectors"), list) and len(data["connectors"]) > 0
    assert isinstance(data.get("protocols"), list) and len(data["protocols"]) > 0
    assert data.get("form_factor") in ("KEYCHAIN", "NANO", "CARD", "BIOMETRIC")
    assert isinstance(data.get("unit_price_cents"), int) and data["unit_price_cents"] > 0


def assert_device(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("asset_tag"), str) and data["asset_tag"]
    assert data.get("platform") in ("WINDOWS", "MACOS", "LINUX", "CHROMEOS", "ANDROID", "IOS")
    assert data.get("lifecycle_status") in ("ACTIVE", "RETIRED")


def assert_employee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("employee_ref"), str) and data["employee_ref"]
    assert isinstance(data.get("directory_user_id"), str) and data["directory_user_id"]
    assert data.get("employment_status") in ("ACTIVE", "TERMINATED")
    assert isinstance(data.get("identity_account_id"), str) and data["identity_account_id"]


def assert_identity_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("registered_key_count"), int) and data["registered_key_count"] >= 0
    assert isinstance(data.get("backup_compliant"), bool)
    assert data.get("status") in ("UNENROLLED", "ENROLLED", "LOCKED")


def assert_purchase_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("line_count"), int) and data["line_count"] >= 1
    assert isinstance(data.get("quoted_total_cents"), int) and data["quoted_total_cents"] > 0
    assert data.get("status") in (
        "PENDING_APPROVAL", "APPROVED", "IN_TRANSIT", "RECEIVED", "QUARANTINED",
    )
    assert isinstance(data.get("version"), int)


def assert_security_key(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("serial_number"), str) and data["serial_number"]
    assert data.get("hardware_status") in ("PRE_REGISTERED", "ASSIGNED", "DISTRIBUTED", "REVOKED")
    assert data.get("attestation_status") in ("UNVERIFIED", "VERIFIED", "FAILED")


def assert_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") in ("PENDING", "ACTIVE", "EXPIRING", "REVOKED", "SUPERSEDED")
    assert isinstance(data.get("renewal_count"), int)


def assert_temporary_access_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("method") in ("TOTP", "SMART_CARD", "SERVICE_DESK_TOKEN")
    assert data.get("status") in ("ACTIVE", "USED", "VOIDED", "EXPIRED")
    assert isinstance(data.get("duration_hours"), int)


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("tier") in ("BASIC", "ENTERPRISE")
    assert data.get("status") in ("ACTIVE", "EXHAUSTED", "EXPIRED")
    assert isinstance(data.get("credits_used"), int)
    assert isinstance(data.get("credits_remaining"), int)
    assert isinstance(data.get("coverage_cents_used"), int)
    assert isinstance(data.get("coverage_cents_remaining"), int)


def assert_help_desk_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("category") in ("LOST_KEY", "LOCKOUT", "OTHER")
    assert data.get("status") in ("OPEN", "PENDING_REVIEW", "RESOLVED", "REJECTED")


def assert_subscription_invariants(data: dict):
    """Subscription counter invariants that must hold after every mutation."""
    assert data["credits_used"] + data["credits_remaining"] == data["replacement_credits_total"]
    assert (
        data["coverage_cents_used"] + data["coverage_cents_remaining"]
        == data["coverage_cents_total"]
    )
