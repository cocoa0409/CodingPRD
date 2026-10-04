"""Pre-built role headers for every role in the PRD.

Identity model (PRD roles section):
- ProgramOfficer, ReferralOfficer, ScientificReviewOfficer, CouncilMember and
  GrantsOfficer are OPAQUE: X-User-ID is not tied to any persisted entity, so
  the shared constants below are the canonical form.
- Applicant is entity_backed by Applicant and Reviewer is entity_backed by
  Reviewer: for any ownership-gated call the caller MUST build headers with
  the real entity id via make_applicant_headers(applicant["id"]) /
  make_reviewer_headers(reviewer["id"]). The shared applicant/reviewer
  constants below are fallbacks only for tests whose success does not depend
  on owning the subject resource (e.g. 400-on-bad-payload or 404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


# Shared constants — canonical for opaque roles; non-ownership fallback for
# the two entity-backed roles.
TEST_USERS = {
    "program_officer_headers": build_user_headers("test-program-officer-1", UserRole.PROGRAM_OFFICER.value),
    "referral_officer_headers": build_user_headers("test-referral-officer-1", UserRole.REFERRAL_OFFICER.value),
    "sro_headers": build_user_headers("test-sro-1", UserRole.SCIENTIFIC_REVIEW_OFFICER.value),
    "council_member_headers": build_user_headers("test-council-member-1", UserRole.COUNCIL_MEMBER.value),
    "grants_officer_headers": build_user_headers("test-grants-officer-1", UserRole.GRANTS_OFFICER.value),
    # Entity-backed fallbacks — NEVER use for ownership-gated calls.
    "applicant_headers": build_user_headers("test-applicant-1", UserRole.APPLICANT.value),
    "reviewer_headers": build_user_headers("test-reviewer-1", UserRole.REVIEWER.value),
}


# --- Per-instance builders for entity-backed roles (mandatory on ownership-
# gated calls: submit, withdraw, jit submit-items, progress-report create,
# modification create, transfer propose, reviewer respond, declare-conflict,
# assignment respond, submit-critique). --------------------------------------

def make_applicant_headers(applicant_id: str) -> dict:
    """Headers for the Applicant role bound to a real Applicant.id."""
    return build_user_headers(applicant_id, UserRole.APPLICANT.value)


def make_reviewer_headers(reviewer_id: str) -> dict:
    """Headers for the Reviewer role bound to a real Reviewer.id."""
    return build_user_headers(reviewer_id, UserRole.REVIEWER.value)


# --- Convenience builders for opaque roles (a distinct id per caller is
# occasionally useful, e.g. council recorded_by). -----------------------------

def make_program_officer_headers(user_id: str = "test-program-officer-1") -> dict:
    return build_user_headers(user_id, UserRole.PROGRAM_OFFICER.value)


def make_referral_officer_headers(user_id: str = "test-referral-officer-1") -> dict:
    return build_user_headers(user_id, UserRole.REFERRAL_OFFICER.value)


def make_sro_headers(user_id: str = "test-sro-1") -> dict:
    return build_user_headers(user_id, UserRole.SCIENTIFIC_REVIEW_OFFICER.value)


def make_council_member_headers(user_id: str = "test-council-member-1") -> dict:
    return build_user_headers(user_id, UserRole.COUNCIL_MEMBER.value)


def make_grants_officer_headers(user_id: str = "test-grants-officer-1") -> dict:
    return build_user_headers(user_id, UserRole.GRANTS_OFFICER.value)


def without_header(headers: dict, name: str) -> dict:
    """Return a copy of headers with one header removed (auth-negative tests)."""
    trimmed = dict(headers)
    trimmed.pop(name, None)
    return trimmed
