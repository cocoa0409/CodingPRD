"""Caller identities for the eleven roles of PRD §2.1.

Eight roles are opaque operator identities: their ``X-User-ID`` is "an opaque
operator identifier that is not tied to any persisted entity", so a single
constant header dict per role is enough, and a second identity per role is
provided for the two segregation-of-duties rules.

Three roles are entity-backed: for ``PartnerBrandReviewer`` the ``X-User-ID`` is
a ``UtilityPartner.id``, for ``Policyholder`` a ``Premises.id``, and for
``NetworkContractor`` a ``Contractor.id``. Those three therefore have no usable
constant — every ownership-sensitive call must build its headers from the real
identifier through the ``make_*_headers`` builders below.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPEALS_OFFICER,
    ROLE_BILLING_OPS,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_CUSTOMER_SERVICE_REP,
    ROLE_MARKETING_OPS,
    ROLE_NETWORK_CONTRACTOR,
    ROLE_OPERATIONS_ADMIN,
    ROLE_PARTNER_BRAND_REVIEWER,
    ROLE_PLATFORM_ADMIN,
    ROLE_POLICYHOLDER,
    ROLE_REGULATORY_AFFAIRS,
)

# ── Opaque operator identifiers ──

PLATFORM_ADMIN_USER_ID = "padmin-001"
MARKETING_OPS_USER_ID = "mops-001"
MARKETING_OPS_USER_ID_2 = "mops-002"
CUSTOMER_SERVICE_REP_USER_ID = "csr-001"
BILLING_OPS_USER_ID = "bill-001"
CLAIMS_ADJUSTER_USER_ID = "adj-001"
CLAIMS_ADJUSTER_USER_ID_2 = "adj-002"
APPEALS_OFFICER_USER_ID = "apo-001"
APPEALS_OFFICER_USER_ID_2 = "apo-002"
REGULATORY_AFFAIRS_USER_ID = "reg-001"
OPERATIONS_ADMIN_USER_ID = "ops-001"

PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
MARKETING_OPS = build_user_headers(MARKETING_OPS_USER_ID, ROLE_MARKETING_OPS)
MARKETING_OPS_2 = build_user_headers(MARKETING_OPS_USER_ID_2, ROLE_MARKETING_OPS)
CUSTOMER_SERVICE_REP = build_user_headers(CUSTOMER_SERVICE_REP_USER_ID, ROLE_CUSTOMER_SERVICE_REP)
BILLING_OPS = build_user_headers(BILLING_OPS_USER_ID, ROLE_BILLING_OPS)
CLAIMS_ADJUSTER = build_user_headers(CLAIMS_ADJUSTER_USER_ID, ROLE_CLAIMS_ADJUSTER)
CLAIMS_ADJUSTER_2 = build_user_headers(CLAIMS_ADJUSTER_USER_ID_2, ROLE_CLAIMS_ADJUSTER)
APPEALS_OFFICER = build_user_headers(APPEALS_OFFICER_USER_ID, ROLE_APPEALS_OFFICER)
APPEALS_OFFICER_2 = build_user_headers(APPEALS_OFFICER_USER_ID_2, ROLE_APPEALS_OFFICER)
REGULATORY_AFFAIRS = build_user_headers(REGULATORY_AFFAIRS_USER_ID, ROLE_REGULATORY_AFFAIRS)
OPERATIONS_ADMIN = build_user_headers(OPERATIONS_ADMIN_USER_ID, ROLE_OPERATIONS_ADMIN)

TEST_USERS = {
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
    ROLE_MARKETING_OPS: MARKETING_OPS,
    ROLE_CUSTOMER_SERVICE_REP: CUSTOMER_SERVICE_REP,
    ROLE_BILLING_OPS: BILLING_OPS,
    ROLE_CLAIMS_ADJUSTER: CLAIMS_ADJUSTER,
    ROLE_APPEALS_OFFICER: APPEALS_OFFICER,
    ROLE_REGULATORY_AFFAIRS: REGULATORY_AFFAIRS,
    ROLE_OPERATIONS_ADMIN: OPERATIONS_ADMIN,
}


# ── Entity-backed identities: one builder per acting instance ──

def make_partner_brand_reviewer_headers(partner_id: str) -> dict:
    """Headers for the reviewer of the partner whose id is ``partner_id``."""
    return build_user_headers(partner_id, ROLE_PARTNER_BRAND_REVIEWER)


def make_policyholder_headers(premises_id: str) -> dict:
    """Headers for the policyholder of the premises whose id is ``premises_id``."""
    return build_user_headers(premises_id, ROLE_POLICYHOLDER)


def make_network_contractor_headers(contractor_id: str) -> dict:
    """Headers for the crew of the contractor whose id is ``contractor_id``."""
    return build_user_headers(contractor_id, ROLE_NETWORK_CONTRACTOR)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary (role, identity) pair."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, entity_id: str = "") -> dict:
    """Return usable headers for any of the eleven roles.

    Opaque roles get their standing operator identity; the three entity-backed
    roles get ``entity_id``, which the caller must supply as the id of the
    partner, premises or contractor the caller is acting as.
    """
    if role in TEST_USERS:
        return TEST_USERS[role]
    if role == ROLE_PARTNER_BRAND_REVIEWER:
        return make_partner_brand_reviewer_headers(entity_id)
    if role == ROLE_POLICYHOLDER:
        return make_policyholder_headers(entity_id)
    if role == ROLE_NETWORK_CONTRACTOR:
        return make_network_contractor_headers(entity_id)
    raise ValueError(f"Unknown role: {role!r}")


# ── Malformed authentication headers (PRD §2.1) ──

# "A request whose X-User-ID header is absent or empty" — the two shapes.
NO_USER_ID_HEADERS = {"X-User-Role": ROLE_PLATFORM_ADMIN, "Content-Type": "application/json"}
EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}
