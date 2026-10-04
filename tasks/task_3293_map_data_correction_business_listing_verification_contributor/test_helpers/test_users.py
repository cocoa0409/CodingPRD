"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Entity-backed roles (Contributor, BusinessOwner) MUST use the
# per-instance builders below whenever the call is ownership-gated.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "contributor_headers": build_user_headers("test-contributor-1", "Contributor"),
    "business_owner_headers": build_user_headers("test-owner-1", "BusinessOwner"),
    "moderator_headers": build_user_headers("mod-1", "Moderator"),
    "moderator2_headers": build_user_headers("mod-2", "Moderator"),
    "policy_analyst_headers": build_user_headers("pa-1", "PolicyAnalyst"),
    "policy_analyst2_headers": build_user_headers("pa-2", "PolicyAnalyst"),
    "policy_analyst3_headers": build_user_headers("pa-3", "PolicyAnalyst"),
    "imagery_operator_headers": build_user_headers("op-1", "ImageryOperator"),
    "imagery_operator2_headers": build_user_headers("op-2", "ImageryOperator"),
    "routing_engineer_headers": build_user_headers("re-1", "RoutingEngineer"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_contributor_headers(user_id: str) -> dict:
    """For Contributor (entity_backed:Contributor). Pass the actual
    Contributor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Contributor")


def make_business_owner_headers(user_id: str) -> dict:
    """For BusinessOwner (entity_backed:Contributor). Pass the actual owning
    Contributor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "BusinessOwner")


def make_moderator_headers(user_id: str) -> dict:
    """Moderator is opaque, but distinct moderator identities matter for
    ticket-claim segregation; this builder makes intent explicit."""
    return build_user_headers(user_id, "Moderator")


def make_policy_analyst_headers(user_id: str) -> dict:
    """PolicyAnalyst is opaque, but distinct analyst identities matter for
    appeal segregation of duties; this builder makes intent explicit."""
    return build_user_headers(user_id, "PolicyAnalyst")
