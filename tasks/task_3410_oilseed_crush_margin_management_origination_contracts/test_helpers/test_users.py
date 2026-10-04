"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed:
- Farmer: X-User-ID must be the acting Farmer's id; ownership checks compare
  it against a resource's farmer_id (mismatch -> ERR_FORBIDDEN).
- CommercialBuyer: X-User-ID must be the acting Buyer's id; compared against
  buyer_id.

The other eight roles are opaque: X-User-ID is an operator identifier never
compared to an entity id (though hedge positions record it as
entered_by_user_id / confirmed_by_user_id, and segregation of duties compares
those two recorded ids).

TEST_USERS holds one shared header set per role. For entity-backed roles the
shared constant is a fallback for tests that do NOT exercise ownership (404s,
400s); any ownership-gated call MUST go through make_farmer_headers /
make_commercial_buyer_headers with the real entity id. Segregation-of-duties
flows likewise need distinct user ids — use make_crush_trader_headers /
make_risk_manager_headers with explicit ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator ids. "trader-77" / "rm-1" / "rm-9" / "sched-1" are
# the ids the test scenarios name for hedge segregation-of-duties flows.
PLATFORM_ADMIN_USER_ID = "admin-1"
ORIGINATION_MERCHANDISER_USER_ID = "orig-merch-1"
CRUSH_TRADER_USER_ID = "trader-77"
RISK_MANAGER_USER_ID = "rm-1"
RISK_MANAGER_ALT_USER_ID = "rm-9"
PLANT_SCHEDULER_USER_ID = "sched-1"
LOGISTICS_COORDINATOR_USER_ID = "logi-1"
PRODUCT_MERCHANDISER_USER_ID = "prod-merch-1"
SUSTAINABILITY_AUDITOR_USER_ID = "sust-audit-1"
# Fallback ids for entity-backed roles — never equal to a real entity id, so
# only safe on paths without an ownership check.
FARMER_FALLBACK_USER_ID = "farmer-fallback-1"
COMMERCIAL_BUYER_FALLBACK_USER_ID = "buyer-fallback-1"


TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, "PlatformAdmin"
    ),
    "origination_merchandiser_headers": build_user_headers(
        ORIGINATION_MERCHANDISER_USER_ID, "OriginationMerchandiser"
    ),
    "farmer_headers": build_user_headers(FARMER_FALLBACK_USER_ID, "Farmer"),
    "crush_trader_headers": build_user_headers(CRUSH_TRADER_USER_ID, "CrushTrader"),
    "risk_manager_headers": build_user_headers(RISK_MANAGER_USER_ID, "RiskManager"),
    "plant_scheduler_headers": build_user_headers(
        PLANT_SCHEDULER_USER_ID, "PlantScheduler"
    ),
    "logistics_coordinator_headers": build_user_headers(
        LOGISTICS_COORDINATOR_USER_ID, "LogisticsCoordinator"
    ),
    "product_merchandiser_headers": build_user_headers(
        PRODUCT_MERCHANDISER_USER_ID, "ProductMerchandiser"
    ),
    "commercial_buyer_headers": build_user_headers(
        COMMERCIAL_BUYER_FALLBACK_USER_ID, "CommercialBuyer"
    ),
    "sustainability_auditor_headers": build_user_headers(
        SUSTAINABILITY_AUDITOR_USER_ID, "SustainabilityAuditor"
    ),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_origination_merchandiser_headers(
    user_id: str = ORIGINATION_MERCHANDISER_USER_ID,
) -> dict:
    return build_user_headers(user_id, "OriginationMerchandiser")


def make_farmer_headers(user_id: str) -> dict:
    """Farmer is entity-backed: pass the actual Farmer.id as user_id whenever
    the call is ownership-gated (contract reads / pricing elections)."""
    return build_user_headers(user_id, "Farmer")


def make_crush_trader_headers(user_id: str = CRUSH_TRADER_USER_ID) -> dict:
    return build_user_headers(user_id, "CrushTrader")


def make_risk_manager_headers(user_id: str = RISK_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "RiskManager")


def make_plant_scheduler_headers(user_id: str = PLANT_SCHEDULER_USER_ID) -> dict:
    return build_user_headers(user_id, "PlantScheduler")


def make_logistics_coordinator_headers(
    user_id: str = LOGISTICS_COORDINATOR_USER_ID,
) -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_product_merchandiser_headers(
    user_id: str = PRODUCT_MERCHANDISER_USER_ID,
) -> dict:
    return build_user_headers(user_id, "ProductMerchandiser")


def make_commercial_buyer_headers(user_id: str) -> dict:
    """CommercialBuyer is entity-backed: pass the actual Buyer.id as user_id
    whenever the call is ownership-gated (sales-contract reads)."""
    return build_user_headers(user_id, "CommercialBuyer")


def make_sustainability_auditor_headers(
    user_id: str = SUSTAINABILITY_AUDITOR_USER_ID,
) -> dict:
    return build_user_headers(user_id, "SustainabilityAuditor")


__all__ = [
    "TEST_USERS",
    "PLATFORM_ADMIN_USER_ID",
    "ORIGINATION_MERCHANDISER_USER_ID",
    "CRUSH_TRADER_USER_ID",
    "RISK_MANAGER_USER_ID",
    "RISK_MANAGER_ALT_USER_ID",
    "PLANT_SCHEDULER_USER_ID",
    "LOGISTICS_COORDINATOR_USER_ID",
    "PRODUCT_MERCHANDISER_USER_ID",
    "SUSTAINABILITY_AUDITOR_USER_ID",
    "FARMER_FALLBACK_USER_ID",
    "COMMERCIAL_BUYER_FALLBACK_USER_ID",
    "make_platform_admin_headers",
    "make_origination_merchandiser_headers",
    "make_farmer_headers",
    "make_crush_trader_headers",
    "make_risk_manager_headers",
    "make_plant_scheduler_headers",
    "make_logistics_coordinator_headers",
    "make_product_merchandiser_headers",
    "make_commercial_buyer_headers",
    "make_sustainability_auditor_headers",
]
