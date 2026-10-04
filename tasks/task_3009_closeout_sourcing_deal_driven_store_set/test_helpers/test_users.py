"""Pre-built role headers for every role in the PRD.

Seven of the eight roles carry an opaque operator identifier as X-User-ID:
the server records it (for example as a lot's created_by_user_id) but never
compares it to a persisted entity id.  ClubMember is the exception: its
X-User-ID must equal the id of the LoyaltyMember it acts for, so member
headers are always built per instance with make_club_member_headers.

Anonymous is the only role permitted to omit X-User-ID entirely.
"""

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER = "admin-1"
BUYER_USER = "buyer-1"
BUYER_USER_ALT = "buyer-2"
SAFETY_OFFICER_USER = "so-1"
SAFETY_OFFICER_USER_ALT = "so-2"
PRICING_LEAD_USER = "pl-1"
ALLOCATION_MANAGER_USER = "am-1"
STORE_MANAGER_USER = "sm-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER, "Admin"),
    "sourcing_buyer_headers": build_user_headers(BUYER_USER, "SourcingBuyer"),
    "sourcing_buyer_alt_headers": build_user_headers(BUYER_USER_ALT, "SourcingBuyer"),
    "safety_officer_headers": build_user_headers(SAFETY_OFFICER_USER, "SafetyOfficer"),
    "safety_officer_alt_headers": build_user_headers(SAFETY_OFFICER_USER_ALT, "SafetyOfficer"),
    "pricing_lead_headers": build_user_headers(PRICING_LEAD_USER, "PricingLead"),
    "allocation_manager_headers": build_user_headers(ALLOCATION_MANAGER_USER, "AllocationManager"),
    "store_manager_headers": build_user_headers(STORE_MANAGER_USER, "StoreManager"),
    # Anonymous omits X-User-ID: role header only.
    "anonymous_headers": {"X-User-Role": "Anonymous", "Content-Type": "application/json"},
}


def make_admin_headers(user_id: str = ADMIN_USER) -> dict:
    return build_user_headers(user_id, "Admin")


def make_sourcing_buyer_headers(user_id: str = BUYER_USER) -> dict:
    return build_user_headers(user_id, "SourcingBuyer")


def make_safety_officer_headers(user_id: str = SAFETY_OFFICER_USER) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_pricing_lead_headers(user_id: str = PRICING_LEAD_USER) -> dict:
    return build_user_headers(user_id, "PricingLead")


def make_allocation_manager_headers(user_id: str = ALLOCATION_MANAGER_USER) -> dict:
    return build_user_headers(user_id, "AllocationManager")


def make_store_manager_headers(user_id: str = STORE_MANAGER_USER) -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_club_member_headers(member_id: str) -> dict:
    """For ClubMember: X-User-ID must equal the acting LoyaltyMember's id."""
    return build_user_headers(member_id, "ClubMember")


def make_anonymous_headers() -> dict:
    return {"X-User-Role": "Anonymous", "Content-Type": "application/json"}
