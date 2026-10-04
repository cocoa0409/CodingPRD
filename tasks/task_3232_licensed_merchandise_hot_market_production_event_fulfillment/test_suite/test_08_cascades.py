"""Transitive cascades: a design rejection, a press failure and a disposal."""
from test_helpers import validate_success
from test_helpers.fixtures import (
    FULFILLMENT,
    PLANNER,
    create_design,
    create_licensor,
    create_order,
    create_run,
    get_order,
    get_run,
    make_licensing_ops_headers,
    pick_order,
    print_layer,
    print_failure,
    set_clock,
)


def test_rejecting_a_design_retires_its_run_and_distresses_its_demand(api):
    """PRD §3.1: "Every production run whose `design_id` is this design is moved
    to `RETIRED_DESTROYED` with `retire_reason` set to `ASSORTMENT_CHANGED`,
    `retired_at` stamped, and the run's own version advanced by 1. Within each
    such run, every print layer is moved to `PRINT_FAILED` with `committed_qty`
    forced to 0 even where units had already been printed"
    PRD §3.1: "The cascade therefore reaches three levels deep — design, run,
    layer and the demand hanging off the layer"

    Design: Difficulty/transitive_cascade/design_rejection_three_hop_cascade
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Cascade", royalty_rate_pct=0.1,
                               minimum_guarantee_cents=1000000)
    design = create_design(api, licensor, team_code="ATL", garment_sku="TRACTOR",
                           design_name="ATL Cascade Tractor")
    run = create_run(
        api, licensor, design, team_code="ATL", trigger_type="CHAMPIONSHIP_WIN",
        event_outcome="WIN_FAVORED_TEAM", expected_demand_qty=20000,
        unit_cost_cents=900, win_probability_pct=0.5,
        outcome_at="2026-09-01T01:00:00Z",
    )
    committed = api.author_layers(
        run["id"],
        {
            "expected_production_order_version": run["version"],
            "layers": [{"print_type": "BASE", "quantity": 20000}],
        },
        PLANNER,
    )
    committed = validate_success(committed, expected_status=200)
    layer_id = committed["layer_ids"][0]
    print_layer(api, layer_id, 20000)

    order_x = create_order(api, committed, channel="ECOM",
                           destination_code="ECOM-ATL-1", quantity=250)
    order_y = create_order(api, committed, channel="ECOM",
                           destination_code="ECOM-ATL-2", quantity=250)
    pick_order(api, order_x, committed["id"], 250, "pick-c1")

    # Design.version has moved since the run was created; the reject carries the
    # version the design currently holds.
    current_design = validate_success(
        api.get_design(design["id"], PLANNER), expected_status=200,
    )
    reject = api.licensor_decision(
        design["id"],
        {
            "decision": "REJECT",
            "expected_design_version": current_design["version"],
            "rejection_reason": "Licensor withdrew the mark",
        },
        make_licensing_ops_headers(licensor["id"]),
    )
    validate_success(reject, expected_status=200)

    # Hop 1: the run is retired.
    retired = get_run(api, committed["id"])
    assert retired["status"] == "RETIRED_DESTROYED"
    assert retired["retire_reason"] == "ASSORTMENT_CHANGED"
    assert retired["retired_at"] is not None

    # Hop 2: the printed layer is forced to zero committed units.
    layer = validate_success(
        api.get_print_layer(layer_id, PLANNER), expected_status=200,
    )
    assert layer["layer_state"] == "PRINT_FAILED"
    assert layer["committed_qty"] == 0
    assert layer["printed_qty"] == 20000

    # Hop 3: the demand hanging off the layer is distressed and revalued to zero.
    for order in (order_x, order_y):
        read = get_order(api, order["id"])
        assert read["status"] == "DISTRESSED"
        assert read["requested_wholesale_cents"] == 0

    assert get_order(api, order_x["id"])["realized_wholesale_cents"] == 0


def test_a_press_failure_thins_the_pool_and_collapses_open_demand(api):
    """PRD §3.4: "The layer's `failed_qty` is increased by the supplied figure and
    `committed_qty` is recomputed as `printed_qty` less `failed_qty`. The parent
    run's `base_units_printed` or `accessory_units_printed` is then recomputed
    downward so that the failed layer's contribution is removed. From there the
    effect reaches demand: for each of the run's open fulfillment orders, the
    order's `requested_wholesale_cents` is scaled by the layer's committed
    quantity divided by the run's `quantity`, and any order whose recomputed total
    falls to zero or below is moved to `DISTRESSED` with `distress_reason`
    recorded as `DEMAND_COLLAPSE`."

    Design: Difficulty/transitive_cascade/print_failure_two_hop_rescale
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Fastprint", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="PHI", garment_sku="CAP",
                           design_name="PHI Fastprint Cap")
    run = create_run(api, licensor, design, team_code="PHI",
                     expected_demand_qty=5000)
    committed = api.author_layers(
        run["id"],
        {
            "expected_production_order_version": run["version"],
            "layers": [{"print_type": "BASE", "quantity": 20}],
        },
        PLANNER,
    )
    committed = validate_success(committed, expected_status=200)
    layer_id = committed["layer_ids"][0]
    print_layer(api, layer_id, 20)

    order = create_order(api, committed, channel="EVENT_POPUP",
                         destination_code="ATL_POPUP", quantity=100)
    assert order["requested_wholesale_cents"] == 900

    print_failure(api, layer_id, 20)

    assert get_run(api, committed["id"])["base_units_printed"] == 0

    collapsed = get_order(api, order["id"])
    assert collapsed["status"] == "DISTRESSED"
    assert collapsed["distress_reason"] == "DEMAND_COLLAPSE"
    assert collapsed["requested_wholesale_cents"] == 0


