"""Pre-built role headers for every role in the PRD (§2.1).

Ownership model (PRD §2.1):
- Candidate / Assessor are entity-backed: X-User-ID must equal the acting
  record's id for ownership-gated calls (submit, retake, artifacts, bookings,
  renewals, submit-score, self-reads). Use make_candidate_headers(candidate["id"])
  / make_assessor_headers(assessor["id"]) — never the shared constant — for any
  call whose success depends on ownership.
- Anonymous, ScoringAdministrator, BoardAdministrator, IncentiveAdministrator
  are opaque: X-User-ID is an operator identifier never compared to a
  resource id, so the shared constants below are canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants. Safe for the opaque roles, and for Candidate/Assessor
# ONLY in tests that do not exercise ownership (e.g. 400-on-bad-payload,
# 403-on-wrong-role where role fires before ownership).
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", UserRole.ANONYMOUS.value),
    # entity_backed fallbacks — non-ownership tests only; see module docstring.
    "candidate_headers": build_user_headers("test-candidate-1", UserRole.CANDIDATE.value),
    "assessor_headers": build_user_headers("test-assessor-1", UserRole.ASSESSOR.value),
    # opaque operator roles — canonical form.
    "scoring_admin_headers": build_user_headers(
        "test-scoring-admin-1", UserRole.SCORING_ADMINISTRATOR.value
    ),
    "board_admin_headers": build_user_headers(
        "test-board-admin-1", UserRole.BOARD_ADMINISTRATOR.value
    ),
    "incentive_admin_headers": build_user_headers(
        "test-incentive-admin-1", UserRole.INCENTIVE_ADMINISTRATOR.value
    ),
}


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    """Anonymous (opaque). Only capability: POST /candidates."""
    return build_user_headers(user_id, UserRole.ANONYMOUS.value)


def make_candidate_headers(candidate_id: str) -> dict:
    """Candidate (entity-backed:Candidate). Pass the actual Candidate.id
    whenever the call is ownership-gated — submissions, artifacts, bookings,
    renewals, and self-reads all compare resource.candidate_id to X-User-ID."""
    return build_user_headers(candidate_id, UserRole.CANDIDATE.value)


def make_assessor_headers(assessor_id: str) -> dict:
    """Assessor (entity-backed:Assessor). Pass the actual Assessor.id
    whenever the call is ownership-gated — submit-score compares
    assignment.assessor_id to X-User-ID, and self-reads compare the path id."""
    return build_user_headers(assessor_id, UserRole.ASSESSOR.value)


def make_scoring_admin_headers(user_id: str = "test-scoring-admin-1") -> dict:
    """ScoringAdministrator (opaque operator)."""
    return build_user_headers(user_id, UserRole.SCORING_ADMINISTRATOR.value)


def make_board_admin_headers(user_id: str = "test-board-admin-1") -> dict:
    """BoardAdministrator (opaque operator)."""
    return build_user_headers(user_id, UserRole.BOARD_ADMINISTRATOR.value)


def make_incentive_admin_headers(user_id: str = "test-incentive-admin-1") -> dict:
    """IncentiveAdministrator (opaque operator)."""
    return build_user_headers(user_id, UserRole.INCENTIVE_ADMINISTRATOR.value)
