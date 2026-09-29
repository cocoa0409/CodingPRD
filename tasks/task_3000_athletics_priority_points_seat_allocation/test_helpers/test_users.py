"""Caller identities.

PRD section 2.1 splits identity in two.  For the five operator roles the
``X-User-ID`` is an opaque operator identifier that the server records for the
audit trail but never compares against an entity ``id``; for ``Donor`` the
``X-User-ID`` *is* the ``id`` of the acting donor record, which is what every
ownership check compares against.  So operator headers are constants, while a
donor's headers can only be built once the donor row exists.

Two segregation-of-duties axes need at least two distinct operator ids on the
same role, hence the numbered certifier and policy identities.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DEVELOPMENT_OFFICER,
    ROLE_DISPUTE_ANALYST,
    ROLE_DONOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_POINTS_CERTIFIER,
    ROLE_POLICY_COMMITTEE,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────

OFFICER_USER_ID = "officer-1"
OFFICER_2_USER_ID = "officer-2"
CERTIFIER_USER_ID = "certifier-1"
CERTIFIER_2_USER_ID = "certifier-2"
ANALYST_USER_ID = "analyst-1"
ANALYST_2_USER_ID = "analyst-2"
POLICY_USER_ID = "policy-1"
POLICY_2_USER_ID = "policy-2"
ADMIN_USER_ID = "admin-1"

# ─── Ready-made operator header sets ──────────────────────────────────────

OFFICER = build_user_headers(OFFICER_USER_ID, ROLE_DEVELOPMENT_OFFICER)
OFFICER_2 = build_user_headers(OFFICER_2_USER_ID, ROLE_DEVELOPMENT_OFFICER)
CERTIFIER = build_user_headers(CERTIFIER_USER_ID, ROLE_POINTS_CERTIFIER)
CERTIFIER_2 = build_user_headers(CERTIFIER_2_USER_ID, ROLE_POINTS_CERTIFIER)
ANALYST = build_user_headers(ANALYST_USER_ID, ROLE_DISPUTE_ANALYST)
ANALYST_2 = build_user_headers(ANALYST_2_USER_ID, ROLE_DISPUTE_ANALYST)
POLICY = build_user_headers(POLICY_USER_ID, ROLE_POLICY_COMMITTEE)
POLICY_2 = build_user_headers(POLICY_2_USER_ID, ROLE_POLICY_COMMITTEE)
ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including deliberate cross-wirings."""
    return build_user_headers(user_id, role)


def make_donor_headers(donor_id):
    """Headers for a Donor caller acting as the donor row with this id."""
    return build_user_headers(donor_id, ROLE_DONOR)


# ─── Malformed authentication header sets ─────────────────────────────────
#
# PRD section 2.1: "If either header is absent, or present but empty, the
# request is rejected with ERR_UNAUTHENTICATED (HTTP 401)".  An empty value
# must be the empty string; a whitespace-only value is not a legal HTTP
# header value and never reaches the server.

EMPTY_USER_ID = {
    "X-User-ID": "",
    "X-User-Role": ROLE_DEVELOPMENT_OFFICER,
    "Content-Type": "application/json",
}

EMPTY_USER_ROLE = {
    "X-User-ID": OFFICER_USER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

MISSING_USER_ID = {
    "X-User-Role": ROLE_DEVELOPMENT_OFFICER,
    "Content-Type": "application/json",
}

MISSING_USER_ROLE = {
    "X-User-ID": OFFICER_USER_ID,
    "Content-Type": "application/json",
}

UNKNOWN_ROLE = {
    "X-User-ID": OFFICER_USER_ID,
    "X-User-Role": "StadiumUsher",
    "Content-Type": "application/json",
}
