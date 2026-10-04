"""Returns, distress and retiring the losing side."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    FULFILLMENT,
    PLANNER,
    committed_run,
    create_order,
    get_order,
    get_run,
    pick_order,
    print_failure,
    print_layer,
    set_clock,
)


def test_a_standard_write_down_survives_its_own_recomputation(api):
    """PRD §3.7: "a `STANDARD` run recovers 0.6 of cost, so it writes down the
    remaining 0.4"
    PRD §3.7: "The greater figure is retained on each target, so an order-level
    write-down strictly smaller than the run-level write-down already booked is
    skipped rather than layered on top of it."

    Design: Corner/calculations/write_down_greater_charge_survives_lesser
    """
    set_clock(api)
    setup = committed_run(api, base_qty=200, unit_cost_cents=900)
    create_order(api, setup["run"], channel="VENUE_RETAIL",
                 destination_code="BOS_VENUE", quantity=100)

    retired = validate_success(
        api.retire_production_order(
            setup["run"]["id"],
            {"retire_reason": "LOSING_OUTCOME", "destroy_mode": "DESTROY"},
            PLANNER,
        ),
        expected_status=200,
    )

    assert retired["status"] == "RETIRED_DESTROYED"
    assert retired["destroyed_units"] == 100
    assert retired["donated_units"] == 0
    assert retired["write_down_inventory_cents"] == 36000

    read = get_run(api, setup["run"]["id"])
    assert read["write_down_inventory_cents"] == 36000


def test_a_destroyed_run_whose_units_all_failed_books_no_write_down(api):
    """PRD §3.7: "the quantity the run actually lost — its destroyed units and its
    donated units as `destroyed_units` and `donated_units` record them -
    multiplied by the run's `unit_cost_cents`, multiplied by the share of cost
    that cannot be recovered."

    Design: Corner/calculations/writing_down_a_second_time_does_not_stack
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20, unit_cost_cents=900)
    print_layer(api, setup["base_layer_id"], 20)
    print_failure(api, setup["base_layer_id"], 5)

    after_failure = get_run(api, setup["run"]["id"])
    assert after_failure["base_units_printed"] == 15
    layer = validate_success(
        api.get_print_layer(setup["base_layer_id"], PLANNER), expected_status=200,
    )
    assert layer["failed_qty"] == 5
    assert layer["committed_qty"] == 15

    retired = validate_success(
        api.retire_production_order(
            setup["run"]["id"],
            {"retire_reason": "DEMAND_COLLAPSE", "destroy_mode": "DESTROY"},
            PLANNER,
        ),
        expected_status=200,
    )
    assert retired["status"] == "RETIRED_DESTROYED"
    assert retired["destroyed_units"] == 0
    assert retired["write_down_inventory_cents"] == 0


