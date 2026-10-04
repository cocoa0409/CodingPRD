"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "program_director_headers": build_user_headers("test-program-director-1", "ProgramDirector"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "placement_officer_headers": build_user_headers("test-placement-officer-1", "PlacementOfficer"),
    "casting_director_headers": build_user_headers("test-casting-director-1", "CastingDirector"),
    "finance_officer_headers": build_user_headers("test-finance-officer-1", "FinanceOfficer"),
    # Student role is entity_backed:Student; the shared constant is a fallback only
    # for tests that do not exercise ownership-gated calls.
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_student_headers(user_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Student")


def make_program_director_headers(user_id: str = "test-program-director-1") -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_registrar_headers(user_id: str = "test-registrar-1") -> dict:
    return build_user_headers(user_id, "Registrar")


def make_placement_officer_headers(user_id: str = "test-placement-officer-1") -> dict:
    return build_user_headers(user_id, "PlacementOfficer")


def make_casting_director_headers(user_id: str = "test-casting-director-1") -> dict:
    return build_user_headers(user_id, "CastingDirector")


def make_finance_officer_headers(user_id: str = "test-finance-officer-1") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")
