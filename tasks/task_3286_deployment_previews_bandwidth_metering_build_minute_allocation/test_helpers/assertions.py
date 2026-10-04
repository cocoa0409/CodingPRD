"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DEPLOYMENT_STATUSES = [
    "QUEUED", "BUILDING", "READY", "STALE", "PROMOTED",
    "ROLLED_BACK", "ERROR", "CANCELED",
]
PROJECT_STATUSES = ["ACTIVE", "SUSPENDED", "ARCHIVED"]


def assert_team(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["plan_tier"], str) and len(data["plan_tier"]) > 0
    assert isinstance(data["seat_limit"], int)
    assert isinstance(data["seats_used"], int) and data["seats_used"] >= 0
    assert isinstance(data["prorated_charges_cents"], int)
    assert data["seats_used"] <= data["seat_limit"]


def assert_project(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in PROJECT_STATUSES
    assert data["preview_protection"] in ["NONE", "TEAM_ONLY"]


def assert_deployment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in DEPLOYMENT_STATUSES
    assert data["target"] in ["PREVIEW", "PRODUCTION"]
    assert isinstance(data["url_slug"], str) and len(data["url_slug"]) > 0
    assert data["url"] == data["url_slug"] + ".preview.example.com"


def assert_usage_period(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["OPEN", "CLOSED", "INVOICED"]
    assert isinstance(data["bandwidth_bytes"], int) and data["bandwidth_bytes"] >= 0
    assert isinstance(data["invocations"], int) and data["invocations"] >= 0
    assert isinstance(data["build_minutes_used"], int) and data["build_minutes_used"] >= 0
    assert isinstance(data["projected_bill_cents"], int) and data["projected_bill_cents"] >= 0


def assert_usage_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "UsageEvent is append-only and must not carry updated_at"
    assert "version" not in data, "UsageEvent is append-only and must not carry version"
    assert data["event_type"] in ["BANDWIDTH", "INVOCATION"]
    assert data["status"] in ["RECORDED", "ESTIMATED"]


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["user_email"], str) and len(data["user_email"]) > 0
    assert data["role"] in ["OWNER", "BILLING", "DEVELOPER", "VIEWER"]


def assert_domain(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["verification_status"] in ["PENDING", "VERIFIED", "FAILED"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_certificate(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ISSUING", "ACTIVE", "EXPIRED", "REVOKED"]


def assert_alert_rule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["metric"] in ["BANDWIDTH_BYTES", "INVOCATIONS", "BUILD_MINUTES", "SPEND_CENTS"]
    assert data["status"] in ["ACTIVE", "FIRED", "DISABLED"]
    assert isinstance(data["threshold_value"], int) and data["threshold_value"] > 0


def assert_spend_cap(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["action"] in ["ALERT_ONLY", "BLOCK_DEPLOYS_AND_SUSPEND"]
    assert data["status"] in ["ACTIVE", "TRIPPED", "DISABLED"]
    assert isinstance(data["cap_cents"], int) and data["cap_cents"] > 0
