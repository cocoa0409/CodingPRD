"""Pre-built role headers for every role in the PRD (section 2.1).

Entity-backed roles (Publisher, Viewer, TvManufacturer) get a per-instance
builder so ownership-gated calls can thread the real entity id as X-User-ID.
The shared constants in TEST_USERS are safe only for tests that do not
exercise entity-backed ownership (e.g. bad-payload or missing-resource
probes) and for the two opaque roles.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles are canonical here; entity-backed entries
# are fallbacks for non-ownership tests only.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "adops_headers": build_user_headers("test-adops-1", "AdOps"),
    "publisher_headers": build_user_headers("test-publisher-1", "Publisher"),
    "viewer_headers": build_user_headers("test-viewer-1", "Viewer"),
    "manufacturer_headers": build_user_headers("test-mfr-1", "TvManufacturer"),
}


def make_publisher_headers(user_id: str) -> dict:
    """Publisher is entity-backed: pass the actual Publisher.id as user_id."""
    return build_user_headers(user_id, "Publisher")


def make_viewer_headers(user_id: str) -> dict:
    """Viewer is entity-backed: pass the actual ViewerAccount.id as user_id."""
    return build_user_headers(user_id, "Viewer")


def make_manufacturer_headers(user_id: str) -> dict:
    """TvManufacturer is entity-backed: pass the actual TvManufacturer.id."""
    return build_user_headers(user_id, "TvManufacturer")
