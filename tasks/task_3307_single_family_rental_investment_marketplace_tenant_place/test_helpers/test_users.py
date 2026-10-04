"""Caller identities for the seven declared roles.

Three roles are entity-backed — ``Seller``, ``Buyer`` and ``PropertyManager``
must present the ``id`` of a persisted entity whenever the call is
ownership-gated; use the ``make_*_headers(entity_id)`` builders for those.
The four opaque roles (``PlatformAdmin``, ``CertificationReviewer``,
``EscrowOfficer``, ``ClaimsAdjuster``) carry stable operator identifiers.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"id": "admin-00000000-0000-4000-8000-000000000001", "role": "PlatformAdmin"},
    "certification_reviewer": {"id": "rev-00000000-0000-4000-8000-000000000001", "role": "CertificationReviewer"},
    "escrow_officer": {"id": "eo-00000000-0000-4000-8000-000000000001", "role": "EscrowOfficer"},
    "claims_adjuster": {"id": "adjuster-00000000-0000-4000-8000-000000000001", "role": "ClaimsAdjuster"},
}

PLATFORM_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["platform_admin"]["id"], TEST_USERS["platform_admin"]["role"]
)
REVIEWER_HEADERS = build_user_headers(
    TEST_USERS["certification_reviewer"]["id"], TEST_USERS["certification_reviewer"]["role"]
)
ESCROW_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["escrow_officer"]["id"], TEST_USERS["escrow_officer"]["role"]
)
CLAIMS_ADJUSTER_HEADERS = build_user_headers(
    TEST_USERS["claims_adjuster"]["id"], TEST_USERS["claims_adjuster"]["role"]
)


def make_platform_admin_headers(user_id: str = TEST_USERS["platform_admin"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_reviewer_headers(user_id: str = TEST_USERS["certification_reviewer"]["id"]) -> Dict[str, str]:
    """CertificationReviewer is opaque; pass a distinct id for segregation tests."""
    return build_user_headers(user_id, "CertificationReviewer")


def make_escrow_officer_headers(user_id: str = TEST_USERS["escrow_officer"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, "EscrowOfficer")


def make_claims_adjuster_headers(user_id: str = TEST_USERS["claims_adjuster"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, "ClaimsAdjuster")


# Entity-backed roles — user_id MUST be the persisted entity's id for any
# ownership-gated call.
def make_seller_headers(user_id: str) -> Dict[str, str]:
    """Seller is entity-backed: pass the Seller.id as user_id."""
    return build_user_headers(user_id, "Seller")


def make_buyer_headers(user_id: str) -> Dict[str, str]:
    """Buyer is entity-backed: pass the Buyer.id as user_id."""
    return build_user_headers(user_id, "Buyer")


def make_property_manager_headers(user_id: str) -> Dict[str, str]:
    """PropertyManager is entity-backed: pass the PropertyManager.id as user_id."""
    return build_user_headers(user_id, "PropertyManager")
