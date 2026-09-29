"""Auth header builders for every role in the parcel billing API.

Four of the five roles carry opaque operator identities, so a stable module
level header dict is enough for them. Segregation of duties compares the
applying operator's ``X-User-ID`` against the proposer's, so two distinct
BillingOps identities are provided and must be used deliberately.

The fifth role, ShipperUser, is entity backed: its ``X-User-ID`` must be the
UUID of the ShipperAccount it acts for. There is therefore no module level
ShipperUser header dict — callers must build one per account with
``make_shipper_user_headers(shipper_account_id)``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BILLING_OPS,
    ROLE_CARRIER_ADMIN,
    ROLE_CARRIER_OPS,
    ROLE_REVENUE_AUDITOR,
    ROLE_SHIPPER_USER,
)

# --- opaque operator identities -------------------------------------------
CARRIER_ADMIN_USER_ID = "admin.one"
CARRIER_ADMIN_ALT_USER_ID = "admin.two"
CARRIER_OPS_USER_ID = "ops.one"
CARRIER_OPS_ALT_USER_ID = "ops.two"
BILLING_OPS_USER_ID = "billing.one"
BILLING_OPS_ALT_USER_ID = "billing.two"
REVENUE_AUDITOR_USER_ID = "auditor.one"
REVENUE_AUDITOR_ALT_USER_ID = "auditor.two"

CARRIER_ADMIN_HEADERS = build_user_headers(CARRIER_ADMIN_USER_ID, ROLE_CARRIER_ADMIN)
CARRIER_ADMIN_ALT_HEADERS = build_user_headers(
    CARRIER_ADMIN_ALT_USER_ID, ROLE_CARRIER_ADMIN
)
CARRIER_OPS_HEADERS = build_user_headers(CARRIER_OPS_USER_ID, ROLE_CARRIER_OPS)
CARRIER_OPS_ALT_HEADERS = build_user_headers(CARRIER_OPS_ALT_USER_ID, ROLE_CARRIER_OPS)
BILLING_OPS_HEADERS = build_user_headers(BILLING_OPS_USER_ID, ROLE_BILLING_OPS)
BILLING_OPS_ALT_HEADERS = build_user_headers(BILLING_OPS_ALT_USER_ID, ROLE_BILLING_OPS)
REVENUE_AUDITOR_HEADERS = build_user_headers(
    REVENUE_AUDITOR_USER_ID, ROLE_REVENUE_AUDITOR
)
REVENUE_AUDITOR_ALT_HEADERS = build_user_headers(
    REVENUE_AUDITOR_ALT_USER_ID, ROLE_REVENUE_AUDITOR
)


def make_carrier_admin_headers(user_id: str) -> Dict[str, str]:
    """CarrierAdmin headers for a caller-chosen opaque operator id."""
    return build_user_headers(user_id, ROLE_CARRIER_ADMIN)


def make_carrier_ops_headers(user_id: str) -> Dict[str, str]:
    """CarrierOps headers for a caller-chosen opaque operator id."""
    return build_user_headers(user_id, ROLE_CARRIER_OPS)


def make_billing_ops_headers(user_id: str) -> Dict[str, str]:
    """BillingOps headers for a caller-chosen opaque operator id.

    Use two different ids across a propose/apply pair, otherwise the
    segregation-of-duties rule rejects the release.
    """
    return build_user_headers(user_id, ROLE_BILLING_OPS)


def make_revenue_auditor_headers(user_id: str) -> Dict[str, str]:
    """RevenueAuditor headers for a caller-chosen opaque operator id."""
    return build_user_headers(user_id, ROLE_REVENUE_AUDITOR)


def make_shipper_user_headers(shipper_account_id: str) -> Dict[str, str]:
    """ShipperUser headers whose X-User-ID is the ShipperAccount's own UUID.

    ShipperUser is an entity-backed role: the identity in the header IS the
    account it may reach, and any other account's data is out of scope.
    """
    return build_user_headers(shipper_account_id, ROLE_SHIPPER_USER)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role string, including unknown ones.

    Useful for role-recognition and permission matrices where the role name is
    the parameter under test.
    """
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that carry X-User-Role but omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that carry X-User-ID but omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_no_auth() -> Dict[str, str]:
    """Headers that carry neither identity header."""
    return {"Content-Type": "application/json"}
