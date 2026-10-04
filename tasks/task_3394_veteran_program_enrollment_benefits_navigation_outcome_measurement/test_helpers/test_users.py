"""Pre-built role headers for every role in the PRD (section 2.1).

Seven roles carry an opaque operator identifier; ProgramMember and
ClinicalPartner are entity-backed: their X-User-ID must equal the id of the
Member (resp. PartnerSite) they act as. Use the per-instance builders for any
ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "intake_coordinator_headers": build_user_headers("test-intake-coordinator-1", "IntakeCoordinator"),
    "accredited_representative_headers": build_user_headers("test-accredited-rep-1", "AccreditedRepresentative"),
    "benefits_officer_headers": build_user_headers("officer-a", "BenefitsOfficer"),
    "career_counselor_headers": build_user_headers("test-career-counselor-1", "CareerCounselor"),
    "event_coordinator_headers": build_user_headers("test-event-coordinator-1", "EventCoordinator"),
    "outcome_analyst_headers": build_user_headers("test-outcome-analyst-1", "OutcomeAnalyst"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "clinical_partner_headers": build_user_headers("test-clinical-partner-1", "ClinicalPartner"),
    "program_member_headers": build_user_headers("test-program-member-1", "ProgramMember"),
}


# ---- Opaque roles -------------------------------------------------------
def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_intake_coordinator_headers(user_id: str = "test-intake-coordinator-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_accredited_representative_headers(user_id: str = "test-accredited-rep-1") -> dict:
    return build_user_headers(user_id, "AccreditedRepresentative")


def make_benefits_officer_headers(user_id: str) -> dict:
    """The officer's X-User-ID is written to decided_by_officer_id and is later
    consulted by the segregation-of-duties rule — pass a distinct id per officer."""
    return build_user_headers(user_id, "BenefitsOfficer")


def make_career_counselor_headers(user_id: str = "test-career-counselor-1") -> dict:
    return build_user_headers(user_id, "CareerCounselor")


def make_event_coordinator_headers(user_id: str = "test-event-coordinator-1") -> dict:
    return build_user_headers(user_id, "EventCoordinator")


def make_outcome_analyst_headers(user_id: str = "test-outcome-analyst-1") -> dict:
    return build_user_headers(user_id, "OutcomeAnalyst")


# ---- Entity-backed roles (per-instance builders are the canonical form) --
def make_program_member_headers(user_id: str) -> dict:
    """For ProgramMember (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ProgramMember")


def make_clinical_partner_headers(user_id: str) -> dict:
    """For ClinicalPartner (entity_backed:PartnerSite). Pass the actual
    PartnerSite.id as user_id for referral ADMIT/DISCHARGE transitions."""
    return build_user_headers(user_id, "ClinicalPartner")
