"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for opaque roles — safe in any context.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "compliance_headers": build_user_headers("compliance-1", "ExchangeComplianceOfficer"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """PlatformAdmin is an opaque role."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_headers(user_id: str = "compliance-1") -> dict:
    """ExchangeComplianceOfficer is an opaque role."""
    return build_user_headers(user_id, "ExchangeComplianceOfficer")


def make_data_steward_headers(carrier_id: str) -> dict:
    """CarrierDataSteward is entity-backed by Carrier: X-User-ID is the carrier id."""
    return build_user_headers(carrier_id, "CarrierDataSteward")


def make_underwriter_headers(carrier_id: str) -> dict:
    """CarrierUnderwriter is entity-backed by Carrier: X-User-ID is the carrier id."""
    return build_user_headers(carrier_id, "CarrierUnderwriter")


def make_consumer_headers(consumer_id: str) -> dict:
    """Consumer is entity-backed by Consumer: X-User-ID is the consumer id."""
    return build_user_headers(consumer_id, "Consumer")
