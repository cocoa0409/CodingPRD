"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics are normative per role:
- PortfolioManager / SupplyChainPlanner / FinanceController are OPAQUE: the
  X-User-ID is not compared to any entity id. Distinct opaque ids exist so the
  segregation-of-duties rule (decider != proposer) is expressible.
- BrandManager is entity-backed by Brand: X-User-ID must equal the managed
  Brand.id on ownership-gated calls (item/project creation).
- PlantDirector is entity-backed by Plant: X-User-ID must equal the transfer's
  target_plant_id when recording a qualification run.
- RetailerBuyer is entity-backed by Retailer: X-User-ID must equal the
  negotiation's retailer_id when responding.

For entity-backed roles, ALWAYS use the per-instance builder with the real
entity id on ownership-gated calls; the shared constants are fallbacks for
tests that never exercise ownership (e.g. role-denial before ownership runs).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # ── Opaque roles ─────────────────────────────────────────────────────────
    # Generic operator; safe wherever ownership is not entity-backed.
    "portfolio_manager_headers": build_user_headers("pm-1", "PortfolioManager"),
    # Distinct PortfolioManager identities for segregation of duties on
    # rationalization-case propose/decide (PRD §3.2: decider must differ from
    # proposer_user_id).
    "portfolio_manager_proposer_headers": build_user_headers(
        "pm-proposer-1", "PortfolioManager"
    ),
    "portfolio_manager_proposer_2_headers": build_user_headers(
        "pm-proposer-2", "PortfolioManager"
    ),
    "portfolio_manager_decider_headers": build_user_headers(
        "pm-decider-1", "PortfolioManager"
    ),
    "portfolio_manager_decider_2_headers": build_user_headers(
        "pm-decider-2", "PortfolioManager"
    ),
    "supply_chain_planner_headers": build_user_headers("scp-1", "SupplyChainPlanner"),
    "finance_controller_headers": build_user_headers("fc-1", "FinanceController"),
    # ── Entity-backed role fallbacks (non-ownership tests ONLY) ──────────────
    # These ids deliberately match no real entity; ownership-gated calls with
    # them are expected to fail ERR_OWNERSHIP_MISMATCH.
    "brand_manager_headers": build_user_headers("test-brand-manager-1", "BrandManager"),
    "plant_director_headers": build_user_headers("test-plant-director-1", "PlantDirector"),
    "retailer_buyer_headers": build_user_headers("test-retailer-buyer-1", "RetailerBuyer"),
}


# ── Per-instance builders for entity-backed roles (mandatory on gated calls) ──

def make_brand_manager_headers(brand_id: str) -> dict:
    """BrandManager identity bound to a real Brand.id (entity-backed).

    Use on POST /portfolio/items and POST /portfolio/innovation-projects when
    the caller is a BrandManager: X-User-ID must equal the payload's brand_id.
    """
    return build_user_headers(brand_id, "BrandManager")


def make_plant_director_headers(plant_id: str) -> dict:
    """PlantDirector identity bound to a real Plant.id (entity-backed).

    Use on POST /portfolio/product-transfers/{id}/qualification-runs:
    X-User-ID must equal the transfer's target_plant_id.
    """
    return build_user_headers(plant_id, "PlantDirector")


def make_retailer_buyer_headers(retailer_id: str) -> dict:
    """RetailerBuyer identity bound to a real Retailer.id (entity-backed).

    Use on POST /portfolio/combined-negotiations/{id}/respond:
    X-User-ID must equal the negotiation's retailer_id.
    """
    return build_user_headers(retailer_id, "RetailerBuyer")


def make_portfolio_manager_headers(user_id: str) -> dict:
    """Opaque PortfolioManager identity with a caller-chosen id."""
    return build_user_headers(user_id, "PortfolioManager")


def make_supply_chain_planner_headers(user_id: str) -> dict:
    """Opaque SupplyChainPlanner identity with a caller-chosen id."""
    return build_user_headers(user_id, "SupplyChainPlanner")


def make_finance_controller_headers(user_id: str) -> dict:
    """Opaque FinanceController identity with a caller-chosen id."""
    return build_user_headers(user_id, "FinanceController")


# ── Negative-auth header shapes (PRD §2.1 priorities 1-2) ────────────────────

def headers_without_role(user_id: str = "test-user-no-role") -> dict:
    """Headers carrying X-User-ID but NO X-User-Role (expect ERR_MISSING_ROLE)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "PortfolioManager") -> dict:
    """Headers carrying X-User-Role but NO X-User-ID (expect ERR_MISSING_USER_ID)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
