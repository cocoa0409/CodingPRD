"""Caller identities.

PRD section 2.1 splits identity in two.  For the four carrier-side operator
roles (PlanAdmin, NetworkManager, ClinicalReviewer, ClaimsExaminer) the
``X-User-ID`` is an opaque operator identifier that the server records but
never compares against an entity ``id``; for ``Member`` the ``X-User-ID``
*is* the ``id`` of the acting ``Subscriber``, and for ``Provider`` it is the
``id`` of the acting ``Provider`` record — which is what every ownership
check compares against.  So operator headers are constants, while member
and provider headers can only be built once the corresponding row exists.

Two segregation-of-duties axes need at least two distinct reviewer ids,
hence ``REVIEWER_1`` and ``REVIEWER_2``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLAIMS_EXAMINER,
    ROLE_CLINICAL_REVIEWER,
    ROLE_MEMBER,
    ROLE_NETWORK_MANAGER,
    ROLE_PLAN_ADMIN,
    ROLE_PROVIDER,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────

ADMIN_USER_ID = "admin-1"
NETWORK_USER_ID = "network-1"
REVIEWER_1_USER_ID = "rev-1"
REVIEWER_2_USER_ID = "rev-2"
EXAMINER_USER_ID = "examiner-1"

# ─── Ready-made operator header sets ──────────────────────────────────────

ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PLAN_ADMIN)
NETWORK = build_user_headers(NETWORK_USER_ID, ROLE_NETWORK_MANAGER)
REVIEWER_1 = build_user_headers(REVIEWER_1_USER_ID, ROLE_CLINICAL_REVIEWER)
REVIEWER_2 = build_user_headers(REVIEWER_2_USER_ID, ROLE_CLINICAL_REVIEWER)
EXAMINER = build_user_headers(EXAMINER_USER_ID, ROLE_CLAIMS_EXAMINER)


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including deliberate cross-wirings."""
    return build_user_headers(user_id, role)


def make_member_headers(subscriber_id):
    """Headers for a Member caller acting as the subscriber with this id.

    Mandatory whenever the call is ownership-gated: the server compares
    ``X-User-ID`` against the resource's ``subscriber_id``.
    """
    return build_user_headers(subscriber_id, ROLE_MEMBER)


def make_provider_headers(provider_id):
    """Headers for a Provider caller acting as the provider with this id.

    Mandatory whenever the call is ownership-gated: the server compares
    ``X-User-ID`` against the resource's ``provider_id``.
    """
    return build_user_headers(provider_id, ROLE_PROVIDER)


def make_reviewer_headers(reviewer_id):
    """Headers for a ClinicalReviewer with the given opaque reviewer id."""
    return build_user_headers(reviewer_id, ROLE_CLINICAL_REVIEWER)


# ─── Malformed / absent authentication header sets ────────────────────────

NO_HEADERS = {}

TEST_USERS = {
    "plan_admin_headers": ADMIN,
    "network_manager_headers": NETWORK,
    "clinical_reviewer_headers": REVIEWER_1,
    "claims_examiner_headers": EXAMINER,
}
