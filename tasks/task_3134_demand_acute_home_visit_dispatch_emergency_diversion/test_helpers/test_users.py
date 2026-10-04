"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# All nine roles have an opaque identity in this domain (the PRD states
# X-User-ID is an opaque operator identifier for every role), so shared
# constants are the canonical form. For ownership-gated calls (dispatch
# accept/reject/arrive, diagnostic collect/result/amend, verify), use the
# per-instance builders below so the X-User-ID matches the team roster entry.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "triage_nurse_headers": build_user_headers("test-nurse-1", "TriageNurse"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "care_team_member_headers": build_user_headers("test-ctm-1", "CareTeamMember"),
    "app_headers": build_user_headers("test-app-1", "AdvancedPracticeProvider"),
    "field_technician_headers": build_user_headers("test-tech-1", "FieldTechnician"),
    "supervising_physician_headers": build_user_headers(
        "test-md-1", "SupervisingPhysician"
    ),
    "billing_specialist_headers": build_user_headers(
        "test-billing-1", "BillingSpecialist"
    ),
    "payer_adjudicator_headers": build_user_headers(
        "test-adjudicator-1", "PayerAdjudicator"
    ),
}


def make_care_team_member_headers(user_id: str) -> dict:
    """For dispatch accept/reject/arrive: X-User-ID must equal the assigned
    CareTeam's app_user_id or tech_user_id."""
    return build_user_headers(user_id, "CareTeamMember")


def make_field_technician_headers(user_id: str) -> dict:
    """For collect/result/amend: the actor identity is compared for the
    segregation-of-duties rule on verify."""
    return build_user_headers(user_id, "FieldTechnician")


def make_supervising_physician_headers(user_id: str) -> dict:
    """For verify and pre-authorization: X-User-ID is compared against the
    team's supervising_physician_user_id and the result actor's id."""
    return build_user_headers(user_id, "SupervisingPhysician")


def make_app_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdvancedPracticeProvider")
