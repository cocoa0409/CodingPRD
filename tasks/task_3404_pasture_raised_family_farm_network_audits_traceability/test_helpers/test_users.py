"""Pre-built role headers for every role in the PRD (§2.1).

Five roles carry an opaque X-User-ID; RetailerBuyer is entity-backed — its
X-User-ID must equal the id of the RetailerAccount it acts for (PRD §2.1:
"When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting
`RetailerAccount`").
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. The retailer_buyer entry is a fallback for non-ownership use only.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "network_manager_headers": build_user_headers("test-network-manager-1", "NetworkManager"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "quality_manager_headers": build_user_headers("test-quality-manager-1", "QualityManager"),
    "plant_operator_headers": build_user_headers("test-plant-operator-1", "PlantOperator"),
    "retailer_buyer_headers": build_user_headers("test-retailer-buyer-1", "RetailerBuyer"),
}


def make_retailer_buyer_headers(user_id: str) -> dict:
    """For RetailerBuyer (entity-backed by RetailerAccount). Pass the actual
    RetailerAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "RetailerBuyer")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor identity is opaque, but the server records it as auditor_user_id
    on completed audits; segregation-of-duties tests need distinct auditor ids."""
    return build_user_headers(user_id, "Auditor")


def make_network_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_quality_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityManager")


def make_plant_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantOperator")
