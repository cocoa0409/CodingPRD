"""Pre-built role headers for every role in the PRD.

Six of the seven roles are opaque: their X-User-ID is an arbitrary operator
string that the service records in the provenance fields and compares only
against another operator string when a segregation-of-duties rule applies.

Buyer is entity-backed: its X-User-ID must be the id of a Buyer row, so an
ownership-gated Buyer call must always be made through make_buyer_headers().
"""

from prd_bench_local_runner.testing import build_user_headers

SALES_AGENT_USER = "agent-mara"
SALES_AGENT_USER_ALT = "agent-tobias"
HEAD_OF_SALES_USER = "hos-signer-1"
HEAD_OF_SALES_VALUER = "hos-valuer-1"
HEAD_OF_SALES_CLOSER = "hos-closer-9"
DELIVERY_MANAGER_USER = "delivery-ines"
COLLECTION_AGENT_USER = "collect-1"
COLLECTION_AGENT_USER_ALT = "collect-2"
LENDER_USER = "lender-ops-0"
LENDER_APPROVER = "lender-approver-1"
LENDER_APPROVER_ALT = "lender-approver-2"
LENDER_DRAWER = "lender-drawer-2"
PLATFORM_ADMIN_USER = "admin-1"

TEST_USERS = {
    "sales_agent_headers": build_user_headers(SALES_AGENT_USER, "SalesAgent"),
    "head_of_sales_headers": build_user_headers(HEAD_OF_SALES_USER, "HeadOfSales"),
    "delivery_manager_headers": build_user_headers(DELIVERY_MANAGER_USER, "DeliveryManager"),
    "collection_agent_headers": build_user_headers(COLLECTION_AGENT_USER, "CollectionAgent"),
    "lender_headers": build_user_headers(LENDER_USER, "Lender"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER, "PlatformAdmin"),
    # Buyer is entity-backed: this shared constant can never satisfy an
    # ownership check, so it is only for role-grant probes on read endpoints.
    "buyer_headers_unowned": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "Buyer"
    ),
    # A recognised header pair for a role name that §2.1 does not declare.
    "unknown_role_headers": build_user_headers("nobody-1", "Projectionist"),
}


def make_sales_agent_headers(user_id: str = SALES_AGENT_USER):
    return build_user_headers(user_id, "SalesAgent")


def make_head_of_sales_headers(user_id: str = HEAD_OF_SALES_USER):
    return build_user_headers(user_id, "HeadOfSales")


def make_delivery_manager_headers(user_id: str = DELIVERY_MANAGER_USER):
    return build_user_headers(user_id, "DeliveryManager")


def make_collection_agent_headers(user_id: str = COLLECTION_AGENT_USER):
    return build_user_headers(user_id, "CollectionAgent")


def make_lender_headers(user_id: str = LENDER_USER):
    return build_user_headers(user_id, "Lender")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER):
    return build_user_headers(user_id, "PlatformAdmin")


def make_buyer_headers(buyer_id: str):
    """Buyer identity is the Buyer row id (§2.1 entity-backed role)."""
    return build_user_headers(buyer_id, "Buyer")


ROLE_NAMES = (
    "SalesAgent",
    "HeadOfSales",
    "Buyer",
    "DeliveryManager",
    "CollectionAgent",
    "Lender",
    "PlatformAdmin",
)

# Headers with no X-User-Role at all, and headers with no identity at all.
NO_ROLE_HEADERS = {"X-User-ID": PLATFORM_ADMIN_USER, "Content-Type": "application/json"}
NO_USER_HEADERS = {"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"}
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
