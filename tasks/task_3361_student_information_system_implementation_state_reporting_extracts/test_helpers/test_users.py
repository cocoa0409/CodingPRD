"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the four opaque operator roles; safe for any call whose
# success does not depend on the caller owning a subject resource (PRD §2.1).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "district_admin_headers": build_user_headers("test-district-admin-1", "DistrictAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "state_reporter_headers": build_user_headers("test-state-reporter-1", "StateReporter"),
    # Fallback for PortalUser tests that do not exercise ownership (e.g. role denial).
    "portal_user_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000001", "PortalUser"),
}


def make_portal_user_headers(user_id: str) -> dict:
    """PortalUser is entity-backed by PortalAccount (PRD §2.1): the X-User-ID must
    equal the id of the PortalAccount being read for ownership-gated calls."""
    return build_user_headers(user_id, "PortalUser")
