"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For SellerAgent (entity-backed by Seller) and Buyer
# (entity-backed by Member) the shared constants are fallbacks only;
# ownership-gated calls must use make_seller_agent_headers /
# make_buyer_headers with the actual entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "yard_operator_headers": build_user_headers("test-yard-operator-1", "YardOperator"),
    "auctioneer_headers": build_user_headers("test-auctioneer-1", "Auctioneer"),
    "title_clerk_headers": build_user_headers("test-title-clerk-1", "TitleClerk"),
    "seller_agent_headers": build_user_headers("test-seller-agent-1", "SellerAgent"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_seller_agent_headers(seller_id: str) -> dict:
    """For SellerAgent (entity-backed by Seller): X-User-ID must equal the
    acting Seller.id whenever the call is ownership-gated (vehicle assignment,
    vehicle cancel, on-approval approve/reject, sale cancel)."""
    return build_user_headers(seller_id, "SellerAgent")


def make_buyer_headers(member_id: str) -> dict:
    """For Buyer (entity-backed by Member): X-User-ID must equal the acting
    Member.id whenever the call is ownership-gated (bids, payments, gate-pass
    booking, export-document submission)."""
    return build_user_headers(member_id, "Buyer")
