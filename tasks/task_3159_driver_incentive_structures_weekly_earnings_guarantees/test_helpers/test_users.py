"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers — never compared to any entity id (PRD §2.1).
PLATFORM_ADMIN_USER = "admin-1"
INCENTIVE_OPS_USER = "ops-1"
PAYMENTS_OFFICER_USER = "pay-1"
FRAUD_ANALYST_USER = "fraud-1"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER, "PlatformAdmin"),
    "incentive_ops_headers": build_user_headers(INCENTIVE_OPS_USER, "IncentiveOps"),
    "payments_officer_headers": build_user_headers(PAYMENTS_OFFICER_USER, "PaymentsOfficer"),
    "fraud_analyst_headers": build_user_headers(FRAUD_ANALYST_USER, "FraudAnalyst"),
    # Driver is entity-backed: this fallback constant is only safe for tests that
    # never exercise an ownership check (e.g. role-denied requests).
    "driver_headers_unowned": build_user_headers("no-such-driver", "Driver"),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_incentive_ops_headers(user_id: str = INCENTIVE_OPS_USER) -> dict:
    return build_user_headers(user_id, "IncentiveOps")


def make_payments_officer_headers(user_id: str = PAYMENTS_OFFICER_USER) -> dict:
    return build_user_headers(user_id, "PaymentsOfficer")


def make_fraud_analyst_headers(user_id: str = FRAUD_ANALYST_USER) -> dict:
    return build_user_headers(user_id, "FraudAnalyst")


def make_driver_headers(driver_id: str) -> dict:
    """For Driver (entity-backed): X-User-ID must be the real Driver.id whenever
    the call is ownership-gated (rides, appeals, self-reads)."""
    return build_user_headers(driver_id, "Driver")
