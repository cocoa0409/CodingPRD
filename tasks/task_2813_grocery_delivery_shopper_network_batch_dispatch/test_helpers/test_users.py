"""Auth header builders for the five roles.

Customer, Shopper and RetailerManager are entity-backed: their X-User-ID must
equal the id of the Customer, Shopper or Retailer row they act for, so those
builders take that id. DispatchAdmin and CustomerSupport identities are
opaque operator identifiers that no ownership rule ever compares, so they are
pre-built constants.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CUSTOMER,
    ROLE_CUSTOMER_SUPPORT,
    ROLE_DISPATCH_ADMIN,
    ROLE_RETAILER_MANAGER,
    ROLE_SHOPPER,
)

# Opaque operator identities (any stable value works; ownership is never checked)
DISPATCH_ADMIN_USER_ID = "admin-dispatch-001"
CUSTOMER_SUPPORT_USER_ID = "support-agent-001"

ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    DISPATCH_ADMIN_USER_ID, ROLE_DISPATCH_ADMIN
)
SUPPORT_HEADERS: Dict[str, str] = build_user_headers(
    CUSTOMER_SUPPORT_USER_ID, ROLE_CUSTOMER_SUPPORT
)


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for the Customer whose Customer.id is `customer_id`."""
    return build_user_headers(customer_id, ROLE_CUSTOMER)


def make_shopper_headers(shopper_id: str) -> Dict[str, str]:
    """Headers for the Shopper whose Shopper.id is `shopper_id`."""
    return build_user_headers(shopper_id, ROLE_SHOPPER)


def make_retailer_manager_headers(retailer_id: str) -> Dict[str, str]:
    """Headers for the RetailerManager of the Retailer whose id is given."""
    return build_user_headers(retailer_id, ROLE_RETAILER_MANAGER)


def make_admin_headers(user_id: str = DISPATCH_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DISPATCH_ADMIN)


def make_support_headers(user_id: str = CUSTOMER_SUPPORT_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CUSTOMER_SUPPORT)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder used by role-matrix tests."""
    return build_user_headers(user_id, role)


# A convenient table for role-sweep tests: role name -> builder taking one id.
TEST_USERS = {
    ROLE_CUSTOMER: make_customer_headers,
    ROLE_SHOPPER: make_shopper_headers,
    ROLE_RETAILER_MANAGER: make_retailer_manager_headers,
    ROLE_DISPATCH_ADMIN: make_admin_headers,
    ROLE_CUSTOMER_SUPPORT: make_support_headers,
}


def headers_without_identity() -> Dict[str, str]:
    """Content-type only: no X-User-ID and no X-User-Role."""
    return {"Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user(role: str) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str, role: str = "StoreClerk") -> Dict[str, str]:
    return build_user_headers(user_id, role)
