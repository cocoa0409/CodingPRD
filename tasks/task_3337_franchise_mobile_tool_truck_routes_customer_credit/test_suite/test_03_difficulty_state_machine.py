"""Difficulty queue A — non_linear_state_machine: cyclic and parallel axes."""
from test_helpers import (
    MANAGER,
    activate_route,
    advance_route,
    api_client,
    advance_territory,
    create_certified_franchisee,
    create_route,
    create_shop,
    get_franchisee,
    get_route,
    get_shop,
    qualify_territory,
    api_client,
    set_clock,
    validate_success,
)


def test_franchisee_and_route_cycles_return_through_their_back_edges(api):
    """PRD §3.1: "Recertifying moves `CERTIFIED` back to `ENROLLED`,
    clears `certified_on` to null, and recomputes `can_resell_territory` to false."
    PRD §3.1: "Reinstatement moves
    `SUSPENDED` back to `IN_SERVICE`, and it deliberately does not reopen the shops that suspension
    closed: a shop left `INACTIVE` by suspension stays `INACTIVE` until it is deliberately reactivated."

    Design: Difficulty/non_linear_state_machine/non_linear_cyclic_loops_on_franchisee_and_route
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    activate_route(franchisee, route)
    shop = create_shop(franchisee, route)

    validate_success(advance_route(franchisee, route, "SUSPEND"))
    assert get_shop(shop["id"])["shop_status"] == "INACTIVE"
    reinstated = validate_success(advance_route(franchisee, route, "REINSTATE"))
    assert reinstated["route_status"] == "IN_SERVICE"

    recertified = validate_success(api_client.advance_training(
        franchisee["id"], {"action": "RECERTIFY", "training_points": 45},
        franchisee["owner_headers"]))
    assert recertified["training_status"] == "ENROLLED"
    assert recertified["can_resell_territory"] is False
    assert recertified["certified_on"] is None

    assert get_shop(shop["id"])["shop_status"] == "INACTIVE", (
        "the reinstate back-edge does not reopen the shops suspension closed")
    assert get_route(route["id"])["route_status"] == "IN_SERVICE"
    assert get_franchisee(franchisee["id"])["active_route_count"] == 1


def test_route_axes_move_independently_of_one_another(api):
    """PRD §3.1: "Territory development is a second, independent axis on the same route, and it does not track
    `route_status`."
    PRD §3.1: "approval moves `PENDING` to `APPROVED` and is permitted only while
    `reopening_fee_cents` is at most `FRANCHISEE_RESALE_FEE_CAP_CENTS`, while a decline moves `PENDING` to
    `DECLINED` with no fee test."

    Design: Difficulty/non_linear_state_machine/non_linear_parallel_dimensions_on_route
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    activate_route(franchisee, route)
    qualified = validate_success(advance_territory(franchisee, route, "DEVELOP", 90))
    assert qualified["territory_development_status"] == "QUALIFIED"

    filed = validate_success(api_client.resale_action(
        route["id"], {"action": "FILE", "buyer_training_status": "ENROLLED",
                      "buyer_training_points": 10}, franchisee["owner_headers"]))
    assert filed["resale_status"] == "PENDING"
    assert filed["reopening_fee_cents"] == 635000, "650000 base less one 15000 discount unit"

    declined = validate_success(api_client.resale_action(route["id"], {"action": "DECLINE"},
                                              MANAGER))
    assert declined["resale_status"] == "DECLINED"

    final = get_route(route["id"])
    assert final["resale_status"] == "DECLINED"
    assert final["route_status"] == "IN_SERVICE", "the resale axis moved alone"
    assert final["territory_development_status"] == "QUALIFIED", "the territory axis moved alone"
