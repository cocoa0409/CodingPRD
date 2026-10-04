"""Caller identities and pre-built role headers (PRD §2.1).

The meaning of ``X-User-ID`` depends on the presented role:

- ``PlatformAdmin`` and ``AwardsDirector`` are OPAQUE operator identifiers —
  the server never compares them to an entity ``id``.  Their shared constants
  are the canonical form.
- ``GovernmentContact`` is entity-backed by Government: ``X-User-ID`` must be
  the acting government's ``id`` for any ownership-gated call.
- ``Reviewer`` is entity-backed by ReviewerProfile: ``X-User-ID`` must be the
  profile's own ``id`` (NOT the member id) for profile self-updates and for
  assignment accept/decline/finding.
- ``CommitteeMember`` and ``Member`` are both entity-backed by Member:
  ``X-User-ID`` is the member's ``id``; committee operations additionally
  require membership of the publication's ``member_ids``.

For every entity-backed role this module therefore provides a per-instance
builder, ``make_<role>_headers(entity_id)``.  Fixtures MUST call the builder
with the freshly created entity's ``id`` — the shared constants for those
roles are fallbacks for tests that do not exercise ownership (bad-payload
400s, missing-resource 404s, role-denial 403s) and will fail every
ownership-gated call by construction.
"""

from prd_bench_local_runner.testing import build_user_headers

# ─── Role strings (PRD §2.1) ────────────────────────────────────────────────

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_GOVERNMENT_CONTACT = "GovernmentContact"
ROLE_REVIEWER = "Reviewer"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_MEMBER = "Member"
ROLE_AWARDS_DIRECTOR = "AwardsDirector"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_GOVERNMENT_CONTACT,
    ROLE_REVIEWER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_MEMBER,
    ROLE_AWARDS_DIRECTOR,
)

# ─── Opaque operator identifiers ────────────────────────────────────────────

PLATFORM_ADMIN_USER_ID = "test-platform-admin-1"
AWARDS_DIRECTOR_USER_ID = "test-awards-director-1"

# ─── Shared header constants ────────────────────────────────────────────────
# Entity-backed entries are safe ONLY where ownership is not exercised.

TEST_USERS = {
    # Opaque roles — canonical form.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN
    ),
    "awards_director_headers": build_user_headers(
        AWARDS_DIRECTOR_USER_ID, ROLE_AWARDS_DIRECTOR
    ),
    # Entity-backed roles — fallback for non-ownership tests only.
    "government_contact_headers": build_user_headers(
        "test-government-contact-1", ROLE_GOVERNMENT_CONTACT
    ),
    "reviewer_headers": build_user_headers("test-reviewer-1", ROLE_REVIEWER),
    "committee_member_headers": build_user_headers(
        "test-committee-member-1", ROLE_COMMITTEE_MEMBER
    ),
    "member_headers": build_user_headers("test-member-1", ROLE_MEMBER),
}

# Convenient module-level aliases for the two opaque roles.
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
AWARDS_DIRECTOR = TEST_USERS["awards_director_headers"]


# ─── Per-instance builders for entity-backed roles (mandatory on
#     ownership-gated calls) ────────────────────────────────────────────────


def make_government_contact_headers(government_id):
    """GovernmentContact acting as the Government row with this id."""
    return build_user_headers(government_id, ROLE_GOVERNMENT_CONTACT)


def make_reviewer_headers(reviewer_profile_id):
    """Reviewer acting as the ReviewerProfile row with this id."""
    return build_user_headers(reviewer_profile_id, ROLE_REVIEWER)


def make_committee_member_headers(member_id):
    """CommitteeMember acting as the Member row with this id."""
    return build_user_headers(member_id, ROLE_COMMITTEE_MEMBER)


def make_member_headers(member_id):
    """Member acting as the Member row with this id."""
    return build_user_headers(member_id, ROLE_MEMBER)


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including deliberate cross-wirings."""
    return build_user_headers(user_id, role)


# ─── Malformed authentication header sets (PRD §2.1: missing or invalid
#     headers are ERR_UNAUTHENTICATED) ──────────────────────────────────────

MISSING_USER_ID = {
    "X-User-Role": ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}

MISSING_USER_ROLE = {
    "X-User-ID": PLATFORM_ADMIN_USER_ID,
    "Content-Type": "application/json",
}

EMPTY_USER_ID = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}

EMPTY_USER_ROLE = {
    "X-User-ID": PLATFORM_ADMIN_USER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

UNKNOWN_ROLE = {
    "X-User-ID": PLATFORM_ADMIN_USER_ID,
    "X-User-Role": "CountyClerk",
    "Content-Type": "application/json",
}
