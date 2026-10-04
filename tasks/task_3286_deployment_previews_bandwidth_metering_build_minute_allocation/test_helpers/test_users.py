"""Pre-built role headers for every role in the PRD (§2.1).

TeamOwner / TeamBillingManager / Developer / Viewer are entity-backed roles:
their X-User-ID is the id of the acting Member row. For calls whose success
does not depend on the caller owning the subject resource the shared
constants below are sufficient; fixtures that create real Member rows should
use the make_*_headers builders with the actual member id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "system_webhook_headers": build_user_headers("test-system-webhook-1", "SystemWebhook"),
    # Entity-backed roles: shared constants for non-ownership-gated calls.
    "team_owner_headers": build_user_headers("test-team-owner-1", "TeamOwner"),
    "team_billing_manager_headers": build_user_headers("test-billing-manager-1", "TeamBillingManager"),
    "developer_headers": build_user_headers("test-developer-1", "Developer"),
    "viewer_headers": build_user_headers("test-viewer-1", "Viewer"),
}


def make_team_owner_headers(user_id: str) -> dict:
    """TeamOwner headers bound to a concrete Member id (entity-backed role)."""
    return build_user_headers(user_id, "TeamOwner")


def make_team_billing_manager_headers(user_id: str) -> dict:
    """TeamBillingManager headers bound to a concrete Member id."""
    return build_user_headers(user_id, "TeamBillingManager")


def make_developer_headers(user_id: str) -> dict:
    """Developer headers bound to a concrete Member id."""
    return build_user_headers(user_id, "Developer")


def make_viewer_headers(user_id: str) -> dict:
    """Viewer headers bound to a concrete Member id."""
    return build_user_headers(user_id, "Viewer")
