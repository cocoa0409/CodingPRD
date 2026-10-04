"""Pre-built role headers for the six roles in the PRD (§2.1).

Identity model (PRD §2.1): five roles carry an opaque operator identifier in
``X-User-ID`` that the server never compares to any entity ``id`` — the shared
constants below are canonical for them. ``RetailerBuyer`` is different: its
``X-User-ID`` IS the ``id`` of the acting ``Retailer``, and every ownership
check compares it against the ``retailer_id`` of the plan that owns the target
resource. For any ownership-gated call, use ``make_retailer_buyer_headers``
with the actual retailer id — the shared ``retailer_buyer_headers`` constant
exists only for tests whose outcome does not depend on retailer ownership
(e.g. 400-on-bad-payload or 404-on-missing-resource probes).
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", UserRole.PLATFORM_ADMIN.value),
    "manufacturer_planner_headers": build_user_headers("test-manufacturer-planner-1", UserRole.MANUFACTURER_PLANNER.value),
    "category_advisor_headers": build_user_headers("test-category-advisor-1", UserRole.CATEGORY_ADVISOR.value),
    "supply_chain_planner_headers": build_user_headers("test-supply-chain-planner-1", UserRole.SUPPLY_CHAIN_PLANNER.value),
    "finance_analyst_headers": build_user_headers("test-finance-analyst-1", UserRole.FINANCE_ANALYST.value),
    # Entity-backed role (RetailerBuyer -> Retailer.id): fallback for
    # non-ownership tests only; ownership-gated calls MUST use
    # make_retailer_buyer_headers(retailer["id"]).
    "retailer_buyer_headers": build_user_headers("test-retailer-buyer-1", UserRole.RETAILER_BUYER.value),
}


def make_retailer_buyer_headers(user_id: str) -> dict:
    """Headers for the entity-backed RetailerBuyer role.

    Pass the actual ``Retailer.id`` as ``user_id`` whenever the call is
    ownership-gated (negotiate/decide on the buyer's own plan, analysis and
    shelf-rec and price-pack decides, deduction filing, forecast commit,
    review finalize, and any RetailerBuyer read of plan-scoped data).
    """
    return build_user_headers(user_id, UserRole.RETAILER_BUYER.value)


def make_headers(user_id: str, role: str) -> dict:
    """Generic header builder for ad-hoc identities (e.g. an unrecognized role
    name for the 401 authentication probes)."""
    return build_user_headers(user_id, role)
