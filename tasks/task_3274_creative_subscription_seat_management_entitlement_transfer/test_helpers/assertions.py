"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer >= 1"


def assert_organization(data: dict):
    _assert_common_fields(data, "Organization")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("org_type") in ["INDIVIDUAL", "TEAM", "ENTERPRISE"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data.get("compliance_posture") in [
        "COMPLIANT", "OVER_ALLOCATED", "UNDER_AUDIT", "FROZEN"]


def assert_admin(data: dict):
    _assert_common_fields(data, "Admin")
    assert isinstance(data.get("email"), str) and data["email"]
    assert data.get("admin_kind") in ["SYSTEM_ADMIN", "PRODUCT_ADMIN", "DEPLOYMENT_ADMIN"]


def assert_end_user(data: dict):
    _assert_common_fields(data, "EndUser")
    assert isinstance(data.get("email"), str) and data["email"]
    assert data.get("status") in ["ACTIVE", "DEACTIVATED", "DEPARTED"]


def assert_reseller(data: dict):
    _assert_common_fields(data, "Reseller")
    assert data.get("region") in ["NA", "EMEA", "APAC", "LATAM"]
    assert data.get("tier") in ["CERTIFIED", "GOLD", "PLATINUM"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED"]


def assert_plan(data: dict):
    _assert_common_fields(data, "Plan")
    assert data.get("segment") in ["INDIVIDUAL", "TEAM", "ENTERPRISE"]
    assert data.get("billing_model") in ["MONTHLY", "ANNUAL_MONTHLY_BILLED", "ANNUAL_PREPAID"]
    assert isinstance(data.get("monthly_price_cents"), int)
    assert isinstance(data.get("seat_limit"), int) and data["seat_limit"] >= -1


def assert_subscription(data: dict):
    _assert_common_fields(data, "Subscription")
    assert data.get("status") in [
        "PENDING_PAYMENT", "ACTIVE", "PAST_DUE",
        "CANCELLED_IN_WINDOW", "CANCELLED_ETF", "EXPIRED"]
    assert isinstance(data.get("seats_purchased"), int) and data["seats_purchased"] >= 1
    assert isinstance(data.get("seats_assigned"), int)
    assert isinstance(data.get("monthly_charge_cents"), int)


def assert_seat(data: dict):
    _assert_common_fields(data, "Seat")
    assert data.get("status") in [
        "UNASSIGNED", "ASSIGNED", "PENDING_RECLAIM", "RECLAIMED", "TRANSFERRING"]


def assert_device(data: dict):
    _assert_common_fields(data, "Device")
    assert data.get("status") in ["ACTIVE", "DEACTIVATED"]


def assert_entitlement(data: dict):
    _assert_common_fields(data, "Entitlement")
    assert data.get("status") in [
        "PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "REVOKED"]


def assert_deployment_package(data: dict):
    _assert_common_fields(data, "DeploymentPackage")
    assert data.get("status") in [
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "PUBLISHED", "RETIRED", "REJECTED"]
    assert data.get("deployment_mode") in ["NAMED_USER", "SERIALIZED", "SHARED_DEVICE"]


def assert_product_version(data: dict):
    _assert_common_fields(data, "ProductVersion")
    assert data.get("availability") in ["AVAILABLE", "DEPRECATED", "FORCED_UPGRADE"]


def assert_add_on_service(data: dict):
    _assert_common_fields(data, "AddOnService")
    assert data.get("kind") in ["STOCK_CREDITS", "FONTS", "CLOUD_SERVICES"]
    assert data.get("status") in ["ACTIVE", "EXHAUSTED", "CANCELLED"]
    assert isinstance(data.get("quota_total"), int) and data["quota_total"] >= 1
    assert isinstance(data.get("quota_used"), int) and data["quota_used"] >= 0


def assert_asset(data: dict):
    _assert_common_fields(data, "Asset")
    assert data.get("status") in [
        "ACTIVE", "IN_TRANSFER", "TRANSFERRED", "ORPHANED", "PURGED"]
    assert isinstance(data.get("size_mb"), int) and data["size_mb"] >= 0


def assert_transfer_request(data: dict):
    _assert_common_fields(data, "TransferRequest")
    assert data.get("status") in [
        "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXECUTED", "EXPIRED"]


def assert_reseller_order(data: dict):
    _assert_common_fields(data, "ResellerOrder")
    assert data.get("status") in ["ROUTED", "FULFILLED", "CANCELLED", "REJECTED"]


def assert_compliance_audit(data: dict):
    _assert_common_fields(data, "ComplianceAudit")
    assert data.get("status") in ["OPEN", "FINDINGS_RAISED", "REMEDIATED", "CLOSED"]


def assert_cancellation_request(data: dict):
    _assert_common_fields(data, "CancellationRequest")
    assert data.get("status") in ["PENDING", "REFUNDED", "ETF_CHARGED", "DENIED"]


def assert_org_storage_pool_invariants(data: dict):
    """An organization's storage pool is never negative."""
    assert data.get("storage_pool_gb", 0) >= 0, "storage_pool_gb must be >= 0"


def assert_seat_count_invariants(subscription: dict):
    """Seats assigned never go negative."""
    assert subscription.get("seats_assigned", 0) >= 0, "seats_assigned must be >= 0"
