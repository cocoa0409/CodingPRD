"""The allocation selector: nested capacity arithmetic, the deferred BLOCKED
outcome, tie-breaking, quarantine exclusion, the expired-commitment gate, and
the allocate/cancel compensation pair.
"""

from test_helpers import (
    PLANNER,
    api_client,
    allocate_order,
    book_order,
    confirm_disease_event,
    create_active_commitment,
    create_and_place_flock,
    create_complex,
    create_customer,
    create_disease_event,
    create_house,
    make_customer_headers,
    read_commitment,
    read_complex,
    read_flock,
    read_order,
    run_ops,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def _setup_prairie_gold(api):
    """MIDWEST complex with a 50000-hen LAYING flock at age 18: the week-0
    projection is 24791 dozen."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Prairie Gold")
    house = create_house(complex_["id"], capacity_hens=100_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=50_000,
    )
    return complex_, house, flock


def _setup_commitment_with_two_orders(api):
    """Prairie Gold + ACTIVE commitment (100000/week, adjustment 0) with a
    10000-dozen order already ALLOCATED and a 15000-dozen order BOOKED for
    the same week."""
    complex_, _, _ = _setup_prairie_gold(api)
    customer = create_customer()
    commitment = create_active_commitment(
        customer["id"], price_adjustment_cents_per_dozen=0,
    )
    order_a = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=10_000,
    )
    order_a = allocate_order(order_a["id"])
    order_b = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=15_000,
    )
    return complex_, customer, commitment, order_a, order_b


def test_allocation_blocks_when_nested_capacity_falls_short(api):
    """available = max(0, projection - already-allocated): 24791 - 10000 =
    14791 < 15000, so the second order blocks.

    PRD §3.6: "Any other complex's availability for the week is its projected
    total dozen at that offset (§3.6's projection below) minus the dozens
    already committed to it for the same `ship_week_start` by orders in
    `ALLOCATED` or `SHIPPED`, floored at zero. Candidates are the complexes
    in the commitment's region whose availability covers `dozen_ordered` —
    allocation is all-or-nothing".

    Design: Difficulty/combinatorial_formula/allocation_capacity_nested_min_max_quarantine_branch
    """
    complex_, _, _, order_a, order_b = _setup_commitment_with_two_orders(api)
    assert order_a["status"] == "ALLOCATED"
    assert order_a["allocated_dozen"] == 10_000
    assert order_a["allocated_complex_id"] == complex_["id"]

    allocate_order(order_b["id"])
    blocked = read_order(order_b["id"])
    assert blocked["status"] == "BLOCKED"
    assert blocked["allocated_complex_id"] is None
    assert blocked["allocated_dozen"] is None


def test_allocation_empty_pool_is_a_200_deferred_outcome(api):
    """An empty candidate pool is not an error: the response is 200, the
    order becomes BLOCKED, and the commitment's counter rises.

    PRD §3.6: "An empty candidate pool is **not** an error: the request still
    returns 200, the order becomes `BLOCKED` with both allocated fields null,
    and the commitment's `blocked_order_count` rises by one — a
    deferred-queue outcome the planner retries later."

    Design: Difficulty/combinatorial_formula/allocation_capacity_nested_min_max_quarantine_branch
    """
    _, _, commitment, _, order_b = _setup_commitment_with_two_orders(api)
    assert read_commitment(commitment["id"])["blocked_order_count"] == 0

    result = validate_success(api.allocate_order(order_b["id"],
                                                 PLANNER))
    assert result["status"] == "BLOCKED"
    assert read_commitment(commitment["id"])["blocked_order_count"] == 1


def test_allocate_then_cancel_restores_week_capacity(api):
    """Cancelling the allocated order releases its week capacity: the
    15000-dozen order that blocked at 14791 allocates cleanly afterwards.

    PRD §3.6: "Cancelling releases the order's claim on the commitment's
    weekly volume; cancelling an `ALLOCATED` order additionally releases its
    allocated capacity, so the complex's week-allocated total no longer
    counts it."
    PRD §3.6: "Allocation is the planner's deferred matching step, legal
    while the order is `BOOKED` or `BLOCKED` and the commitment is `ACTIVE`".

    Design: Difficulty/compensating_invariant/allocate_then_cancel_restores_week_capacity
    """
    complex_, customer, _, order_a, order_b = (
        _setup_commitment_with_two_orders(api)
    )
    mid = allocate_order(order_b["id"])
    assert mid["status"] == "BLOCKED"  # pool drained to 14791 < 15000

    cancelled = validate_success(
        api.cancel_order(order_a["id"], make_customer_headers(customer["id"]))
    )
    assert cancelled["status"] == "CANCELLED"

    retried = allocate_order(order_b["id"])
    assert retried["status"] == "ALLOCATED"
    assert retried["allocated_dozen"] == 15_000
    assert retried["allocated_complex_id"] == complex_["id"]


def test_blocked_counter_returns_to_zero_after_retry(api):
    """The counter is symmetric: it falls back to 0 when the BLOCKED order
    leaves BLOCKED via the successful retry.

    PRD §3.6: "The counter is maintained symmetrically: it increments when an
    order enters `BLOCKED` and decrements when a `BLOCKED` order leaves it
    for `ALLOCATED` or `CANCELLED`."

    Design: Difficulty/compensating_invariant/allocate_then_cancel_restores_week_capacity
    """
    _, customer, commitment, order_a, order_b = (
        _setup_commitment_with_two_orders(api)
    )
    allocate_order(order_b["id"])
    assert read_commitment(commitment["id"])["blocked_order_count"] == 1

    validate_success(
        api.cancel_order(order_a["id"], make_customer_headers(customer["id"]))
    )
    allocate_order(order_b["id"])

    assert read_commitment(commitment["id"])["blocked_order_count"] == 0
    assert read_order(order_b["id"])["status"] == "ALLOCATED"


def test_selector_tie_break_prefers_earlier_created_complex(api):
    """Identical availability ties break by earliest complex created_at.

    PRD §3.6: "Candidates are the complexes in the commitment's region whose
    availability covers `dozen_ordered` — allocation is all-or-nothing —
    ranked by highest availability with ties broken by earliest complex
    `created_at`."

    Design: Corner/endpoints/selector_tie_break_prefers_earlier_created_complex
    """
    set_clock("2026-09-01T00:00:00Z")
    alpha = create_complex(name="Alpha")
    set_clock("2026-09-01T01:00:00Z")
    beta = create_complex(name="Beta")
    for complex_ in (alpha, beta):
        house = create_house(complex_["id"], capacity_hens=100_000)
        create_and_place_flock(
            house["id"], placement_date="2026-04-28T00:00:00Z",
            placed_hen_count=50_000,
        )
    customer = create_customer()
    commitment = create_active_commitment(
        customer["id"], price_adjustment_cents_per_dozen=0,
    )
    order = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=5_000,
    )

    allocated = allocate_order(order["id"])
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_dozen"] == 5_000
    # Alpha (created 2026-09-01T00:00:00Z) beats Beta (01:00:00Z) on the tie.
    assert allocated["allocated_complex_id"] == alpha["id"]
    assert allocated["allocated_complex_id"] != beta["id"]


def test_selector_skips_quarantined_complex(api):
    """A QUARANTINE complex contributes zero availability and is excluded
    from the candidate set; the order lands on the remaining complex.

    PRD §3.6: "A complex in `QUARANTINE` contributes zero availability."
    PRD §2.7: "order allocation treats a quarantined complex more gently: the
    complex simply has zero availability in the selector and is never an
    error."

    Design: Corner/endpoints/selector_skips_quarantined_complex
    """
    set_clock("2026-09-01T00:00:00Z")
    alpha = create_complex(name="Alpha")
    beta = create_complex(name="Beta")
    houses = {}
    flocks = {}
    for tag, complex_ in (("a", alpha), ("b", beta)):
        house = create_house(complex_["id"], capacity_hens=100_000)
        houses[tag] = house
        flocks[tag] = create_and_place_flock(
            house["id"], placement_date="2026-04-28T00:00:00Z",
            placed_hen_count=50_000,
        )
    event = create_disease_event(alpha["id"], [houses["a"]["id"]])
    confirm_disease_event(event["id"])
    assert read_complex(alpha["id"])["biosecurity_posture"] == "QUARANTINE"
    # Confirmation alone does not depopulate: Alpha's flock is intact.
    assert read_flock(flocks["a"]["id"])["status"] == "LAYING"

    customer = create_customer()
    commitment = create_active_commitment(
        customer["id"], price_adjustment_cents_per_dozen=0,
    )
    order = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=10_000,
    )

    allocated = allocate_order(order["id"])
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_complex_id"] == beta["id"]


def _setup_expired_commitment_order(api):
    """A BOOKED order whose commitment expired while the ship window is
    still open."""
    complex_, _, _ = _setup_prairie_gold(api)
    customer = create_customer()
    commitment = create_active_commitment(
        customer["id"], price_adjustment_cents_per_dozen=0,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-20T00:00:00Z",
    )
    order = book_order(
        commitment["id"], customer["id"],
        ship_week_start="2026-09-07T00:00:00Z", dozen_ordered=10_000,
    )
    set_clock("2026-09-20T12:00:00Z")
    run_ops(complex_["id"])
    return complex_, customer, commitment, order


def test_allocate_rejected_after_commitment_expires(api):
    """The commitment moved ACTIVE -> EXPIRED under the order, so the
    allocate cross-entity state gate rejects with ERR_INVALID_STATE.

    PRD §3.5: "Any complex's operations checkpoint expires an `ACTIVE`
    commitment into `EXPIRED` once the clock passes `effective_to`."
    PRD §3.6: "Allocation is the planner's deferred matching step, legal
    while the order is `BOOKED` or `BLOCKED` and the commitment is `ACTIVE`
    (else `ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/allocate_blocked_after_commitment_expires
    """
    _, _, commitment, order = _setup_expired_commitment_order(api)
    expired = read_commitment(commitment["id"])
    assert expired["status"] == "EXPIRED"

    validate_error(api.allocate_order(order["id"], PLANNER),
                   ERR.ERR_INVALID_STATE)


def test_allocate_rejection_leaves_order_booked_inside_ship_window(api):
    """The order's own ship window still passes at the attempt clock —
    isolating the cross-entity state gate as the sole failure — and the
    order stays BOOKED.

    PRD §3.6: "Allocation is the planner's deferred matching step, legal
    while the order is `BOOKED` or `BLOCKED` and the commitment is `ACTIVE`
    (else `ERR_INVALID_STATE`), and only while the clock is earlier than
    fourteen days after `ship_week_start` (else
    `ERR_ORDER_OUTSIDE_SHIP_WINDOW`)."

    Design: Difficulty/cross_entity_state_dependency/allocate_blocked_after_commitment_expires
    """
    _, _, commitment, order = _setup_expired_commitment_order(api)
    # Clock 2026-09-20T12:00 is earlier than ship_week_start + 14 days
    # (2026-09-21T00:00Z): the temporal gate alone would pass.
    validate_error(api.allocate_order(order["id"], PLANNER),
                   ERR.ERR_INVALID_STATE)
    assert read_order(order["id"])["status"] == "BOOKED"
    assert read_commitment(commitment["id"])["status"] == "EXPIRED"

