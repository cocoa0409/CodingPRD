"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For RightsHolder (entity-backed by Artist) the shared constant is
# a fallback only; ownership-gated calls must use make_rights_holder_headers
# with the actual artist id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "rights_holder_headers": build_user_headers("test-rights-holder-1", "RightsHolder"),
    "playlist_editor_headers": build_user_headers("test-playlist-editor-1", "PlaylistEditor"),
    "editorial_lead_headers": build_user_headers("test-editorial-lead-1", "EditorialLead"),
    "fraud_analyst_headers": build_user_headers("test-fraud-analyst-1", "FraudAnalyst"),
}


def make_rights_holder_headers(artist_id: str) -> dict:
    """For RightsHolder (entity-backed by Artist): X-User-ID must equal the
    acting artist's id whenever the call is ownership-gated (release create,
    change-date, remove, track create, pitch submit/revise/withdraw, promotion
    enroll/suspend/resume/terminate, profile-module attach/disable, presave
    cancel)."""
    return build_user_headers(artist_id, "RightsHolder")