def test_a_distress_on_the_destroy_branch_revalues_an_order_to_the_penalty_rate(api):
    """PRD §3.7: "on the `DESTROY` branch the order's `destroyed_qty` is set to
    its full `quantity`, its `donated_qty` is left at 0, and its
    `requested_wholesale_cents` is rewritten to the units valued at the destroy
    penalty rate of 4 cents per unit. ... Both branches set
    `realized_wholesale_cents` to 0"

    Design: Corner/consistency_model/distressed_cascade_is_visible_on_the_very_next_read
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    order = create_order(api, setup["run"], channel="VENUE_RETAIL",
                         destination_code="PHI_TEAMSTORE", quantity=100)

    distressed = validate_success(
        api.distress(
            order["id"],
            {"distress_reason": "DEMAND_COLLAPSE", "destroy_mode": "DESTROY"},
            FULFILLMENT,
        ),
        expected_status=200,
    )

    assert distressed["status"] == "DISTRESSED"
    assert distressed["distress_reason"] == "DEMAND_COLLAPSE"
    assert distressed["destroyed_qty"] == 100
    assert distressed["donated_qty"] == 0
    assert distressed["requested_wholesale_cents"] == 400
    assert distressed["realized_wholesale_cents"] == 0


def test_a_distress_without_a_donation_recipient_is_refused(api):
    """PRD §3.7: "Electing the `DONATE` branch without also supplying a
    `donation_recipient_code` is a request-shape failure reported as
    `ERR_INVALID_REQUEST` (HTTP 400), because a donation without a named
    recipient is not a donation."

    Design: Corner/errors/lot_exhausted_when_every_unit_is_already_moved
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-4", quantity=50)

    resp = api.distress(
        order["id"],
        {"distress_reason": "DEMAND_COLLAPSE", "destroy_mode": "DONATE"},
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_a_distress_on_the_donate_branch_moves_units_without_a_penalty(api):
    """PRD §3.7: "On the `DONATE` branch the order's `donated_qty` is set to its
    full `quantity`, its `destroyed_qty` is left at 0, and its
    `requested_wholesale_cents` is rewritten at the donate penalty rate, which is
    zero, so a donated order's requested total is zero."

    Design: Corner/consistency_model/distressed_cascade_is_visible_on_the_very_next_read
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-5", quantity=80)

    distressed = validate_success(
        api.distress(
            order["id"],
            {
                "distress_reason": "DAMAGED_ON_SITE",
                "destroy_mode": "DONATE",
                "donation_recipient_code": "RECIPIENT_1",
            },
            FULFILLMENT,
        ),
        expected_status=200,
    )

    assert distressed["donated_qty"] == 80
    assert distressed["destroyed_qty"] == 0
    assert distressed["requested_wholesale_cents"] == 0
    assert distressed["realized_wholesale_cents"] == 0
    assert distressed["status"] == "DISTRESSED"


def test_a_return_of_more_than_was_shipped_is_refused(api):
    """PRD §3.7: "the one bound on the request is that the `return_quantity` must
    not exceed the order's shipped quantity — a return larger than what went out
    is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/errors/lot_exhausted_when_every_unit_is_already_moved
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-20", quantity=50)
    pick_order(api, order, setup["run"]["id"], 50, "pick-ret")
    validate_success(
        api.ship(order["id"], {"quantity": 50, "carrier": "GROUND",
                               "sla_hours": 48}, FULFILLMENT),
        expected_status=201,
    )

    resp = api.return_order(order["id"], {"return_quantity": 60}, FULFILLMENT)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)


def test_a_return_recognizes_recovery_less_the_returned_units_at_cost(api):
    """PRD §3.7: "Recovery is recognized as the request-time wholesale total less
    the returned units valued at the run's `unit_cost_cents`, floored at zero and
    rounded half up: that difference is written to `realized_wholesale_cents`"

    Design: Difficulty/compensating_invariant/unlacing_on_site_removes_second_party_liability
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000, unit_cost_cents=900)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-21", quantity=250)
    pick_order(api, order, setup["run"]["id"], 250, "pick-ret2")
    validate_success(
        api.ship(order["id"], {"quantity": 250, "carrier": "GROUND",
                               "sla_hours": 48}, FULFILLMENT),
        expected_status=201,
    )

    returned = validate_success(
        api.return_order(order["id"], {"return_quantity": 10}, FULFILLMENT),
        expected_status=200,
    )

    assert returned["status"] == "RETURNED"
    assert returned["returned_qty"] == 10
    # requested 1250, less 10 units at 900 cents, floored at zero.
    assert returned["realized_wholesale_cents"] == max(
        0, returned["requested_wholesale_cents"] - 10 * 900,
    )


def test_retiring_from_parallel_hold_destroys_and_fails_the_layers(api):
    """PRD §3.7: "Retirement from `PARALLEL_HOLD` is the lightest branch and does
    not touch the design at all: the run moves to `RETIRED_DESTROYED` with
    `retired_at` stamped and `hold_allocation_cents` released, and every print
    layer is moved to `PRINT_FAILED` with `committed_qty` forced to 0, which then
    scales that run's open fulfillment orders down and marks any order whose
    recomputed wholesale total falls below zero as `DISTRESSED`."

    Design: Difficulty/transitive_cascade/design_rejection_three_hop_cascade
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-22", quantity=20)
    pick_order(api, order, setup["run"]["id"], 20, "pick-ph")
    retired = validate_success(
        api.retire_production_order(
            setup["run"]["id"],
            {"retire_reason": "LOSING_OUTCOME", "destroy_mode": "DESTROY"},
            PLANNER,
        ),
        expected_status=200,
    )
    assert retired["status"] == "RETIRED_DESTROYED"
    assert retired["retired_at"] is not None
    assert retired["hold_allocation_cents"] == 0

    layer = validate_success(
        api.get_print_layer(setup["base_layer_id"], PLANNER), expected_status=200,
    )
    assert layer["layer_state"] == "PRINT_FAILED"
    assert layer["committed_qty"] == 0


