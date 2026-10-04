"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership gating (e.g., 400-on-bad-payload or 404-on-missing-resource tests).
TEST_USERS = {
    # PlatformAdmin is opaque: X-User-ID is not tied to any persisted entity.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Parent / SchoolAdmin / DeviceAgent are entity-backed: these shared constants
    # are fallbacks ONLY for tests whose outcome does not depend on ownership.
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
    "school_admin_headers": build_user_headers("test-school-admin-1", "SchoolAdmin"),
    "device_agent_headers": build_user_headers("test-device-agent-1", "DeviceAgent"),
}


def make_parent_headers(parent_member_id: str) -> dict:
    """For Parent (entity_backed:ParentMember). Pass the actual ParentMember.id
    whenever the call is ownership-gated."""
    return build_user_headers(parent_member_id, "Parent")


def make_school_admin_headers(district_id: str) -> dict:
    """For SchoolAdmin (entity_backed:District). Pass the actual District.id."""
    return build_user_headers(district_id, "SchoolAdmin")


def make_device_agent_headers(device_id: str) -> dict:
    """For DeviceAgent (entity_backed:Device). Pass the actual Device.id."""
    return build_user_headers(device_id, "DeviceAgent")
