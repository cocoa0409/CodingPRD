"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# the Rider/Driver ownership checks.
TEST_USERS = {
    "admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "investigator_headers": build_user_headers("op-investigator-1", "SafetyInvestigator"),
    "appeal_reviewer_headers": build_user_headers("op-appeal-1", "SafetyAppealReviewer"),
    "operations_lead_headers": build_user_headers("op-operations-1", "SafetyOperationsLead"),
    "liaison_headers": build_user_headers("op-liaison-1", "RegulatorLiaison"),
    "background_reviewer_headers": build_user_headers("op-background-1", "BackgroundReviewer"),
    # entity_backed roles: the shared constants are fallbacks for calls that are
    # not ownership-gated (missing-resource and 401/403 probes).
    "rider_headers": build_user_headers("op-rider-1", "Rider"),
    "driver_headers": build_user_headers("op-driver-1", "Driver"),
}

# Named operator identities that specific scenarios depend on: the appeal
# reviewer must never equal the deciding investigator.
APPEAL_REVIEWER_PRIYA = "ar-priya"
APPEAL_REVIEWER_QUINN = "ar-quinn"
APPEAL_REVIEWER_ROWAN = "ar-rowan"


# --- Per-instance builders --------------------------------------------------
# Rider and Driver are entity-backed: X-User-ID is the acting Account's id, and
# every ownership-gated call must thread the real entity id through here.

def make_rider_headers(user_id: str) -> dict:
    """For Rider (entity-backed on Account). Pass the acting Account.id."""
    return build_user_headers(user_id, "Rider")


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity-backed on Account). Pass the acting Account.id."""
    return build_user_headers(user_id, "Driver")


def make_appeal_reviewer_headers(user_id: str) -> dict:
    """Appeal reviewer identity, for separation-of-duties scenarios."""
    return build_user_headers(user_id, "SafetyAppealReviewer")


def make_investigator_headers(user_id: str) -> dict:
    """Investigator identity, for separation-of-duties scenarios."""
    return build_user_headers(user_id, "SafetyInvestigator")


def make_operations_lead_headers(user_id: str) -> dict:
    """Operations lead identity."""
    return build_user_headers(user_id, "SafetyOperationsLead")