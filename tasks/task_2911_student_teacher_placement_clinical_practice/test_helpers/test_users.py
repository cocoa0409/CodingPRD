"""Identity headers for every role in the contract.

Five roles are opaque operator identities: the user id is an arbitrary
identifier the server only echoes back into audit fields.  Two roles are
entity backed — a UniversitySupervisorUser's user id must be the id of the
UniversitySupervisor row, and a CandidateUser's user id must be the id of the
Candidate row — so those two get per-instance builders that thread a real
entity id into the header.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Opaque operator identities ───────────────────────
PROGRAM_ADMIN_USER_ID = "u-admin-1"
SECOND_PROGRAM_ADMIN_USER_ID = "u-admin-2"
PLACEMENT_COORDINATOR_USER_ID = "u-coord-1"
SECOND_PLACEMENT_COORDINATOR_USER_ID = "u-coord-2"
CREDENTIAL_ANALYST_USER_ID = "u-cred-1"
SUPERVISION_LEAD_USER_ID = "u-suplead-1"
ASSESSMENT_SCORER_USER_ID = "u-scorer-1"
SECOND_ASSESSMENT_SCORER_USER_ID = "u-scorer-2"

# A single natural person holding two roles at once, used to exercise the
# segregation-of-duties rule that keys on user id rather than on role.
DUAL_ROLE_USER_ID = "u-staff-77"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": build_user_headers(PROGRAM_ADMIN_USER_ID,
                                       UserRole.PROGRAM_ADMIN.value),
    "program_admin_2": build_user_headers(SECOND_PROGRAM_ADMIN_USER_ID,
                                         UserRole.PROGRAM_ADMIN.value),
    "placement_coordinator": build_user_headers(PLACEMENT_COORDINATOR_USER_ID,
                                               UserRole.PLACEMENT_COORDINATOR.value),
    "placement_coordinator_2": build_user_headers(
        SECOND_PLACEMENT_COORDINATOR_USER_ID,
        UserRole.PLACEMENT_COORDINATOR.value),
    "credential_analyst": build_user_headers(CREDENTIAL_ANALYST_USER_ID,
                                             UserRole.CREDENTIAL_ANALYST.value),
    "supervision_lead": build_user_headers(SUPERVISION_LEAD_USER_ID,
                                           UserRole.SUPERVISION_LEAD.value),
    "assessment_scorer": build_user_headers(ASSESSMENT_SCORER_USER_ID,
                                            UserRole.ASSESSMENT_SCORER.value),
    "assessment_scorer_2": build_user_headers(SECOND_ASSESSMENT_SCORER_USER_ID,
                                              UserRole.ASSESSMENT_SCORER.value),
}

PROGRAM_ADMIN = TEST_USERS["program_admin"]
PROGRAM_ADMIN_2 = TEST_USERS["program_admin_2"]
PLACEMENT_COORDINATOR = TEST_USERS["placement_coordinator"]
PLACEMENT_COORDINATOR_2 = TEST_USERS["placement_coordinator_2"]
CREDENTIAL_ANALYST = TEST_USERS["credential_analyst"]
SUPERVISION_LEAD = TEST_USERS["supervision_lead"]
ASSESSMENT_SCORER = TEST_USERS["assessment_scorer"]
ASSESSMENT_SCORER_2 = TEST_USERS["assessment_scorer_2"]

ALL_OPERATOR_ROLES = [
    UserRole.PROGRAM_ADMIN.value,
    UserRole.PLACEMENT_COORDINATOR.value,
    UserRole.CREDENTIAL_ANALYST.value,
    UserRole.SUPERVISION_LEAD.value,
    UserRole.ASSESSMENT_SCORER.value,
]


# ─── Entity-backed identity builders ──────────────────

def make_university_supervisor_headers(supervisor_id: str) -> Dict[str, str]:
    """Headers for a UniversitySupervisorUser bound to that supervisor row."""
    return build_user_headers(supervisor_id, UserRole.UNIVERSITY_SUPERVISOR_USER.value)


def make_candidate_headers(candidate_id: str) -> Dict[str, str]:
    """Headers for a CandidateUser bound to that candidate row."""
    return build_user_headers(candidate_id, UserRole.CANDIDATE_USER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pairing."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, entity_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for any role; entity-backed roles require the owning entity id."""
    if role == UserRole.UNIVERSITY_SUPERVISOR_USER.value:
        assert entity_id is not None, "UniversitySupervisorUser needs a supervisor id"
        return make_university_supervisor_headers(entity_id)
    if role == UserRole.CANDIDATE_USER.value:
        assert entity_id is not None, "CandidateUser needs a candidate id"
        return make_candidate_headers(entity_id)
    ids = {
        UserRole.PROGRAM_ADMIN.value: PROGRAM_ADMIN_USER_ID,
        UserRole.PLACEMENT_COORDINATOR.value: PLACEMENT_COORDINATOR_USER_ID,
        UserRole.CREDENTIAL_ANALYST.value: CREDENTIAL_ANALYST_USER_ID,
        UserRole.SUPERVISION_LEAD.value: SUPERVISION_LEAD_USER_ID,
        UserRole.ASSESSMENT_SCORER.value: ASSESSMENT_SCORER_USER_ID,
    }
    return build_user_headers(ids[role], role)


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
"""Headers carrying no identity at all."""


def blank_identity_headers() -> Dict[str, str]:
    """Identity headers present but empty — an empty string, not whitespace."""
    return {
        "X-User-ID": "",
        "X-User-Role": "",
        "Content-Type": "application/json",
    }
