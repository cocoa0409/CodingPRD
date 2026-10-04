"""Pre-built role headers for every role in the PRD.

The Driver role is entity-backed: its X-User-ID must equal the acting
Driver's id for ownership-gated calls. All other roles are opaque per the
PRD role descriptions.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS

# Shared constants — safe for opaque roles, and for tests that do not
# exercise Driver ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "telematics_ingest_headers": build_user_headers("test-ingest-1", "TelematicsIngest"),
    "safety_manager_headers": build_user_headers(
        TEST_DEFAULTS["REVIEWER_USER_ID"], "SafetyManager"
    ),
    "claims_adjuster_headers": build_user_headers(
        TEST_DEFAULTS["ADJUSTER_USER_ID"], "ClaimsAdjuster"
    ),
    "fleet_admin_headers": build_user_headers("test-fleetadmin-1", "FleetAdmin"),
    # Fallback only for Driver calls that are NOT ownership-gated.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_safety_manager_headers(user_id: str) -> dict:
    """SafetyManager headers with a specific opaque user id."""
    return build_user_headers(user_id, "SafetyManager")


def make_claims_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster headers with a specific opaque user id."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_driver_headers(user_id: str) -> dict:
    """Driver is entity-backed: pass the actual Driver.id whenever the call
    is ownership-gated (session acknowledge, exoneration claim submission)."""
    return build_user_headers(user_id, "Driver")
