"""Pre-built role headers for every role in the PRD (§2.1).

Viewer is entity-backed: ownership checks compare X-User-ID against the
Viewer.id, so viewer calls that exercise ownership MUST use
make_viewer_headers(viewer["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "rights_manager_headers": build_user_headers("test-rights-manager-1", "RightsManager"),
    "ad_ops_headers": build_user_headers("test-ad-ops-1", "AdOps"),
    "stream_ops_headers": build_user_headers("test-stream-ops-1", "StreamOps"),
    "partner_manager_headers": build_user_headers("test-partner-manager-1", "PartnerManager"),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. viewer self-registration, where no Viewer exists yet).
    "viewer_headers": build_user_headers("test-viewer-1", "Viewer"),
}


def make_viewer_headers(viewer_id: str) -> dict:
    """For the entity-backed Viewer role. Pass the actual Viewer.id as
    viewer_id whenever the call is ownership-gated (view grants, promo
    redemption, self-cancel, own-record reads)."""
    return build_user_headers(viewer_id, "Viewer")


def anonymous_headers() -> dict:
    """No auth headers at all (PRD §2.1: missing headers -> 401)."""
    return {}
