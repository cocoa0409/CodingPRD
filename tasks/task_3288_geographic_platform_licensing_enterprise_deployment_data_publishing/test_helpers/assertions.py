"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity_label}.version must be an int >= 1"


def assert_organization(data: dict):
    _assert_common(data, "Organization")
    assert data["status"] in ("PROVISIONING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["org_kind"] in ("COMMERCIAL", "EDUCATION", "NONPROFIT")
    assert isinstance(data["credit_balance"], int)
    assert isinstance(data["seat_overage_fee_accrued_cents"], int)
    assert isinstance(data["current_period_index"], int)


def assert_credit_pool(data: dict):
    _assert_common(data, "CreditPool")
    assert data["posture"] in ("OK", "LOW_CREDIT", "EXHAUSTED", "OVERDRAWN")
    assert isinstance(data["capacity_credits"], int)
    assert isinstance(data["reserved_credits"], int)
    assert isinstance(data["consumed_credits"], int)


def assert_license_grant(data: dict):
    _assert_common(data, "LicenseGrant")
    assert data["status"] in ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED")
    assert data["grant_kind"] in ("STANDARD", "EDUCATION_PROGRAM", "NONPROFIT_PROGRAM")
    assert isinstance(data["seats_allocated"], int)
    assert isinstance(data["seats_in_use"], int)


def assert_named_user(data: dict):
    _assert_common(data, "NamedUser")
    assert data["status"] in ("INVITED", "ACTIVE", "DISABLED", "DEACTIVATED")
    assert data["named_user_level"] in (
        "VIEWER", "EDITOR", "FIELD_WORKER", "CREATOR", "PROFESSIONAL", "PROFESSIONAL_PLUS",
    )


def assert_content_item(data: dict):
    _assert_common(data, "ContentItem")
    assert data["status"] in ("DRAFT", "PUBLISHED", "FLAGGED", "RETRACTED")
    assert data["sharing_level"] in ("PRIVATE", "ORGANIZATION", "PUBLIC")
    assert data["item_kind"] in (
        "FEATURE_LAYER", "TILE_LAYER", "BASEMAP", "WEB_MAP", "NOTEBOOK", "API_APP",
    )


def assert_credit_batch(data: dict):
    _assert_common(data, "CreditBatch")
    assert data["status"] in ("PENDING", "SETTLED", "REVERSED")
    assert data["service_kind"] in ("GEOCODE", "ANALYSIS", "STORAGE", "TILE_QUERY", "ROUTING")


def assert_deployment_server(data: dict):
    _assert_common(data, "DeploymentServer")
    assert data["status"] in ("REGISTERED", "AUTHORIZED", "UPGRADING", "DECOMMISSIONED")
    assert data["role"] in ("GIS_SERVER", "PORTAL", "DATA_STORE", "NOTEBOOK_SERVER")


def assert_api_key(data: dict):
    _assert_common(data, "ApiKey")
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["credits_consumed"], int)


def assert_eligibility_verification(data: dict):
    _assert_common(data, "EligibilityVerification")
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "RENEWAL_REQUIRED")
    assert data["program_kind"] in ("EDUCATION_PROGRAM", "NONPROFIT_PROGRAM")


def assert_pool_invariants(pool: dict, org: dict):
    """The pool's available credits always mirror the org's credit_balance."""
    available = pool["capacity_credits"] - pool["consumed_credits"] - pool["reserved_credits"]
    assert org["credit_balance"] == available, (
        f"credit_balance {org['credit_balance']} != capacity {pool['capacity_credits']} "
        f"- consumed {pool['consumed_credits']} - reserved {pool['reserved_credits']}"
    )
    if available < 0:
        expected = "OVERDRAWN"
    elif available == 0:
        expected = "EXHAUSTED"
    elif available < pool["low_credit_threshold_credits"]:
        expected = "LOW_CREDIT"
    else:
        expected = "OK"
    assert pool["posture"] == expected, f"posture {pool['posture']} != expected {expected} at available {available}"
