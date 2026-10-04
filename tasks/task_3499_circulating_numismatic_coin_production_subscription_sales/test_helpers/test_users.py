"""Pre-built role headers for every role in the PRD (§2.1).

Ten roles are opaque (X-User-ID is an operator identifier never compared to an
entity id). Collector and BullionDealer are entity-backed: their X-User-ID IS
the id of the Collector / AuthorizedPurchaser entity, so any ownership-gated
call MUST use make_collector_headers(collector["id"]) /
make_bullion_dealer_headers(purchaser["id"]) — never the shared fallback.

Segregation of duties (PRD §2.10) needs distinct, stable user ids:
  - disburser (FinanceOfficer) != program creator (ProgramManager pm-1)
  - settler (FinanceOfficer) != offerer (ProgramManager pm-9)
  - destruction certifiers dc-1..dc-4 distinct from each other and from the
    reporting inspector (qi-1)
For cross-role same-id scenarios (e.g. a FinanceOfficer whose id equals the
offering ProgramManager's id), use make_headers(user_id, role).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Stable opaque user ids (referenced by name in test recipes) ---------------
ANONYMOUS_USER_ID = "anon-1"
PLATFORM_ADMIN_USER_ID = "admin-1"
FED_LIAISON_USER_ID = "fed-1"
PROCUREMENT_OFFICER_USER_ID = "proc-1"
PRODUCTION_PLANNER_USER_ID = "plan-1"
QUALITY_INSPECTOR_USER_ID = "qi-1"
QUALITY_INSPECTOR_ALT_USER_ID = "qi-9"
DESTRUCTION_CERTIFIER_1_USER_ID = "dc-1"
DESTRUCTION_CERTIFIER_2_USER_ID = "dc-2"
DESTRUCTION_CERTIFIER_3_USER_ID = "dc-3"
DESTRUCTION_CERTIFIER_4_USER_ID = "dc-4"
PROGRAM_MANAGER_USER_ID = "pm-1"
PROGRAM_MANAGER_ALT_USER_ID = "pm-9"
MINT_DIRECTOR_USER_ID = "director-1"
FINANCE_OFFICER_USER_ID = "fin-1"
FINANCE_OFFICER_ALT_USER_ID = "fin-9"
# Fallback ids for entity-backed roles — ONLY for tests whose outcome does not
# depend on the caller owning a specific resource (400/403/404 checks).
COLLECTOR_FALLBACK_USER_ID = "collector-fallback-1"
BULLION_DEALER_FALLBACK_USER_ID = "ap-fallback-1"

# --- Shared header constants -----------------------------------------------------
TEST_USERS = {
    "anonymous_headers": build_user_headers(ANONYMOUS_USER_ID, UserRole.ANONYMOUS.value),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value),
    "fed_liaison_headers": build_user_headers(FED_LIAISON_USER_ID, UserRole.FED_LIAISON.value),
    "procurement_officer_headers": build_user_headers(PROCUREMENT_OFFICER_USER_ID, UserRole.PROCUREMENT_OFFICER.value),
    "production_planner_headers": build_user_headers(PRODUCTION_PLANNER_USER_ID, UserRole.PRODUCTION_PLANNER.value),
    "quality_inspector_headers": build_user_headers(QUALITY_INSPECTOR_USER_ID, UserRole.QUALITY_INSPECTOR.value),
    "quality_inspector_alt_headers": build_user_headers(QUALITY_INSPECTOR_ALT_USER_ID, UserRole.QUALITY_INSPECTOR.value),
    "destruction_certifier_1_headers": build_user_headers(DESTRUCTION_CERTIFIER_1_USER_ID, UserRole.DESTRUCTION_CERTIFIER.value),
    "destruction_certifier_2_headers": build_user_headers(DESTRUCTION_CERTIFIER_2_USER_ID, UserRole.DESTRUCTION_CERTIFIER.value),
    "destruction_certifier_3_headers": build_user_headers(DESTRUCTION_CERTIFIER_3_USER_ID, UserRole.DESTRUCTION_CERTIFIER.value),
    "destruction_certifier_4_headers": build_user_headers(DESTRUCTION_CERTIFIER_4_USER_ID, UserRole.DESTRUCTION_CERTIFIER.value),
    "program_manager_headers": build_user_headers(PROGRAM_MANAGER_USER_ID, UserRole.PROGRAM_MANAGER.value),
    "program_manager_alt_headers": build_user_headers(PROGRAM_MANAGER_ALT_USER_ID, UserRole.PROGRAM_MANAGER.value),
    "mint_director_headers": build_user_headers(MINT_DIRECTOR_USER_ID, UserRole.MINT_DIRECTOR.value),
    "finance_officer_headers": build_user_headers(FINANCE_OFFICER_USER_ID, UserRole.FINANCE_OFFICER.value),
    "finance_officer_alt_headers": build_user_headers(FINANCE_OFFICER_ALT_USER_ID, UserRole.FINANCE_OFFICER.value),
    # Entity-backed fallbacks: non-ownership tests only.
    "collector_headers": build_user_headers(COLLECTOR_FALLBACK_USER_ID, UserRole.COLLECTOR.value),
    "bullion_dealer_headers": build_user_headers(BULLION_DEALER_FALLBACK_USER_ID, UserRole.BULLION_DEALER.value),
}


# --- Per-instance builders ---------------------------------------------------------
def make_collector_headers(collector_id: str) -> dict:
    """Collector is entity-backed: pass the actual Collector.id as collector_id
    whenever the call is ownership-gated (orders, subscriptions, invoices)."""
    return build_user_headers(collector_id, UserRole.COLLECTOR.value)


def make_bullion_dealer_headers(authorized_purchaser_id: str) -> dict:
    """BullionDealer is entity-backed: pass the actual AuthorizedPurchaser.id
    whenever the call is ownership-gated (allocation confirm)."""
    return build_user_headers(authorized_purchaser_id, UserRole.BULLION_DEALER.value)


def make_headers(user_id: str, role: str) -> dict:
    """Ad-hoc headers for any (user_id, role) pair — e.g. a FinanceOfficer whose
    id deliberately equals the offering ProgramManager's id for a
    segregation-of-duties rejection test."""
    return build_user_headers(user_id, role)
