"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque operator X-User-ID never compared to
any entity id. The Member role is entity-backed: X-User-ID must be the acting
Member row's own id, so ownership-gated calls must be built with
make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

OFFICER_A_ID = "officer-A"
OFFICER_B_ID = "officer-B"
OFFICER_C_ID = "officer-C"

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "applicant_headers": build_user_headers("applicant-1", "EligibilityApplicant"),
    "officer_a_headers": build_user_headers(OFFICER_A_ID, "VerificationOfficer"),
    "officer_b_headers": build_user_headers(OFFICER_B_ID, "VerificationOfficer"),
    "officer_c_headers": build_user_headers(OFFICER_C_ID, "VerificationOfficer"),
    "benefits_officer_headers": build_user_headers("benefits-1", "BenefitsOfficer"),
    "product_admin_headers": build_user_headers("product-admin-1", "ProductAdministrator"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # Fallback only for tests that do not exercise Member ownership.
    "member_headers": build_user_headers("member-placeholder", "Member"),
}


def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity-backed): pass the acting Member row's id
    whenever the call is ownership-gated (any /membership/members/{memberId}
    route)."""
    return build_user_headers(member_id, "Member")


def make_officer_headers(user_id: str) -> dict:
    """VerificationOfficer headers for an arbitrary opaque officer id — used
    by segregation-of-duties scenarios that must control the officer id."""
    return build_user_headers(user_id, "VerificationOfficer")
