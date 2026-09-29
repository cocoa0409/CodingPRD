"""Pre-built role headers for every role named by the PRD.

Five of the six roles are opaque: their ``X-User-ID`` is any stable string.
``MerchantOperator`` is backed by a Merchant row — the PRD requires its
``X-User-ID`` to be the identifier of the merchant it acts for, so ownership
gated calls MUST use ``make_merchant_operator_headers(merchant["id"])``.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable user identifiers. Distinct identities within the same role matter for
# every ownership, reviewer and separation-of-duties rule in the contract.
PLATFORM_ADMIN_ID = "pa-1"
FLEET_DISPATCHER_ID = "fd-1"
FLEET_DISPATCHER_2_ID = "fd-2"
REMOTE_OPERATOR_ID = "ro-1"
REMOTE_OPERATOR_2_ID = "ro-2"
SAFETY_OFFICER_ID = "so-1"
SAFETY_OFFICER_2_ID = "so-2"
SAFETY_OFFICER_3_ID = "so-3"
CUSTOMER_SUPPORT_ID = "cs-1"

# Shared constants — safe for the opaque roles, and for any test that does not
# exercise merchant ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "fleet_dispatcher_headers": build_user_headers(FLEET_DISPATCHER_ID, "FleetDispatcher"),
    "fleet_dispatcher_2_headers": build_user_headers(FLEET_DISPATCHER_2_ID, "FleetDispatcher"),
    "remote_operator_headers": build_user_headers(REMOTE_OPERATOR_ID, "RemoteOperator"),
    "remote_operator_2_headers": build_user_headers(REMOTE_OPERATOR_2_ID, "RemoteOperator"),
    "safety_officer_headers": build_user_headers(SAFETY_OFFICER_ID, "SafetyOfficer"),
    "safety_officer_2_headers": build_user_headers(SAFETY_OFFICER_2_ID, "SafetyOfficer"),
    "safety_officer_3_headers": build_user_headers(SAFETY_OFFICER_3_ID, "SafetyOfficer"),
    "customer_support_headers": build_user_headers(CUSTOMER_SUPPORT_ID, "CustomerSupport"),
    # Fallback only — never use for an ownership-gated merchant call.
    "merchant_operator_headers": build_user_headers("merchant-operator-1", "MerchantOperator"),
}

# Convenience aliases for the shared constants.
ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["fleet_dispatcher_headers"]
OPERATOR = TEST_USERS["remote_operator_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]
SUPPORT = TEST_USERS["customer_support_headers"]


def make_merchant_operator_headers(merchant_id: str) -> dict:
    """Headers for a MerchantOperator acting for one merchant.

    ``merchant_id`` must be the identifier of the Merchant row the call
    touches; the server rejects any other identity on a merchant-owned row.
    """
    return build_user_headers(merchant_id, "MerchantOperator")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_fleet_dispatcher_headers(user_id: str = FLEET_DISPATCHER_ID) -> dict:
    return build_user_headers(user_id, "FleetDispatcher")


def make_remote_operator_headers(user_id: str = REMOTE_OPERATOR_ID) -> dict:
    return build_user_headers(user_id, "RemoteOperator")


def make_safety_officer_headers(user_id: str = SAFETY_OFFICER_ID) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_customer_support_headers(user_id: str = CUSTOMER_SUPPORT_ID) -> dict:
    return build_user_headers(user_id, "CustomerSupport")


NO_AUTH_HEADERS: dict = {"Content-Type": "application/json"}
"""Headers with no X-User-ID and no X-User-Role at all."""
