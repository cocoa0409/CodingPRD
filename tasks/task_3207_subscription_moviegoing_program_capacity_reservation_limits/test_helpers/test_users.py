"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "member_services_headers": build_user_headers("test-member-services-1", "MemberServices"),
    "theater_staff_headers": build_user_headers("test-theater-staff-1", "TheaterStaff"),
    "studio_rep_headers": build_user_headers("test-studio-rep-1", "StudioRep"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_member_services_headers(user_id: str = "test-member-services-1") -> dict:
    return build_user_headers(user_id, "MemberServices")


def make_theater_staff_headers(user_id: str = "test-theater-staff-1") -> dict:
    return build_user_headers(user_id, "TheaterStaff")


def make_studio_rep_headers(user_id: str = "test-studio-rep-1") -> dict:
    return build_user_headers(user_id, "StudioRep")
