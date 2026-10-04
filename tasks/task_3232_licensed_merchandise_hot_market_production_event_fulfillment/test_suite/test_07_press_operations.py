"""Press operations: printing units, recording lost units and the reopen rail."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    CLOCK_PAST_WINDOW,
    PRINTER,
    author_layers,
    committed_run,
    get_run,
    print_failure,
    print_layer,
    printed_run,
    set_clock,
)


def test_a_print_moves_the_run_into_printing_and_records_the_units(api):
    """PRD §3.4: "A successful print adds the supplied `printed_qty` to the
    layer's running `printed_qty`, recomputes the layer's `committed_qty` as its
    `printed_qty` less its `failed_qty`, advances the layer to `PRINTED` and
    refreshes `design_version_checked` with the `Design`'s `version` observed at
    that moment."
    PRD §3.4: "the run moves from `COMMITTED` to `PRINTING`"

    Design: Difficulty/transitive_cascade/print_failure_two_hop_rescale
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)
    layer = validate_success(
        api.print_layer(setup["base_layer_id"], {"printed_qty": 20}, PRINTER),
        expected_status=200,
    )

    assert layer["printed_qty"] == 20
    assert layer["failed_qty"] == 0
    assert layer["committed_qty"] == 20
    assert layer["layer_state"] == "PRINTED"
    assert layer["design_version_checked"] is not None

    run = get_run(api, setup["run"]["id"])
    assert run["status"] == "PRINTING"
    assert run["base_units_printed"] == 20


