"""Pre-built role headers for every role in the PRD (§2.1).

API MANIFEST (frozen for Phase B):
  TEST_USERS: dict[str, dict] — shared-constant headers, one per role. Keys:
      "candidate_headers", "program_admin_headers", "proctor_headers",
      "experience_reviewer_headers", "reference_provider_headers",
      "conduct_investigator_headers", "conduct_adjudicator_headers"
    Safe for tests whose outcome does NOT depend on the caller owning the
    subject resource (bad-payload 400s, missing-resource 404s, opaque roles).

  Per-instance builders — call with the ACTUAL entity id whenever the call is
  ownership-gated (PRD §2.1: Candidate X-User-ID is the Candidate.id;
  ReferenceProvider X-User-ID is the ReferenceContact.id):
      make_candidate_headers(user_id)          — entity-backed: Candidate
      make_reference_provider_headers(user_id) — entity-backed: ReferenceContact
  Opaque-role builders (X-User-ID is an opaque operator identifier, e.g. the
  "inv-1"/"adj-2" pairs that segregation-of-duties and reviewer-attribution
  tests need):
      make_program_admin_headers(user_id)
      make_proctor_headers(user_id)
      make_experience_reviewer_headers(user_id)
      make_conduct_investigator_headers(user_id)
      make_conduct_adjudicator_headers(user_id)
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants — canonical form for opaque roles; fallback-only for the
# entity-backed roles (never use these when the call is ownership-gated).
TEST_USERS = {
    "candidate_headers": build_user_headers("test-candidate-1", UserRole.CANDIDATE.value),
    "program_admin_headers": build_user_headers("test-admin-1", UserRole.PROGRAM_ADMIN.value),
    "proctor_headers": build_user_headers("test-proctor-1", UserRole.PROCTOR.value),
    "experience_reviewer_headers": build_user_headers(
        "test-reviewer-1", UserRole.EXPERIENCE_REVIEWER.value
    ),
    "reference_provider_headers": build_user_headers(
        "test-reference-1", UserRole.REFERENCE_PROVIDER.value
    ),
    "conduct_investigator_headers": build_user_headers(
        "test-investigator-1", UserRole.CONDUCT_INVESTIGATOR.value
    ),
    "conduct_adjudicator_headers": build_user_headers(
        "test-adjudicator-1", UserRole.CONDUCT_ADJUDICATOR.value
    ),
}


# --- Entity-backed roles: X-User-ID must equal the owned entity's id ---
def make_candidate_headers(user_id: str) -> dict:
    """Candidate headers (entity-backed). Pass the actual Candidate.id whenever
    the call is ownership-gated (enrollments, appointments, submissions,
    conduct statements, appeals, memberships, CE records)."""
    return build_user_headers(user_id, UserRole.CANDIDATE.value)


def make_reference_provider_headers(user_id: str) -> dict:
    """ReferenceProvider headers (entity-backed). Pass the actual
    ReferenceContact.id — the reference answers as its own record id."""
    return build_user_headers(user_id, UserRole.REFERENCE_PROVIDER.value)


# --- Opaque roles: X-User-ID is an operator identifier, not an entity id ---
def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_proctor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PROCTOR.value)


def make_experience_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.EXPERIENCE_REVIEWER.value)


def make_conduct_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.CONDUCT_INVESTIGATOR.value)


def make_conduct_adjudicator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.CONDUCT_ADJUDICATOR.value)


__all__ = [
    "TEST_USERS",
    "make_candidate_headers",
    "make_reference_provider_headers",
    "make_program_admin_headers",
    "make_proctor_headers",
    "make_experience_reviewer_headers",
    "make_conduct_investigator_headers",
    "make_conduct_adjudicator_headers",
]
