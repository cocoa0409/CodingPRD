"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# `Buyer` is entity_backed: the shared constant is a fallback for tests that do
# not exercise ownership; ownership-gated calls MUST use make_buyer_headers().
# Every other role is opaque, so the shared constant is the canonical form.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "delivery_advisor_headers": build_user_headers("test-advisor-1", "DeliveryAdvisor"),
    "trade_in_specialist_headers": build_user_headers("test-tradein-1", "TradeInSpecialist"),
    "finance_partner_headers": build_user_headers("test-finance-1", "FinancePartner"),
    "service_technician_headers": build_user_headers("test-tech-1", "ServiceTechnician"),
    "parts_coordinator_headers": build_user_headers("test-parts-1", "PartsCoordinator"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_buyer_headers(user_id: str) -> dict:
    """For Buyer (entity_backed:Buyer). Pass the actual Buyer.id as user_id
    whenever the call is ownership-gated (placing an order, changing its
    configuration, cancelling it, accepting or rejecting an offer, or filing
    and funding a financing application against it)."""
    return build_user_headers(user_id, "Buyer")