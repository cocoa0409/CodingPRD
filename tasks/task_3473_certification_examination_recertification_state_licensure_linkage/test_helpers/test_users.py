"""Pre-built role headers for every role in the PRD (§2.1).

Identity bindings:
- Candidate is entity-backed: X-User-ID must equal the Candidate.id minted at
  self-registration. Fixtures MUST use make_candidate_headers(candidate["id"])
  for any ownership-gated call; the shared TEST_USERS constant is only for
  tests that do not exercise ownership (400/404/foreign-role probes).
- ProgramDirector is opaque but program-scoped: X-User-ID must equal the
  target program's director_user_id on attestation endpoints. Use
  make_program_director_headers(program["director_user_id"]).
- StateOfficial / RegistryAdmin / ExamProctor are opaque operator ids.
- HearingOfficer is opaque but must differ from a case's opened_by_user_id.
- Anonymous sends no identity headers at all (candidate self-registration).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    DEFAULT_ADMIN_USER_ID,
    DEFAULT_DIRECTOR_USER_ID,
    DEFAULT_HEARING_OFFICER_USER_ID,
    DEFAULT_PROCTOR_USER_ID,
    DEFAULT_STATE_OFFICIAL_USER_ID,
)
from .types import UserRole

# Anonymous: no X-User-ID / X-User-Role headers (PRD §2.1).
ANONYMOUS_HEADERS: dict = {}

TEST_USERS = {
    # Shared constants — safe for opaque roles and non-ownership tests.
    "anonymous_headers": ANONYMOUS_HEADERS,
    "registry_admin_headers": build_user_headers(DEFAULT_ADMIN_USER_ID, UserRole.REGISTRY_ADMIN.value),
    "program_director_headers": build_user_headers(DEFAULT_DIRECTOR_USER_ID, UserRole.PROGRAM_DIRECTOR.value),
    "state_official_headers": build_user_headers(DEFAULT_STATE_OFFICIAL_USER_ID, UserRole.STATE_OFFICIAL.value),
    "exam_proctor_headers": build_user_headers(DEFAULT_PROCTOR_USER_ID, UserRole.EXAM_PROCTOR.value),
    "hearing_officer_headers": build_user_headers(DEFAULT_HEARING_OFFICER_USER_ID, UserRole.HEARING_OFFICER.value),
    # Candidate fallback — NEVER valid for ownership-gated calls; use
    # make_candidate_headers(candidate["id"]) instead.
    "candidate_headers": build_user_headers("test-candidate-1", UserRole.CANDIDATE.value),
}


def make_candidate_headers(user_id: str) -> dict:
    """Entity-backed Candidate identity: pass the actual Candidate.id."""
    return build_user_headers(user_id, UserRole.CANDIDATE.value)


def make_program_director_headers(user_id: str) -> dict:
    """Program-scoped attestations require user_id == program.director_user_id."""
    return build_user_headers(user_id, UserRole.PROGRAM_DIRECTOR.value)


def make_state_official_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.STATE_OFFICIAL.value)


def make_registry_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.REGISTRY_ADMIN.value)


def make_exam_proctor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.EXAM_PROCTOR.value)


def make_hearing_officer_headers(user_id: str) -> dict:
    """Must differ from the target case's opened_by_user_id (segregation)."""
    return build_user_headers(user_id, UserRole.HEARING_OFFICER.value)
