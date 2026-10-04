"""Pre-built role headers for every role the platform declares.

LenderOfficer and ServicerOfficer are entity-backed roles: their X-User-ID must
equal the id of the Lender they act for. The shared constants for those roles
are fallbacks for tests that exercise no ownership comparison (e.g. 400/404
probes); every ownership-gated call MUST go through the per-instance builders
with the real Lender.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Named opaque operator identities (rules record X-User-ID verbatim).
ADMIN_ID = "admin-1"
REVIEWER_ALPHA_ID = "rev-alpha"
REVIEWER_BETA_ID = "rev-beta"
REVIEWER_GAMMA_ID = "rev-gamma"
APPROVER_BETA_ID = "appr-beta"
EXAMINER_ID = "cx-1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers(ADMIN_ID, "PlatformAdmin"),
    "fha_reviewer_headers": build_user_headers(REVIEWER_ALPHA_ID, "FhaReviewer"),
    "fha_approver_headers": build_user_headers(APPROVER_BETA_ID, "FhaApprover"),
    "claims_examiner_headers": build_user_headers(EXAMINER_ID, "ClaimsExaminer"),
    # Entity-backed roles: fallback only for non-ownership probes.
    "lender_officer_headers": build_user_headers("test-lender-officer-fallback", "LenderOfficer"),
    "servicer_officer_headers": build_user_headers("test-servicer-officer-fallback", "ServicerOfficer"),
}


def make_lender_officer_headers(lender_id: str) -> dict:
    """Headers for the LenderOfficer of the lender identified by lender_id."""
    return build_user_headers(lender_id, "LenderOfficer")


def make_servicer_officer_headers(lender_id: str) -> dict:
    """Headers for the ServicerOfficer of the lender identified by lender_id."""
    return build_user_headers(lender_id, "ServicerOfficer")


def make_reviewer_headers(user_id: str = REVIEWER_ALPHA_ID) -> dict:
    return build_user_headers(user_id, "FhaReviewer")


def make_approver_headers(user_id: str = APPROVER_BETA_ID) -> dict:
    return build_user_headers(user_id, "FhaApprover")


def make_examiner_headers(user_id: str = EXAMINER_ID) -> dict:
    return build_user_headers(user_id, "ClaimsExaminer")


def make_admin_headers(user_id: str = ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def anonymous_headers() -> dict:
    """No auth context at all — for priority-1 refusal probes."""
    return {"Content-Type": "application/json"}


def unknown_role_headers() -> dict:
    """A role outside the declared catalog — for priority-1 refusal probes."""
    return build_user_headers("test-intruder-1", "SuperUser")
