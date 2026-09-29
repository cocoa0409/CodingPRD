"""Actor identities and header builders for the four declared roles.

Two of the four roles carry an identity that the server compares against a
stored entity id: a ``HostStoreManager``'s ``X-User-ID`` is the id of the host
store it manages, and a ``FranchiseChef``'s ``X-User-ID`` is the id of the chef
record. Tests that exercise ownership MUST build those headers from the id of
the entity created for the test, using ``make_host_store_manager_headers`` and
``make_franchise_chef_headers``. The ``TEST_USERS`` constants for those two
roles are fallbacks for calls where no ownership comparison happens.

``FranchisorOps`` and ``QualityAuditor`` identities are opaque operator ids that
are never compared to an entity id, so the constants are canonical for them.
The segregation-of-duties rules compare two opaque ids to each other, which is
why distinct creator/issuer and opener/verifier identities are provided.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FRANCHISE_CHEF,
    ROLE_FRANCHISOR_OPS,
    ROLE_HOST_STORE_MANAGER,
    ROLE_QUALITY_AUDITOR,
)

# Opaque operator identities.
OPS_CREATOR_ID = "ops-creator-1"
OPS_ISSUER_ID = "ops-issuer-2"
OPS_ALTERNATE_ID = "ops-creator-7"
AUDITOR_OPENER_ID = "qa-opener-1"
AUDITOR_VERIFIER_ID = "qa-verifier-9"

TEST_USERS = {
    "franchisor_ops_headers": build_user_headers(OPS_CREATOR_ID, ROLE_FRANCHISOR_OPS),
    "franchisor_ops_issuer_headers": build_user_headers(
        OPS_ISSUER_ID, ROLE_FRANCHISOR_OPS
    ),
    "quality_auditor_headers": build_user_headers(
        AUDITOR_OPENER_ID, ROLE_QUALITY_AUDITOR
    ),
    "quality_auditor_verifier_headers": build_user_headers(
        AUDITOR_VERIFIER_ID, ROLE_QUALITY_AUDITOR
    ),
    # Fallbacks for calls that perform no ownership comparison.
    "host_store_manager_headers": build_user_headers(
        "test-store-1", ROLE_HOST_STORE_MANAGER
    ),
    "franchise_chef_headers": build_user_headers("test-chef-1", ROLE_FRANCHISE_CHEF),
}


def make_franchisor_ops_headers(user_id: str = OPS_CREATOR_ID) -> dict:
    """Headers for an opaque franchisor operations identity."""
    return build_user_headers(user_id, ROLE_FRANCHISOR_OPS)


def make_quality_auditor_headers(user_id: str = AUDITOR_OPENER_ID) -> dict:
    """Headers for an opaque quality auditor identity."""
    return build_user_headers(user_id, ROLE_QUALITY_AUDITOR)


def make_host_store_manager_headers(host_store_id: str) -> dict:
    """Headers for the manager of one host store; pass the HostStore id."""
    return build_user_headers(host_store_id, ROLE_HOST_STORE_MANAGER)


def make_franchise_chef_headers(chef_id: str) -> dict:
    """Headers for one franchise chef; pass the Chef id."""
    return build_user_headers(chef_id, ROLE_FRANCHISE_CHEF)


def make_role_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/id pair, including undeclared role names."""
    return build_user_headers(user_id, role)


def make_headers_without_identity() -> dict:
    """Headers carrying an empty role and no user id at all.

    The empty string is deliberate: a blank-but-present header value is what the
    authentication rung of the rejection ladder is specified against.
    """
    return {"X-User-Role": "", "Content-Type": "application/json"}


def make_headers_with_blank_role(user_id: str) -> dict:
    """Headers carrying a user id but an empty role value."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


NO_HEADERS: dict = {}