def test_a_further_print_accumulates_on_a_printed_layer(api):
    """PRD §3.4: "a further print on a layer already in `PRINTED` keeps it in
    `PRINTED` and simply increases `printed_qty` and `committed_qty` again while
    refreshing `design_version_checked` afresh, so a layer carries the sum of all
    its successful attempts."

    Design: Difficulty/non_linear_state_machine/production_order_printing_revert_reopen_window
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    print_layer(api, setup["base_layer_id"], 20)

    layer = validate_success(
        api.print_layer(setup["base_layer_id"], {"printed_qty": 15}, PRINTER),
        expected_status=200,
    )
    assert layer["printed_qty"] == 35
    assert layer["committed_qty"] == 35
    assert layer["layer_state"] == "PRINTED"

    run = get_run(api, setup["run"]["id"])
    assert run["base_units_printed"] == 35


def test_a_print_beyond_the_authorised_quantity_is_refused(api):
    """PRD §3.4: "a print that would carry `printed_qty` above the layer's
    `quantity` is rejected with `ERR_PRINT_QUANTITY_EXCEEDED` (HTTP 422)."

    Design: Corner/state_machines/print_layer_pennant_blocked_when_flag_false
    """
    set_clock(api)
    setup = committed_run(api, base_qty=20)

    resp = api.print_layer(setup["base_layer_id"], {"printed_qty": 21}, PRINTER)
    validate_error(resp, ApiErrorId.ERR_PRINT_QUANTITY_EXCEEDED,
                   expected_status=422)


def test_a_failure_that_zeroes_the_reducer_reopens_the_run(api):
    """PRD §3.4: "When a recorded failure drives the print reducer's result — the
    layer's `printed_qty` less its `failed_qty` — to exactly zero, meaning the
    layer's `failed_qty` has caught up with or passed its `printed_qty`, the run
    reopens: its `status` returns to `COMMITTED` and `committed_at` is
    re-stamped, which restarts the event window from the new stamp."
    PRD §3.4: "it recomputes the run's open fulfillment orders against the reduced
    printable pool — any order whose recomputed `requested_wholesale_cents` drops
    below zero is set to `DISTRESSED`."

    Design: Difficulty/non_linear_state_machine/production_order_printing_revert_reopen_window
    """
    set_clock(api)
    setup = printed_run(api, printed_qty=20, base_qty=20)
    run_before = get_run(api, setup["run"]["id"])
    assert run_before["status"] == "PRINTING"
    committed_at_before = run_before["committed_at"]

    set_clock(api, "2026-09-01T01:00:00Z")
    layer = print_failure(api, setup["base_layer_id"], 40)

    assert layer["failed_qty"] == 40
    assert layer["printed_qty"] == 20
    assert layer["committed_qty"] == 0
    assert layer["layer_state"] == "PRINT_FAILED"

    run = get_run(api, setup["run"]["id"])
    assert run["status"] == "COMMITTED"
    assert run["base_units_printed"] == 0
    assert run["committed_at"] > committed_at_before
    assert run["write_down_inventory_cents"] == 0


def test_printing_after_the_event_window_closes_is_refused(api):
    """PRD §3.4: "If the parent run is in `PRINTING`, the clock must read at or
    before the run's `committed_at` plus 48 hours; a print arriving after that
    instant is rejected with `ERR_EVENT_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/reopen_window_boundary_at_committed_plus_48h
    """
    set_clock(api)
    setup = printed_run(api, printed_qty=20, base_qty=20)

    set_clock(api, CLOCK_PAST_WINDOW)
    resp = api.print_failure(
        setup["base_layer_id"], {"failed_qty": 20}, PRINTER,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_CLOSED, expected_status=409)


def test_print_failure_after_the_window_closes_leaves_the_layer_untouched(api):
    """PRD §3.6: "The window that governs hot-market production is the run's event
    window: it opens at `ProductionOrder.committed_at` and closes 48 hours later.
    Printing into the window, and reopening a committed run back from `PRINTING`
    to `COMMITTED`, are both permitted only while the logical clock reads at or
    before that instant; a request that arrives after it is rejected with
    `ERR_EVENT_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/print_failure_blocked_by_closed_event_window
    """
    set_clock(api)
    setup = printed_run(api, printed_qty=20, base_qty=20)

    set_clock(api, CLOCK_PAST_WINDOW)
    resp = api.print_failure(setup["base_layer_id"], {"failed_qty": 5}, PRINTER)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_CLOSED, expected_status=409)

    layer = validate_success(
        api.get_print_layer(setup["base_layer_id"], PRINTER), expected_status=200,
    )
    assert layer["failed_qty"] == 0
    assert layer["committed_qty"] == 20


def test_the_reopen_window_is_inclusive_at_exactly_48_hours(api):
    """PRD §3.6: "Printing into the window, and reopening a committed run back
    from `PRINTING` to `COMMITTED`, are both permitted only while the logical
    clock reads at or before that instant"
    PRD §3.6: "This is permitted only while the clock still reads at or before the
    pre-existing `committed_at` plus 48 hours"

    Design: Difficulty/boundary_precision_check/reopen_window_boundary_at_committed_plus_48h
    """
    set_clock(api)
    setup = printed_run(api, printed_qty=20, base_qty=20)

    set_clock(api, "2026-09-03T00:00:00Z")
    resp = api.print_failure(setup["base_layer_id"], {"failed_qty": 40}, PRINTER)
    layer = validate_success(resp, expected_status=200)

    assert layer["committed_qty"] == 0
    run = get_run(api, setup["run"]["id"])
    assert run["status"] == "COMMITTED"
    assert run["base_units_printed"] == 0


def test_a_reopened_run_may_be_layered_and_printed_again(api):
    """PRD §3.4: "Because the reopen re-stamps `committed_at` and returns the run
    to a committable state, it is genuinely cyclic: the reopened run may be
    layered again, and a second failed print reverts it a second time within the
    freshly opened window."

    Design: Difficulty/non_linear_state_machine/production_order_printing_revert_reopen_window
    """
    set_clock(api)
    setup = printed_run(api, printed_qty=20, base_qty=20)
    print_failure(api, setup["base_layer_id"], 40)

    reopened = get_run(api, setup["run"]["id"])
    assert reopened["status"] == "COMMITTED"

    relayered = author_layers(
        api, reopened, [{"print_type": "BASE", "quantity": 30}],
    )
    assert relayered["status"] == "COMMITTED"
    new_layer_id = relayered["layer_ids"][-1]

    print_layer(api, new_layer_id, 30)
    assert get_run(api, setup["run"]["id"])["status"] == "PRINTING"

    print_failure(api, new_layer_id, 30)
    assert get_run(api, setup["run"]["id"])["status"] == "COMMITTED"


def test_a_stale_clock_blocks_even_a_reopening_print_failure(api):
    """PRD §3.6: "the run's event window: it opens at `ProductionOrder.committed_at`
    and closes 48 hours later."
    PRD §2.6: "All deadlines, reopen windows, window classifications and rush
    service levels in this API are evaluated against a logical clock, never
    against wall-clock time."

    Design: Difficulty/cross_entity_state_dependency/print_failure_blocked_by_closed_event_window
    """
    set_clock(api)
    setup = printed_run(api, printed_qty=20, base_qty=20)
    run_before = get_run(api, setup["run"]["id"])
    assert run_before["status"] == "PRINTING"

    set_clock(api, CLOCK_PAST_WINDOW)
    resp = api.print_failure(setup["base_layer_id"], {"failed_qty": 40}, PRINTER)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_CLOSED, expected_status=409)

    # The failure that would have reopened the run never landed.
    run_after = get_run(api, setup["run"]["id"])
    assert run_after["status"] == "PRINTING"
    assert run_after["committed_at"] == run_before["committed_at"]
    assert run_after["base_units_printed"] == 20
    layer = validate_success(
        api.get_print_layer(setup["base_layer_id"], PRINTER), expected_status=200,
    )
    assert layer["failed_qty"] == 0
    assert layer["committed_qty"] == 20