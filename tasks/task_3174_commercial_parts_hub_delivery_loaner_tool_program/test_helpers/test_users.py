"""Pre-built role headers for every role the API recognizes.

`CommercialSalesRep` is the only entity-backed role: its `X-User-ID` is the
`id` of the acting `SalesRep`. Ownership checks that reach a resource through
that rep's `rep_id` must therefore call `make_commercial_sales_rep_headers()`
with a real entity id. Every other role carries an opaque operator id, so the
shared constant is the canonical form for those.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "CommercialSalesRep"),
    "driver_headers": build_user_headers("test-driver-1", "DeliveryDriver"),
    "tool_crib_headers": build_user_headers("test-tool-crib-1", "ToolCribAttendant"),
    "credit_analyst_headers": build_user_headers("test-credit-analyst-1", "CreditAnalyst"),
    "route_dispatcher_headers": build_user_headers("test-route-dispatcher-1", "RouteDispatcher"),
    "parts_manager_headers": build_user_headers("test-parts-manager-1", "PartsCategoryManager"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


def make_commercial_sales_rep_headers(user_id: str) -> dict:
    """For CommercialSalesRep, whose identity is `entity_backed:SalesRep`.

    Pass the actual SalesRep.id whenever the call is ownership-gated (any
    request whose path or body references that rep's `rep_id`).
    """
    return build_user_headers(user_id, "CommercialSalesRep")


def make_delivery_driver_headers(user_id: str) -> dict:
    """Opaque role; provided for symmetric call sites."""
    return build_user_headers(user_id, "DeliveryDriver")


def make_tool_crib_attendant_headers(user_id: str) -> dict:
    """Opaque role; provided for symmetric call sites."""
    return build_user_headers(user_id, "ToolCribAttendant")


def make_credit_analyst_headers(user_id: str) -> dict:
    """Opaque role; provided for symmetric call sites."""
    return build_user_headers(user_id, "CreditAnalyst")


def make_route_dispatcher_headers(user_id: str) -> dict:
    """Opaque role; provided for symmetric call sites."""
    return build_user_headers(user_id, "RouteDispatcher")


def make_parts_category_manager_headers(user_id: str) -> dict:
    """Opaque role; provided for symmetric call sites."""
    return build_user_headers(user_id, "PartsCategoryManager")


def make_platform_admin_headers(user_id: str) -> dict:
    """Opaque role; provided for symmetric call sites."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_any_headers(user_id: str) -> dict:
    """Opaque role; provided for symmetric call sites."""
    return build_user_headers(user_id, "Any")