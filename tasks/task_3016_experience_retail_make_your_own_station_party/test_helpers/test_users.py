"""Pre-built role headers for every role in the PRD (§2.1).

Customer / WorkshopAssociate / PartyHost are entity-backed: any call gated on
ownership or staff identity MUST use the per-instance builders below with the
real entity id. The shared constants are safe only for opaque-role calls
(StoreManager) or tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "workshop_associate_headers": build_user_headers("test-associate-1", "WorkshopAssociate"),
    "party_host_headers": build_user_headers("test-party-host-1", "PartyHost"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id for ownership-gated calls."""
    return build_user_headers(user_id, "Customer")


def make_workshop_associate_headers(user_id: str) -> dict:
    """WorkshopAssociate is entity-backed (StaffMember): pass the actual StaffMember.id."""
    return build_user_headers(user_id, "WorkshopAssociate")


def make_party_host_headers(user_id: str) -> dict:
    """PartyHost is entity-backed (StaffMember): pass the actual StaffMember.id."""
    return build_user_headers(user_id, "PartyHost")


def make_store_manager_headers(user_id: str = "test-store-manager-1") -> dict:
    """StoreManager is opaque: any identifier works."""
    return build_user_headers(user_id, "StoreManager")
