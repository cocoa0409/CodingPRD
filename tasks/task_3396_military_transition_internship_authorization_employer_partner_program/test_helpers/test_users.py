"""Pre-built role headers for every role in the PRD (§2.1, §4).

Opaque roles (ProgramOffice, TransitionCounselor, UnitCommander,
InstallationAuthority) carry an operator identifier not tied to any entity,
so shared constants are safe for them. Entity-backed roles (ServiceMember,
EmployerRep) bind ``X-User-ID`` to a real entity id - use the per-instance
builders with the actual entity's id whenever the call is ownership-gated.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_office_headers": build_user_headers("po-1", "ProgramOffice"),
    "transition_counselor_headers": build_user_headers("tc-1", "TransitionCounselor"),
    "unit_commander_headers": build_user_headers("cmd-1", "UnitCommander"),
    "installation_authority_headers": build_user_headers("auth-1", "InstallationAuthority"),
    # Fallbacks for non-ownership tests only. Never use these when the call
    # is ownership-gated: the id below equals no real entity's id.
    "service_member_headers": build_user_headers("test-member-1", "ServiceMember"),
    "employer_rep_headers": build_user_headers("test-employer-1", "EmployerRep"),
}

PROGRAM_OFFICE_HEADERS = TEST_USERS["program_office_headers"]
TRANSITION_COUNSELOR_HEADERS = TEST_USERS["transition_counselor_headers"]
UNIT_COMMANDER_HEADERS = TEST_USERS["unit_commander_headers"]
INSTALLATION_AUTHORITY_HEADERS = TEST_USERS["installation_authority_headers"]


def make_program_office_headers(user_id: str = "po-1") -> dict:
    return build_user_headers(user_id, "ProgramOffice")


def make_transition_counselor_headers(user_id: str = "tc-1") -> dict:
    return build_user_headers(user_id, "TransitionCounselor")


def make_unit_commander_headers(user_id: str = "cmd-1") -> dict:
    return build_user_headers(user_id, "UnitCommander")


def make_installation_authority_headers(user_id: str = "auth-1") -> dict:
    return build_user_headers(user_id, "InstallationAuthority")


def make_service_member_headers(user_id: str) -> dict:
    """ServiceMember is entity-backed: pass the acting member's id."""
    return build_user_headers(user_id, "ServiceMember")


def make_employer_rep_headers(user_id: str) -> dict:
    """EmployerRep is entity-backed: pass the acting employer's id."""
    return build_user_headers(user_id, "EmployerRep")
