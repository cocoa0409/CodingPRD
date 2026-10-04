"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for opaque roles, and for tests that do not exercise
# ownership. For the entity-backed roles, prefer the per-instance builders below
# whenever the call is ownership-gated.
TEST_USERS = {
    "network_manager_headers": build_user_headers("test-network-manager-1", "DealerNetworkManager"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "DealerPerformanceReviewer"),
    "parts_manager_headers": build_user_headers("test-parts-manager-1", "PartsManager"),
    "rebuild_specialist_headers": build_user_headers("test-rebuild-specialist-1", "RebuildProgramSpecialist"),
    "technician_supervisor_headers": build_user_headers("test-technician-supervisor-1", "ServiceTechnicianSupervisor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "sales_manager_headers": build_user_headers("test-sales-manager-1", "DealerSalesManager"),
    "finance_partner_headers": build_user_headers("test-finance-partner-1", "FinancePartner"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "input_dealer_headers": build_user_headers("test-input-dealer-1", "InputDealer"),
}


def make_sales_manager_headers(user_id: str) -> dict:
    """For DealerSalesManager (entity_backed:Dealer). Pass the actual Dealer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "DealerSalesManager")


def make_input_dealer_headers(user_id: str) -> dict:
    """For InputDealer (entity_backed:Dealer). Pass the actual Dealer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "InputDealer")


__all__ = ["TEST_USERS", "make_sales_manager_headers", "make_input_dealer_headers"]