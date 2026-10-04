"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. ReferringPhysician is entity_backed by ReferralSource: for any
# ownership-gated call, use make_referring_physician_headers(source["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "NetworkAdmin"),
    "intake_headers": build_user_headers("ic-1", "IntakeCoordinator"),
    "reviewer1_headers": build_user_headers("rcm-1", "ReviewCommitteeMember"),
    "reviewer2_headers": build_user_headers("rcm-2", "ReviewCommitteeMember"),
    "reviewer3_headers": build_user_headers("rcm-3", "ReviewCommitteeMember"),
    "billing_headers": build_user_headers("bs-1", "BillingSpecialist"),
    "care_headers": build_user_headers("cc-1", "CareCoordinator"),
    "outreach_headers": build_user_headers("op-1", "OutreachPlanner"),
    "philanthropy_headers": build_user_headers("po-1", "PhilanthropyOfficer"),
    # Fallback for non-ownership tests only — X-User-ID here is NOT a real
    # ReferralSource id, so ownership-gated calls must use the builder below.
    "physician_headers": build_user_headers("test-physician-1", "ReferringPhysician"),
}


def make_referring_physician_headers(referral_source_id: str) -> dict:
    """For ReferringPhysician (entity_backed:ReferralSource). Pass the actual
    ReferralSource.id whenever the call is ownership-gated."""
    return build_user_headers(referral_source_id, "ReferringPhysician")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkAdmin")


def make_intake_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReviewCommitteeMember")


def make_billing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_care_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CareCoordinator")


def make_outreach_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OutreachPlanner")


def make_philanthropy_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PhilanthropyOfficer")
