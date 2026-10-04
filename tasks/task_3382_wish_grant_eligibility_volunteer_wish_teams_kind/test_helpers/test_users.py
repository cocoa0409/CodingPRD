"""Pre-built role headers for every role in the PRD.

Two forms per role:

- A shared constant in TEST_USERS — used by tests whose outcome does not
  depend on the caller owning a specific resource (400/404 probes, opaque
  roles, and the canonical operator identities like "coord-1" / "dir-1"
  that fixtures thread through plan creation and approval).

- A per-instance builder make_<role>_headers(user_id) — MANDATORY for the
  entity-backed Volunteer role: X-User-ID must equal the actual Volunteer
  entity's id for team-membership checks, so fixtures and tests build
  volunteer headers from the created volunteer's id. Also used wherever a
  test needs two distinct operators of the same opaque role (e.g. two
  ChapterDirectors for segregation-of-duties).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Canonical opaque operator identities. These exact ids are load-bearing:
# plans created by "coord-1" are approvable by "dir-1"/"nat-1" but not by
# their creator; "dir-1" vs "dir-2" drive the segregation-of-duties pair.
NATIONAL_ADMIN_ID = "admin-1"
REFERRAL_SOURCE_ID = "src-1"
MEDICAL_PROVIDER_ID = "med-1"
ELIGIBILITY_REVIEWER_ID = "rev-1"
WISH_COORDINATOR_ID = "coord-1"
IN_KIND_OFFICER_ID = "iko-1"
CHAPTER_DIRECTOR_ID = "dir-1"
CHAPTER_DIRECTOR_ALT_ID = "dir-2"
NATIONAL_DIRECTOR_ID = "nat-1"

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "national_admin_headers": build_user_headers(
        NATIONAL_ADMIN_ID, UserRole.NATIONAL_ADMIN.value),
    "referral_source_headers": build_user_headers(
        REFERRAL_SOURCE_ID, UserRole.REFERRAL_SOURCE.value),
    "medical_provider_headers": build_user_headers(
        MEDICAL_PROVIDER_ID, UserRole.MEDICAL_PROVIDER.value),
    "eligibility_reviewer_headers": build_user_headers(
        ELIGIBILITY_REVIEWER_ID, UserRole.ELIGIBILITY_REVIEWER.value),
    "wish_coordinator_headers": build_user_headers(
        WISH_COORDINATOR_ID, UserRole.WISH_COORDINATOR.value),
    "in_kind_officer_headers": build_user_headers(
        IN_KIND_OFFICER_ID, UserRole.IN_KIND_OFFICER.value),
    "chapter_director_headers": build_user_headers(
        CHAPTER_DIRECTOR_ID, UserRole.CHAPTER_DIRECTOR.value),
    # Second director identity: segregation-of-duties approvals need an
    # approver distinct from the plan's creator.
    "chapter_director_alt_headers": build_user_headers(
        CHAPTER_DIRECTOR_ALT_ID, UserRole.CHAPTER_DIRECTOR.value),
    "national_director_headers": build_user_headers(
        NATIONAL_DIRECTOR_ID, UserRole.NATIONAL_DIRECTOR.value),
    # entity_backed:Volunteer — FALLBACK ONLY. Never use this constant for a
    # team-membership-gated call (visit create/conclude): the id below belongs
    # to no real Volunteer entity. Use make_volunteer_headers(volunteer["id"]).
    "volunteer_headers": build_user_headers(
        "vol-fallback-1", UserRole.VOLUNTEER.value),
}


def make_national_admin_headers(user_id: str = NATIONAL_ADMIN_ID) -> dict:
    return build_user_headers(user_id, UserRole.NATIONAL_ADMIN.value)


def make_referral_source_headers(user_id: str = REFERRAL_SOURCE_ID) -> dict:
    return build_user_headers(user_id, UserRole.REFERRAL_SOURCE.value)


def make_medical_provider_headers(user_id: str = MEDICAL_PROVIDER_ID) -> dict:
    return build_user_headers(user_id, UserRole.MEDICAL_PROVIDER.value)


def make_eligibility_reviewer_headers(user_id: str = ELIGIBILITY_REVIEWER_ID) -> dict:
    return build_user_headers(user_id, UserRole.ELIGIBILITY_REVIEWER.value)


def make_volunteer_headers(user_id: str) -> dict:
    """Entity-backed role: pass the actual Volunteer entity's id whenever the
    call is membership-gated (wish-visit create/conclude)."""
    return build_user_headers(user_id, UserRole.VOLUNTEER.value)


def make_wish_coordinator_headers(user_id: str = WISH_COORDINATOR_ID) -> dict:
    return build_user_headers(user_id, UserRole.WISH_COORDINATOR.value)


def make_in_kind_officer_headers(user_id: str = IN_KIND_OFFICER_ID) -> dict:
    return build_user_headers(user_id, UserRole.IN_KIND_OFFICER.value)


def make_chapter_director_headers(user_id: str = CHAPTER_DIRECTOR_ID) -> dict:
    return build_user_headers(user_id, UserRole.CHAPTER_DIRECTOR.value)


def make_national_director_headers(user_id: str = NATIONAL_DIRECTOR_ID) -> dict:
    return build_user_headers(user_id, UserRole.NATIONAL_DIRECTOR.value)
