"""Depth: the allocation shortfall cascade that unwinds a quote and its siblings."""
from test_helpers import validate_success
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_pool_conserved
from test_helpers.fixtures import (
    SALES_OPS,
    create_backorder,
    finalize_allocation,
    get_backorder,
    setup_book_world,
    setup_reserved_quote,
    start_sweep,
)


def _reserved_quote_with_two_sibling_backorders(clock="2026-09-16T00:00:00.000Z"):
    """RESERVED SYSTEM_PACKAGE quote (anchor guitar line + dependent amp line),
    each holding one PREORDER_PENDING backorder; shared pool holds 1 unit."""
    world = setup_book_world(clock=clock)
    setup_reserved_quote(world)
    first = create_backorder(world["guitar_line"], world["engineer"],
                             units_requested=3,
                             preorder_open_at="2026-09-16T00:00:00.000Z")
    second = create_backorder(world["amp_line"], world["engineer"],
                              units_requested=1,
                              preorder_open_at="2026-09-16T00:00:00.000Z")
    world.update({"backorder_first": first, "backorder_second": second,
                  "backorder_first_id": first["id"], "backorder_second_id": second["id"]})
    return world


def test_preliminary_sweep_estimate_measures_each_claim_against_the_whole_pool():
    """PRD 3.5: "The provisional variant, stored in `overcommit_estimate_units`
    when the sweep starts, measures each claim against the full pool
    independently, giving each claim the smaller of its own requested units and
    the whole pool." PRD 3.5: "Over-commitment of the provisional estimate is
    explicitly permitted".

    Design: Difficulty/transitive_cascade/allocation_shortfall_unwinds_quote_and_sibling_backorders
    """
    world = _reserved_quote_with_two_sibling_backorders()
    swept = start_sweep(world["backorder_first"], pool_units=1)
    assert swept["status"] == "ALLOCATION_SWEEP"
    assert swept["overcommit_estimate_units"] == 1, (
        "min(units_requested 3, pool 1) == 1 for this claim's own view of the pool"
    )


def test_shortfall_finalizes_the_claim_as_partially_filled():
    """PRD 3.5: "The final variant, stored in `units_filled` when the allocation
    is finalized, is a single pass that depletes the pool: it starts with the
    full pool as remaining capacity, grants each claim in walk order the smaller
    of its requested units and what remains, and subtracts the grant before
    moving on, so the pool is conserved exactly".

    Design: Difficulty/transitive_cascade/allocation_shortfall_unwinds_quote_and_sibling_backorders
    """
    world = _reserved_quote_with_two_sibling_backorders()
    start_sweep(world["backorder_first"], pool_units=1)
    finalized = finalize_allocation(world["backorder_first"], pool_units=1)
    assert finalized["units_filled"] == 1
    assert finalized["status"] == "PARTIALLY_FILLED"


def test_shortfall_unwinds_the_parent_quote_to_submitted():
    """PRD 3.5: "When the final allocation grants more than zero but fewer than
    `units_requested`, the claim moves to `PARTIALLY_FILLED`, and this is the
    branch with consequences beyond the claim itself: the containing quote loses
    its full reservation, returning to `SUBMITTED` with `reserved_at` cleared".

    Design: Difficulty/transitive_cascade/allocation_shortfall_unwinds_quote_and_sibling_backorders
    """
    world = _reserved_quote_with_two_sibling_backorders()
    start_sweep(world["backorder_first"], pool_units=1)
    finalize_allocation(world["backorder_first"], pool_units=1)

    quote = validate_success(api_client.get_quote(world["quote_id"], SALES_OPS))
    assert quote["status"] == "SUBMITTED"
    assert quote["reserved_at"] is None


def test_shortfall_cancels_the_quote_sibling_backorder():
    """PRD 3.5: "every other backorder on the same quote that is still in
    `PREORDER_PENDING` or `ALLOCATION_SWEEP` is cancelled."

    Design: Difficulty/transitive_cascade/allocation_shortfall_unwinds_quote_and_sibling_backorders
    """
    world = _reserved_quote_with_two_sibling_backorders()
    assert get_backorder(world["backorder_second_id"])["status"] == "PREORDER_PENDING"

    start_sweep(world["backorder_first"], pool_units=1)
    finalize_allocation(world["backorder_first"], pool_units=1)

    sibling = get_backorder(world["backorder_second_id"])
    assert sibling["status"] == "CANCELLED"


def test_final_allocation_conserves_the_pool_the_preliminary_estimates_over_committed():
    """PRD 3.5: "the pool is conserved exactly and no fraction of a unit is ever
    allocated. A consequence worth stating plainly: because the final walk stops
    once the pool is exhausted, later claims in `alloc_sequence` order receive
    strictly less than their own preliminary estimate whenever the pool cannot
    cover everyone."

    Design: Difficulty/transitive_cascade/allocation_shortfall_unwinds_quote_and_sibling_backorders
    """
    world = _reserved_quote_with_two_sibling_backorders()
    preliminary = start_sweep(world["backorder_first"], pool_units=1)
    assert preliminary["overcommit_estimate_units"] == 1

    finalize_allocation(world["backorder_first"], pool_units=1)
    non_cancelled = [row for row in
                     [get_backorder(world["backorder_first_id"]),
                      get_backorder(world["backorder_second_id"])]
                     if row["status"] != "CANCELLED"]
    assert_pool_conserved(
        sum(row["units_filled"] for row in non_cancelled), 1)
    assert sum(row["units_filled"] for row in non_cancelled) == 1


def test_final_allocation_grants_the_full_request_and_fills_the_board():
    """PRD 3.5: "When the final allocation grants at least `units_requested` and
    at least one unit was requested, the claim moves to `BOARD_FILLED` and the
    quote is left alone."

    Design: Difficulty/transitive_cascade/allocation_shortfall_unwinds_quote_and_sibling_backorders
    """
    world = _reserved_quote_with_two_sibling_backorders()
    single = create_backorder(world["guitar_line"], world["engineer"],
                              units_requested=2,
                              preorder_open_at="2026-09-16T00:00:00.000Z")
    start_sweep(single, pool_units=2)
    finalized = finalize_allocation(single, pool_units=2)

    assert finalized["units_filled"] == 2
    assert finalized["status"] == "BOARD_FILLED"
    quote = validate_success(api_client.get_quote(world["quote_id"], SALES_OPS))
    assert quote["status"] == "RESERVED"


def test_claim_requesting_zero_units_is_refused_before_any_sweep():
    """PRD 3.5: "A claim asking for zero units is refused rather than being
    quietly satisfied with nothing: `units_requested` of exactly 0 defines an
    empty candidate set and raises `ERR_ZERO_ALLOCATION_REQUEST` at HTTP 422."

    Design: Difficulty/transitive_cascade/allocation_shortfall_unwinds_quote_and_sibling_backorders
    """
    from test_helpers import ApiErrorId, validate_error

    world = setup_book_world(clock="2026-09-16T00:00:00.000Z")
    setup_reserved_quote(world)

    resp = api_client.create_backorder(
        {"quote_line_id": world["guitar_line"]["id"], "engineer_id": world["engineer_id"],
         "units_requested": 0, "preorder_open_at": "2026-09-16T00:00:00.000Z"},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_ZERO_ALLOCATION_REQUEST)