def test_a_retired_run_keeps_the_greater_write_down_through_a_late_return(api):
    """PRD §3.7: "The greater figure is retained on each target, so an
    order-level write-down strictly smaller than the run-level write-down already
    booked is skipped rather than layered on top of it."
    PRD §3.7: "a `STANDARD` run recovers 0.6 of cost, so it writes down the
    remaining 0.4"

    Design: Difficulty/compensating_invariant/unlacing_on_site_removes_second_party_liability
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Invariant", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="PHI", garment_sku="TRACTOR",
                           design_name="PHI Invariant Tractor")
    run = create_run(api, licensor, design, team_code="PHI",
                     expected_demand_qty=20000, unit_cost_cents=900)
    committed = api.author_layers(
        run["id"],
        {
            "expected_production_order_version": run["version"],
            "layers": [{"print_type": "BASE", "quantity": 200}],
        },
        PLANNER,
    )
    committed = validate_success(committed, expected_status=200)
    print_layer(api, committed["layer_ids"][0], 200)

    order = create_order(api, committed, channel="VENUE_RETAIL",
                         destination_code="PHI_TEAMSTORE", quantity=100)

    retired = validate_success(
        api.retire_production_order(
            committed["id"],
            {"retire_reason": "DEMAND_COLLAPSE", "destroy_mode": "DESTROY"},
            PLANNER,
        ),
        expected_status=200,
    )
    assert retired["status"] == "RETIRED_DESTROYED"
    assert retired["write_down_inventory_cents"] == 36000

    distressed = get_order(api, order["id"])
    assert distressed["status"] == "DISTRESSED"
    assert distressed["destroyed_qty"] == 100
    assert distressed["donated_qty"] == 0

    # A zero-quantity return moves no goods; the standing write-down is retained.
    api.return_order(order["id"], {"return_quantity": 0}, FULFILLMENT)

    after = get_run(api, committed["id"])
    assert after["write_down_inventory_cents"] == 36000
    assert get_order(api, order["id"])["donated_qty"] == 0