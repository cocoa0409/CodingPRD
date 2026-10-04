"""Pre-built role headers for every role the PRD declares (PRD §2.1).

``EnrollmentOps``, ``ClinicalOps``, ``BillingOps``, ``EligibilityService``,
``OutreachService`` and ``ClinicalReviewService`` identify with opaque operator
or service identifiers, so the shared constants below are their canonical form.

``Clinician`` and ``Member`` are the two entity-backed roles: for those, the
shared constants are usable only by tests whose success does not depend on the
caller owning the subject resource. Any ownership-gated call must go through
the per-instance builders below, passing the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the six opaque roles; fallback-only for the
# two entity-backed roles.
TEST_USERS = {
    "enrollment_ops_headers": build_user_headers("test-enrollment-ops-1", "EnrollmentOps"),
    "clinical_ops_headers": build_user_headers("test-clinical-ops-1", "ClinicalOps"),
    "billing_ops_headers": build_user_headers("test-billing-ops-1", "BillingOps"),
    "eligibility_service_headers": build_user_headers("test-eligibility-service-1", "EligibilityService"),
    "outreach_service_headers": build_user_headers("test-outreach-service-1", "OutreachService"),
    "clinical_review_service_headers": build_user_headers(
        "test-clinical-review-service-1", "ClinicalReviewService"
    ),
    # entity_backed:Clinician — fallback for non-ownership tests only.
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    # entity_backed:Member — fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


# ─── Per-instance builders (required for entity-backed roles) ─────────
def make_clinician_headers(clinician_id: str) -> dict:
    """For Clinician (entity_backed:Clinician). Pass the actual Clinician.id
    whenever the call is ownership-gated (conducting a review, approving or
    denying a handoff, completing a handoff)."""
    return build_user_headers(clinician_id, "Clinician")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id whenever the
    call is ownership-gated (completing a session, recording a measurement)."""
    return build_user_headers(member_id, "Member")