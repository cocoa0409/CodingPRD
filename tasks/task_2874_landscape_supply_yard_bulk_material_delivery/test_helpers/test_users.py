"""Identity headers for every declared role.

``Contractor`` is entity-backed: the ``X-User-ID`` a contractor presents must be the
id of the ContractorAccount row it owns, so ownership-scoped calls have to build
their headers from a freshly created account. Every other role is opaque, so any
stable string works, and distinct strings are used where a test must tell two
operators apart (for example a dispatching planner versus a deciding adjuster).
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

# Opaque identities reused across tests that do not care which operator acted.
YARD_ADMIN_USER_ID = "admin-1"
CREDIT_MANAGER_USER_ID = "credit-1"
DISPATCH_PLANNER_USER_ID = "planner-1"
YARD_LOADER_USER_ID = "loader-1"
CLAIMS_ADJUSTER_USER_ID = "adjuster-1"
# Placeholder contractor identity, only valid for calls that touch no owned row.
CONTRACTOR_USER_ID = "contractor-1"

TEST_USERS = {
    "yard_admin": build_user_headers(YARD_ADMIN_USER_ID, "YardAdmin"),
    "credit_manager": build_user_headers(CREDIT_MANAGER_USER_ID, "CreditManager"),
    "dispatch_planner": build_user_headers(DISPATCH_PLANNER_USER_ID, "DispatchPlanner"),
    "yard_loader": build_user_headers(YARD_LOADER_USER_ID, "YardLoader"),
    "claims_adjuster": build_user_headers(CLAIMS_ADJUSTER_USER_ID, "ClaimsAdjuster"),
    "contractor": build_user_headers(CONTRACTOR_USER_ID, "Contractor"),
}

ROLE_NAMES = [
    "YardAdmin",
    "CreditManager",
    "DispatchPlanner",
    "YardLoader",
    "ClaimsAdjuster",
    "Contractor",
]


def make_contractor_headers(contractor_account_id: str) -> Headers:
    """Headers for the Contractor that owns ``contractor_account_id``."""
    return build_user_headers(contractor_account_id, "Contractor")


def make_yard_admin_headers(user_id: str = YARD_ADMIN_USER_ID) -> Headers:
    return build_user_headers(user_id, "YardAdmin")


def make_credit_manager_headers(user_id: str = CREDIT_MANAGER_USER_ID) -> Headers:
    return build_user_headers(user_id, "CreditManager")


def make_dispatch_planner_headers(user_id: str = DISPATCH_PLANNER_USER_ID) -> Headers:
    return build_user_headers(user_id, "DispatchPlanner")


def make_yard_loader_headers(user_id: str = YARD_LOADER_USER_ID) -> Headers:
    return build_user_headers(user_id, "YardLoader")


def make_claims_adjuster_headers(user_id: str = CLAIMS_ADJUSTER_USER_ID) -> Headers:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_headers_for_role(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary declared role and identity."""
    return build_user_headers(user_id, role)


__all__ = [
    "TEST_USERS",
    "ROLE_NAMES",
    "YARD_ADMIN_USER_ID",
    "CREDIT_MANAGER_USER_ID",
    "DISPATCH_PLANNER_USER_ID",
    "YARD_LOADER_USER_ID",
    "CLAIMS_ADJUSTER_USER_ID",
    "CONTRACTOR_USER_ID",
    "make_contractor_headers",
    "make_yard_admin_headers",
    "make_credit_manager_headers",
    "make_dispatch_planner_headers",
    "make_yard_loader_headers",
    "make_claims_adjuster_headers",
    "make_headers_for_role",
]
