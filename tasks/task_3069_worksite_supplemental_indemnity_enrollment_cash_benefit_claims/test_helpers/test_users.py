"""Caller identities.

Four of the five roles carry an opaque operator identifier that the server "never
compares it to any entity's ``id``", so a shared constant is enough for them. The
``BenefitCounselor`` role is backed by a persisted counselor row: the server compares
a campaign's ``counselor_id`` against ``X-User-ID``, so counselor headers are always
built around the live counselor identifier handed in by the caller.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BENEFIT_COUNSELOR,
    ROLE_CARRIER_ADMIN,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_GROUP_ADMIN,
    ROLE_POLICYHOLDER_SERVICES,
)
from .types import Headers, ResourceId

# Opaque operator identifiers for the four roles the server never compares to an id.
CARRIER_ADMIN_USER_ID = "carrier-admin-operator-001"
GROUP_ADMIN_USER_ID = "group-admin-operator-001"
CLAIMS_ADJUSTER_USER_ID = "claims-adjuster-operator-001"
POLICYHOLDER_SERVICES_USER_ID = "policyholder-services-operator-001"

# Shared constants for the opaque roles (safe for any call).
TEST_USERS = {
    "carrier_admin_headers": build_user_headers(
        CARRIER_ADMIN_USER_ID, ROLE_CARRIER_ADMIN
    ),
    "group_admin_headers": build_user_headers(GROUP_ADMIN_USER_ID, ROLE_GROUP_ADMIN),
    "claims_adjuster_headers": build_user_headers(
        CLAIMS_ADJUSTER_USER_ID, ROLE_CLAIMS_ADJUSTER
    ),
    "policyholder_services_headers": build_user_headers(
        POLICYHOLDER_SERVICES_USER_ID, ROLE_POLICYHOLDER_SERVICES
    ),
    # Fallback for a counselor call where no specific counselor identity matters
    # (e.g. a 403 probe). Ownership-gated calls MUST use make_counselor_headers.
    "benefit_counselor_headers": build_user_headers(
        "counselor-operator-placeholder", ROLE_BENEFIT_COUNSELOR
    ),
}


def make_carrier_admin_headers() -> Headers:
    """Headers for the carrier-side administrator."""
    return build_user_headers(CARRIER_ADMIN_USER_ID, ROLE_CARRIER_ADMIN)


def make_group_admin_headers() -> Headers:
    """Headers for the employer-side administrator."""
    return build_user_headers(GROUP_ADMIN_USER_ID, ROLE_GROUP_ADMIN)


def make_claims_adjuster_headers() -> Headers:
    """Headers for the claims adjudicator."""
    return build_user_headers(CLAIMS_ADJUSTER_USER_ID, ROLE_CLAIMS_ADJUSTER)


def make_policyholder_services_headers() -> Headers:
    """Headers for the policyholder service desk."""
    return build_user_headers(POLICYHOLDER_SERVICES_USER_ID, ROLE_POLICYHOLDER_SERVICES)


def make_counselor_headers(counselor_id: ResourceId) -> Headers:
    """Headers for a benefit counselor acting as themselves.

    ``X-User-ID`` must be the id of the acting counselor row: the server compares a
    campaign's ``counselor_id`` against it when the counselor drives the campaign
    lifecycle.
    """
    return build_user_headers(counselor_id, ROLE_BENEFIT_COUNSELOR)


def headers_without_identity() -> Headers:
    """A request that carries no identity headers at all."""
    return {"Content-Type": "application/json"}


__all__ = [
    "TEST_USERS",
    "make_carrier_admin_headers",
    "make_group_admin_headers",
    "make_claims_adjuster_headers",
    "make_policyholder_services_headers",
    "make_counselor_headers",
    "headers_without_identity",
]
