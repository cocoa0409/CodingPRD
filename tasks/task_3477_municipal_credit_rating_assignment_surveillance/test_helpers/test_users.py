"""Caller identities for the seven declared roles (PRD section 2.1).

Two roles are entity-backed: for ``Issuer`` and ``Underwriter`` the
``X-User-ID`` IS the ``id`` of the acting issuer or underwriter record, and
every ownership check compares against it.  Those headers can only be built
once the record exists — use ``make_issuer_headers(issuer["id"])`` /
``make_underwriter_headers(underwriter["id"])``.  The shared constants for
those two roles exist ONLY for tests that never touch an ownership check
(bad-payload 400s, wrong-role 403s, missing-resource 404s).

The other five roles carry opaque operator identifiers.  Distinctness
matters in two places:

* segregation of duties (PRD section 3.3): the LeadAnalyst who authored an
  engagement's scorecard is recorded as its ``assigned_analyst_id`` and is
  barred from voting on it — so a second analyst identity exists for
  engagements that must differ, and the committee pool must never silently
  reuse the authoring analyst's id unless the test is probing that bar;
* chair identity (PRD section 3.3): only the scheduling chair may open,
  close or appoint alternates, so a second chair exists for negative tests.

Committee members vote under their pool identifier: ``voter_id`` must equal
``X-User-ID``, so member headers are always built per voter id via
``make_committee_member_headers``.
"""

from prd_bench_local_runner.testing import build_user_headers

from . import constants as C

# ─── Opaque operator identifiers ────────────────────────────────────────────

ADMIN_USER_ID = "admin-1"
ANALYST_USER_ID = "analyst-1"
ANALYST_2_USER_ID = "analyst-2"
CHAIR_USER_ID = "chair-1"
CHAIR_2_USER_ID = "chair-2"
OFFICER_USER_ID = "officer-1"

# ─── Ready-made header sets for the opaque roles ────────────────────────────

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, C.ROLE_PLATFORM_ADMIN)
ANALYST_HEADERS = build_user_headers(ANALYST_USER_ID, C.ROLE_LEAD_ANALYST)
ANALYST_2_HEADERS = build_user_headers(ANALYST_2_USER_ID, C.ROLE_LEAD_ANALYST)
CHAIR_HEADERS = build_user_headers(CHAIR_USER_ID, C.ROLE_COMMITTEE_CHAIR)
CHAIR_2_HEADERS = build_user_headers(CHAIR_2_USER_ID, C.ROLE_COMMITTEE_CHAIR)
OFFICER_HEADERS = build_user_headers(OFFICER_USER_ID, C.ROLE_SURVEILLANCE_OFFICER)

# Shared constants for the entity-backed roles.  These are FALLBACKS for
# tests that do not exercise ownership; any ownership-gated call must use
# the make_*_headers builders below with the real entity id.
ISSUER_HEADERS = build_user_headers("issuer-placeholder", C.ROLE_ISSUER)
UNDERWRITER_HEADERS = build_user_headers("underwriter-placeholder", C.ROLE_UNDERWRITER)

# ─── Shared-constant registry (thin fixture source for test_suite) ─────────

TEST_USERS = {
    "platform_admin_headers": ADMIN_HEADERS,
    "lead_analyst_headers": ANALYST_HEADERS,
    "lead_analyst_2_headers": ANALYST_2_HEADERS,
    "committee_chair_headers": CHAIR_HEADERS,
    "committee_chair_2_headers": CHAIR_2_HEADERS,
    "surveillance_officer_headers": OFFICER_HEADERS,
    "issuer_headers": ISSUER_HEADERS,
    "underwriter_headers": UNDERWRITER_HEADERS,
    # Committee members always act under their own pool id; the canonical
    # first pool member is included for convenience.
    "committee_member_headers": build_user_headers("voter-1", C.ROLE_COMMITTEE_MEMBER),
}

# ─── Per-instance builders (entity-backed roles and committee members) ──────


def make_issuer_headers(issuer_id):
    """Headers for the Issuer role acting as issuer record ``issuer_id``.
    Mandatory on every ownership-gated call: engagement create/accept/
    documents/withdraw, appeals, obligation submission, bond sales."""
    return build_user_headers(issuer_id, C.ROLE_ISSUER)


def make_underwriter_headers(underwriter_id):
    """Headers for the Underwriter role acting as underwriter record
    ``underwriter_id``; an underwriter-originated engagement must carry
    ``underwriter_id`` equal to this id (PRD section 2.1)."""
    return build_user_headers(underwriter_id, C.ROLE_UNDERWRITER)


def make_committee_member_headers(voter_id):
    """Headers for the CommitteeMember casting a ballot as ``voter_id``;
    the voter id must equal X-User-ID and belong to the session pool
    (PRD section 3.3)."""
    return build_user_headers(voter_id, C.ROLE_COMMITTEE_MEMBER)


def make_lead_analyst_headers(user_id):
    """A LeadAnalyst under an arbitrary opaque id (e.g. for a second
    analyst on a sibling engagement)."""
    return build_user_headers(user_id, C.ROLE_LEAD_ANALYST)


def make_committee_chair_headers(user_id):
    """A CommitteeChair under an arbitrary opaque id."""
    return build_user_headers(user_id, C.ROLE_COMMITTEE_CHAIR)


def make_surveillance_officer_headers(user_id):
    """A SurveillanceOfficer under an arbitrary opaque id."""
    return build_user_headers(user_id, C.ROLE_SURVEILLANCE_OFFICER)


def make_platform_admin_headers(user_id):
    """A PlatformAdmin under an arbitrary opaque id."""
    return build_user_headers(user_id, C.ROLE_PLATFORM_ADMIN)


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including deliberate cross-wirings
    for negative RBAC tests."""
    return build_user_headers(user_id, role)


# ─── Malformed authentication header sets (PRD section 2.1) ─────────────────
#
# "A request missing either header, or carrying a role the system does not
# declare, is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER".

NO_HEADERS = {"Content-Type": "application/json"}

MISSING_USER_ID_HEADERS = {
    "X-User-Role": C.ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}

MISSING_USER_ROLE_HEADERS = {
    "X-User-ID": ADMIN_USER_ID,
    "Content-Type": "application/json",
}

UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": ADMIN_USER_ID,
    "X-User-Role": "RatingCommittee",
    "Content-Type": "application/json",
}