def test_retiring_a_committed_run_donates_when_the_mode_is_donate(api):
    """PRD §3.7: "From `COMMITTED` or `PRINTING` with `destroy_mode` `DONATE` the
    run moves to `RETIRED_DONATED`"
    PRD §3.7: "On the donation branch, every fulfillment order of the run has its
    `donated_qty` set to its full `quantity`, its `destroyed_qty` set to 0, its
    `requested_wholesale_cents` rewritten on the donate weighting with no penalty,
    and its `realized_wholesale_cents` set to 0."

    Design: Difficulty/compensating_invariant/unlacing_on_site_removes_second_party_liability
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    order = create_order(api, setup["run"], channel="VENUE_RETAIL",
                         destination_code="ATL_VENUE", quantity=100)

    retired = validate_success(
        api.retire_production_order(
            setup["run"]["id"],
            {"retire_reason": "LOSING_OUTCOME", "destroy_mode": "DONATE"},
            PLANNER,
        ),
        expected_status=200,
    )
    assert retired["status"] == "RETIRED_DONATED"

    read = get_order(api, order["id"])
    assert read["donated_qty"] == 100
    assert read["destroyed_qty"] == 0
    assert read["requested_wholesale_cents"] == 0
    assert read["realized_wholesale_cents"] == 0


def test_no_mutation_leaves_a_retired_run(api):
    """PRD §2.6: "`RETIRED_DESTROYED` and `RETIRED_DONATED` on a `ProductionOrder`
    ... No operation in this API leaves a resource in one of those states."

    Design: Corner/state_machines/fulfillment_delivered_is_terminal
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    retired = validate_success(
        api.retire_production_order(
            setup["run"]["id"],
            {"retire_reason": "LOSING_OUTCOME", "destroy_mode": "DESTROY"},
            PLANNER,
        ),
        expected_status=200,
    )

    resp = api.retire_production_order(
        setup["run"]["id"],
        {"retire_reason": "DEMAND_COLLAPSE", "destroy_mode": "DONATE"},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_run(api, setup["run"]["id"])["status"] == retired["status"]


@pytest.mark.parametrize("reason", ["OUTCOME_COMMITTED", "LOSING_OUTCOME",
                                    "ASSORTMENT_CHANGED", "DEMAND_COLLAPSE"])
def test_every_declared_retire_reason_is_accepted(api, reason):
    """PRD §3.7: "it is taken against a `retire_reason` — one of
    `OUTCOME_COMMITTED`, `LOSING_OUTCOME`, `ASSORTMENT_CHANGED` or
    `DEMAND_COLLAPSE` — with an optional `destroy_mode`."

    Design: Difficulty/compensating_invariant/unlacing_on_site_removes_second_party_liability
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)

    retired = validate_success(
        api.retire_production_order(
            setup["run"]["id"],
            {"retire_reason": reason, "destroy_mode": "DESTROY"},
            PLANNER,
        ),
        expected_status=200,
    )
    assert retired["retire_reason"] == reason
    assert retired["status"] == "RETIRED_DESTROYED"