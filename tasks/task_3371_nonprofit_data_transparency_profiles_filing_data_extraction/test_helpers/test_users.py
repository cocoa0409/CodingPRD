"""Pre-built role headers for every role in the PRD (PRD §2.1).

``OrganizationUser`` and ``DataConsumer`` are entity-backed roles: their
``X-User-ID`` is the acting organization's own ``id``, so any ownership-gated
call must use the per-instance builders below with the real entity id.
``PlatformVerifier`` and ``PlatformAdmin`` are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared opaque operator identities used by the recipes.
ADMIN_USER_ID = "admin-root"
VERIFIER_USER_ID = "ver-dana"
# A second, distinct verifier identity for segregation-of-duties scenarios.
VERIFIER_USER_ID_2 = "ver-omar"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "verifier_headers": build_user_headers(VERIFIER_USER_ID, "PlatformVerifier"),
    "verifier2_headers": build_user_headers(VERIFIER_USER_ID_2, "PlatformVerifier"),
    # Entity-backed roles — these constants are fallbacks for calls whose
    # outcome does not depend on ownership; prefer the builders below.
    "organization_user_headers": build_user_headers("unbound-organization-user", "OrganizationUser"),
    "data_consumer_headers": build_user_headers("unbound-data-consumer", "DataConsumer"),
}


def make_organization_user_headers(organization_id: str) -> dict:
    """For OrganizationUser (entity_backed:Organization).

    Pass the acting organization's own ``id``; the server compares it to the
    resource's owning organization on every ownership-gated call.
    """
    return build_user_headers(organization_id, "OrganizationUser")


def make_data_consumer_headers(organization_id: str) -> dict:
    """For DataConsumer (entity_backed:Organization).

    Pass the licensee/funder organization's own ``id``.
    """
    return build_user_headers(organization_id, "DataConsumer")


def make_verifier_headers(user_id: str = VERIFIER_USER_ID) -> dict:
    """PlatformVerifier is opaque; any operator id is acceptable."""
    return build_user_headers(user_id, "PlatformVerifier")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """PlatformAdmin is opaque; any operator id is acceptable."""
    return build_user_headers(user_id, "PlatformAdmin")


def anonymous_headers() -> dict:
    """No identity headers at all — used for the unauthenticated case."""
    return {}
