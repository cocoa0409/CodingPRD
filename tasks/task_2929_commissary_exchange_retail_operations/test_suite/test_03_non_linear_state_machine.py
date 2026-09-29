"""Lifecycles that are not a straight line.

A capital project can re-enter a state it already left, and a special order forks
on one call into two branches with different fiscal consequences before the
period-close checkpoint joins them again.
"""
from test_helpers import (
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    make_board_officer_headers,
    make_fund_controller_headers,
    validate_success,
)


def _scene_returned_project(api):
    """A project submitted once by sfc-001 and returned for revision by mwr-001."""
    store = fx.create_store(api, name="Norfolk Exchange", channel="EXCHANGE", region="CONUS")
    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Deli counter refresh",
                requested_amount_cents=100000,
            ),
            make_fund_controller_headers("sfc-001"),
        ),
        201,
    )
    validate_success(
        api.submit_capital_project(project["id"], None, make_fund_controller_headers("sfc-001")),
        200,
    )
    returned = validate_success(
        api.decide_capital_project(
            project["id"],
            factories.project_decision_payload("RETURN", note="Scope statement incomplete"),
            make_board_officer_headers("mwr-001"),
        ),
        200,
    )
    return {"store": store, "project": project, "returned": returned}


def test_resubmitting_a_returned_project_increments_revision_count_once(api):
    """One round trip through RETURNED_FOR_REVISION leaves revision_count at 1.

    PRD 3.9: "The two source states differ in exactly one respect: `DRAFT →
    SUBMITTED` leaves `revision_count` alone, while `RETURNED_FOR_REVISION →
    SUBMITTED` increments `revision_count` by 1, because that counter tallies only
    re-submissions."

    Design: Difficulty/non_linear_state_machine/capital_project_revision_cycle_increments_revision_count
    """
    scene = _scene_returned_project(api)

    project = validate_success(
        api.submit_capital_project(
            scene["project"]["id"], None, make_fund_controller_headers("sfc-001")
        ),
        200,
    )

    assert project["state"] == "SUBMITTED"
    assert project["revision_count"] == 1
    assert project["submitted_by_user_id"] == "sfc-001"
    assert project["decided_by_user_id"] == "mwr-001"


def test_the_return_clears_the_submitter_and_the_cycle_never_reprices_the_project(api):
    """RETURN nulls submitted_by_user_id; the re-submit re-stamps it and the money holds.

    PRD 3.9: "In addition to writing `decided_by_user_id`, it **clears
    `submitted_by_user_id` back to null**, because the next submission may come
    from a different controller and the segregation-of-duties check at close must
    reflect whoever submits last."

    Design: Difficulty/non_linear_state_machine/capital_project_revision_cycle_increments_revision_count
    """
    scene = _scene_returned_project(api)
    assert scene["returned"]["state"] == "RETURNED_FOR_REVISION"
    assert scene["returned"]["submitted_by_user_id"] is None
    assert scene["returned"]["revision_count"] == 0

    project = validate_success(
        api.submit_capital_project(
            scene["project"]["id"], None, make_fund_controller_headers("sfc-001")
        ),
        200,
    )
    assert project["submitted_by_user_id"] == "sfc-001"
    assert project["requested_amount_cents"] == 100000
    assert project["contingency_bp"] == 1000
    assert project["contingency_cents"] == 10000
    assert project["obligation_cents"] == 110000

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["surcharge_obligated_cents"] == 0


def _scene_two_submitted_orders(api):
    """Two identical overseas special orders, both still unrouted."""
    store = fx.create_store(api, name="Kadena Exchange", channel="EXCHANGE", region="OVERSEAS")
    product = fx.create_product(
        api,
        sku="SKU-GEN-900",
        name="Rice Cooker 5.5 cup",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=4000,
        unit_weight_grams=900,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="E5",
        facings=3,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="PO2 E Nakamura", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_05)
    order_local = fx.create_special_order(api, store["id"], patron["id"], product["id"], 8)
    order_ship = fx.create_special_order(api, store["id"], patron["id"], product["id"], 8)
    return {
        "store": store,
        "product": product,
        "patron": patron,
        "order_local": order_local,
        "order_ship": order_ship,
    }


def test_routing_forks_into_two_branches_with_divergent_freight(api):
    """The same call yields a zero-freight branch and a 1260-cent subsidised branch.

    PRD 3.8: "Whichever branch is taken, billable weight is computed the same way:
    the product's `unit_weight_grams` multiplied by the order's `quantity`,
    divided by one thousand, and **rounded up** to the next whole kilogram
    whenever there is any remainder."
    PRD 3.8: "The order will be filled from local stock, so no freight is incurred
    at all: `gross_ship_cents`, `patron_share_cents` and `shipping_allowance_cents`
    are all set to 0."

    Design: Difficulty/non_linear_state_machine/special_order_fork_join_local_fill_vs_overseas_ship
    """
    scene = _scene_two_submitted_orders(api)

    local = validate_success(
        api.route_special_order(
            scene["order_local"]["id"],
            factories.route_payload("LOCAL_FILL"),
            HEADERS_STORE_CASHIER,
        ),
        200,
    )
    ship = validate_success(
        api.route_special_order(
            scene["order_ship"]["id"],
            factories.route_payload("OVERSEAS_SHIP"),
            HEADERS_STORE_CASHIER,
        ),
        200,
    )

    assert local["route"] == "LOCAL_FILL"
    assert local["state"] == "LOCAL_FILL_PENDING"
    assert local["billable_weight_kg"] == 8
    assert local["gross_ship_cents"] == 0
    assert local["patron_share_cents"] == 0
    assert local["shipping_allowance_cents"] == 0

    assert ship["route"] == "OVERSEAS_SHIP"
    assert ship["state"] == "OVERSEAS_SHIP_PENDING"
    assert ship["billable_weight_kg"] == 8
    assert ship["gross_ship_cents"] == 1680
    assert ship["patron_share_cents"] == 420
    assert ship["shipping_allowance_cents"] == 1260

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["shipping_allowance_committed_cents"] == 1260


def test_period_close_joins_both_branches_without_releasing_the_commitment(api):
    """Both pending orders reach FULFILLED and the store still shows 1260 committed.

    PRD 3.8: "Fulfilment does **not** release the commitment: a `FULFILLED` order
    keeps its `shipping_allowance_cents` inside the store's
    `shipping_allowance_committed_cents`, because the money really was spent."

    Design: Difficulty/non_linear_state_machine/special_order_fork_join_local_fill_vs_overseas_ship
    """
    scene = _scene_two_submitted_orders(api)
    fx.route_special_order(api, scene["order_local"]["id"], "LOCAL_FILL")
    fx.route_special_order(api, scene["order_ship"]["id"], "OVERSEAS_SHIP")

    validate_success(api.close_period(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER), 200)

    local = validate_success(
        api.get_special_order(scene["order_local"]["id"], HEADERS_STORE_CASHIER)
    )
    ship = validate_success(api.get_special_order(scene["order_ship"]["id"], HEADERS_STORE_CASHIER))
    assert local["state"] == "FULFILLED"
    assert ship["state"] == "FULFILLED"
    assert ship["shipping_allowance_cents"] == 1260

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["shipping_allowance_committed_cents"] == 1260
    assert store["period_close_index"] == 1
