"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "volunteer_editor_headers": build_user_headers("test-editor-1", "VolunteerEditor"),
    "administrator_headers": build_user_headers("test-admin-1", "Administrator"),
    "fundraising_manager_headers": build_user_headers("test-fm-1", "FundraisingManager"),
    "payment_processor_headers": build_user_headers("test-pp-1", "PaymentProcessor"),
    "grant_administrator_headers": build_user_headers("test-ga-1", "GrantAdministrator"),
    "grant_reviewer_headers": build_user_headers("test-gr-1", "GrantReviewer"),
    "legal_counsel_headers": build_user_headers("test-lc-1", "LegalCounsel"),
    "platform_admin_headers": build_user_headers("test-pa-1", "PlatformAdmin"),
}


def make_volunteer_editor_headers(user_id: str) -> dict:
    """For VolunteerEditor (entity_backed:VolunteerEditor). Pass the actual editor id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "VolunteerEditor")
