"""Pre-built role headers for every role in the PRD (§2.1).

ClientUser is entity-backed: X-User-ID is the acting Client's id. Any
ownership-gated call MUST use make_client_user_headers(client["id"]) with the
real Client id; the shared constant is a fallback for non-ownership tests.
Opaque roles carry operator ids; the methodology pinner / awards officer ids
matter for the segregation-of-duties rule (PRD §3.5).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import U_AWARDS_OFFICER, U_METHODOLOGY_LEAD

TEST_USERS = {
    "study_admin_headers": build_user_headers("u_admin_001", "StudyAdmin"),
    "methodology_lead_headers": build_user_headers(U_METHODOLOGY_LEAD, "MethodologyLead"),
    "field_ops_headers": build_user_headers("u_fo_001", "FieldOps"),
    "awards_officer_headers": build_user_headers(U_AWARDS_OFFICER, "AwardsOfficer"),
    "licensing_manager_headers": build_user_headers("u_lm_001", "LicensingManager"),
    "press_user_headers": build_user_headers("u_press_001", "PressUser"),
    # Fallback only — never use for ownership-gated calls.
    "client_user_headers": build_user_headers("test-client-user-1", "ClientUser"),
}


def make_client_user_headers(user_id: str) -> dict:
    """ClientUser is entity_backed:Client — pass the actual Client.id."""
    return build_user_headers(user_id, "ClientUser")


def make_study_admin_headers(user_id: str = "u_admin_001") -> dict:
    return build_user_headers(user_id, "StudyAdmin")


def make_methodology_lead_headers(user_id: str = U_METHODOLOGY_LEAD) -> dict:
    return build_user_headers(user_id, "MethodologyLead")


def make_field_ops_headers(user_id: str = "u_fo_001") -> dict:
    return build_user_headers(user_id, "FieldOps")


def make_awards_officer_headers(user_id: str = U_AWARDS_OFFICER) -> dict:
    return build_user_headers(user_id, "AwardsOfficer")


def make_licensing_manager_headers(user_id: str = "u_lm_001") -> dict:
    return build_user_headers(user_id, "LicensingManager")


def make_press_user_headers(user_id: str = "u_press_001") -> dict:
    return build_user_headers(user_id, "PressUser")
