"""Pre-built role headers for the five roles in PRD §2.1.

Identity rules (PRD §2.1):
- Candidate: X-User-ID is the acting Candidate's id (entity-backed).
- Supervisor: X-User-ID is the acting Supervisor's id (entity-backed).
- Anonymous / BoardAdministrator / NcarbAdministrator: X-User-ID is an opaque
  operator identifier never compared to any entity id (though it is recorded,
  e.g. as filed_by_user_id on a disciplinary report).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "board_admin_headers": build_user_headers("board-admin-1", "BoardAdministrator"),
    "ncarb_admin_headers": build_user_headers("ncarb-admin-1", "NcarbAdministrator"),
    # Entity-backed roles: shared constants are a fallback for non-ownership
    # tests only (400/404 paths); ownership-gated calls MUST use the builders.
    "candidate_headers": build_user_headers("candidate-fallback", "Candidate"),
    "supervisor_headers": build_user_headers("supervisor-fallback", "Supervisor"),
}


def make_candidate_headers(candidate_id: str) -> dict:
    """Candidate is entity-backed: pass the real Candidate.id for any
    candidate-scoped call (PRD §2.1 ownership rule)."""
    return build_user_headers(candidate_id, "Candidate")


def make_supervisor_headers(supervisor_id: str) -> dict:
    """Supervisor is entity-backed: pass the real Supervisor.id for
    verify/return calls (PRD §3.3 supervisor ownership rule)."""
    return build_user_headers(supervisor_id, "Supervisor")


def make_board_admin_headers(user_id: str) -> dict:
    """BoardAdministrator is opaque; distinct ids matter for
    segregation-of-duties scenarios (PRD §3.8)."""
    return build_user_headers(user_id, "BoardAdministrator")


def make_ncarb_admin_headers(user_id: str) -> dict:
    """NcarbAdministrator is opaque; a resolver id must differ from a
    report's filed_by_user_id (PRD §3.8 segregation of duties)."""
    return build_user_headers(user_id, "NcarbAdministrator")
