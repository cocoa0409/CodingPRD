"""The allocation run: policy ranking, paralleled sets, shortage, release."""


from test_helpers import (
    ApiErrorId,
    PRODUCT_P1,
    allocate_payload,
    allocations_of_line,
    allocations_of_order,
    build_quote,
    convert_quote,
    create_branch,
    create_customer,
    create_product,
    issue_quote,
    list_order_lines,
    list_reels,
    make_branch_ops_headers,
    post_credit_adjustment,
    publish_index,
    read_allocation,
    read_branch,
    read_customer,
    read_order,
    read_order_line,
    read_reel,
    receive_reel,
    release_allocations,
    run_allocator,
    setup_converted_order,
    setup_allocated_order,
    validate_error,
    validate_success,
)


def _branch_pool_with_a_three_hundred_foot_demand(customer, product, branch_name):
    """One branch stocked with 400 ft, 1000 ft and 250 ft reels of the same
    part, and a converted order carrying a single 300 ft CUT line."""
    branch = create_branch(name=branch_name)
    reels = [
        receive_reel(product["id"], branch["id"], nominal_length_ft=length,
                     lot_code="LA")
        for length in (400, 1000, 250)
    ]
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 300}],
    )
    issue_quote(quote["id"], issuer="rep-2")
    order = convert_quote(quote["id"], issuer="rep-2")
    return {"branch": branch, "reels": reels, "order": order}


def _two_pools_allocated_under_each_policy():
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    pool_a = _branch_pool_with_a_three_hundred_foot_demand(
        customer, product, "Houston DC"
    )
    pool_b = _branch_pool_with_a_three_hundred_foot_demand(
        customer, product, "Dallas DC"
    )
    run_allocator(
        pool_a["order"]["id"], pool_a["branch"]["id"], policy="MINIMIZE_REMNANT"
    )
    run_allocator(
        pool_b["order"]["id"], pool_b["branch"]["id"], policy="FEWEST_REELS"
    )
    return pool_a, pool_b


def test_minimize_remnant_broaches_the_smallest_sufficient_reel(api):
    """PRD §3.6: "Under `MINIMIZE_REMNANT` — the policy used when
    `allocation_policy` is omitted — the allocator best-fits: among candidates
    whose available footage is at least the footage still needed for this
    pick, it chooses the one with the smallest available footage, so that the
    least usable cable is left behind."
    PRD §3.6: "The two policies genuinely diverge: for a 300-foot need against
    reels of 400, 1000 and 250 feet, `MINIMIZE_REMNANT` broaches the 400-foot
    reel and `FEWEST_REELS` broaches the 1000-foot reel — the same demand, a
    different reel, and a different remnant."
    PRD §3.6: "For each allocation created, the holding reel's
    `allocated_length_ft` rises by that allocation's `length_ft`; a reel whose
    `allocated_length_ft` becomes greater than 0 moves `IN_STOCK →
    ALLOCATED_PARTIAL`, and its `available_length_ft` is recomputed."

    Design: Difficulty/dual_variant_calc/allocation_policy_minimize_remnant_vs_fewest_reels_on_reel_pool
    """
    pool_a, _ = _two_pools_allocated_under_each_policy()
    reel_400, reel_1000, reel_250 = pool_a["reels"]

    broached = read_reel(reel_400["id"])
    assert broached["allocated_length_ft"] == 300
    assert broached["status"] == "ALLOCATED_PARTIAL"
    untouched = read_reel(reel_1000["id"])
    assert untouched["allocated_length_ft"] == 0
    assert untouched["status"] == "IN_STOCK"
    assert read_reel(reel_250["id"])["allocated_length_ft"] == 0

    order = read_order(pool_a["order"]["id"])
    assert order["fulfillment_status"] == "ALLOCATED"
    assert order["allocation_policy"] == "MINIMIZE_REMNANT"


def test_fewest_reels_broaches_the_largest_reel(api):
    """PRD §3.6: "Under `FEWEST_REELS`, the allocator ranks by available
    footage descending unconditionally, so the largest reel is always broached
    first."
    PRD §3.6: "The two policies genuinely diverge: for a 300-foot need against
    reels of 400, 1000 and 250 feet, `MINIMIZE_REMNANT` broaches the 400-foot
    reel and `FEWEST_REELS` broaches the 1000-foot reel — the same demand, a
    different reel, and a different remnant."
    PRD §3.6: "The order's `allocation_policy` is set to whatever policy this
    run used."

    Design: Difficulty/dual_variant_calc/allocation_policy_minimize_remnant_vs_fewest_reels_on_reel_pool
    """
    _, pool_b = _two_pools_allocated_under_each_policy()
    reel_400, reel_1000, reel_250 = pool_b["reels"]

    broached = read_reel(reel_1000["id"])
    assert broached["allocated_length_ft"] == 300
    assert broached["status"] == "ALLOCATED_PARTIAL"
    untouched = read_reel(reel_400["id"])
    assert untouched["allocated_length_ft"] == 0
    assert untouched["status"] == "IN_STOCK"
    assert read_reel(reel_250["id"])["allocated_length_ft"] == 0

    order = read_order(pool_b["order"]["id"])
    assert order["fulfillment_status"] == "ALLOCATED"
    assert order["allocation_policy"] == "FEWEST_REELS"


# ══════════════════════════════════════════════════════════════════════════
# The reserve / release / reserve cycle
# ══════════════════════════════════════════════════════════════════════════

def _three_reel_pool_allocated_once():
    return setup_allocated_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[
            {"nominal_length_ft": 400},
            {"nominal_length_ft": 1000},
            {"nominal_length_ft": 250},
        ],
        policy="MINIMIZE_REMNANT",
    )


def test_release_returns_the_broached_reel_to_in_stock(api):
    """PRD §3.6: "Every `RESERVED` allocation moves `RESERVED → RELEASED`;
    each release decrements its reel's `allocated_length_ft` by the
    allocation's `length_ft`, and a reel whose `allocated_length_ft` returns
    to 0 moves `ALLOCATED_PARTIAL → IN_STOCK` provided it still carries
    physical footage."
    PRD §3.6: "Every line is reset to `allocated_length_ft` 0 and
    `allocation_status` `UNALLOCATED`, and the order returns to
    `PENDING_ALLOCATION` from either starting state."

    Design: Difficulty/non_linear_state_machine/reel_reserve_release_reserve_cycle_returns_to_allocated_partial
    """
    scn = _three_reel_pool_allocated_once()
    reel_400 = scn["reels"][0]
    assert read_reel(reel_400["id"])["status"] == "ALLOCATED_PARTIAL"

    release_allocations(scn["order"]["id"], scn["branch"]["id"])

    released = read_reel(reel_400["id"])
    assert released["status"] == "IN_STOCK"
    assert released["allocated_length_ft"] == 0
    assert released["current_length_ft"] == 400, (
        "reservations move numbers, not cable"
    )
    line = read_order_line(scn["order_lines"][0]["id"])
    assert line["allocated_length_ft"] == 0
    assert line["allocation_status"] == "UNALLOCATED"
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "PENDING_ALLOCATION"


def test_reallocating_after_a_release_reserves_the_same_reel_again(api):
    """PRD §3.6: "Under `MINIMIZE_REMNANT` — the policy used when
    `allocation_policy` is omitted — the allocator best-fits: among candidates
    whose available footage is at least the footage still needed for this
    pick, it chooses the one with the smallest available footage, so that the
    least usable cable is left behind."
    PRD §3.6: "`available_length_ft` is always `current_length_ft` less
    `allocated_length_ft`, and `reel_type` is either `MASTER` or `REMNANT`,
    the latter reserved for reels spawned by a cut."
    PRD §3.6: "The order then follows: if every line is `FULLY_ALLOCATED` the
    order moves to `ALLOCATED`; if at least one allocation was created but at
    least one line ends `SHORT` or `UNALLOCATED`, the order moves to
    `PARTIALLY_ALLOCATED`."

    Design: Difficulty/non_linear_state_machine/reel_reserve_release_reserve_cycle_returns_to_allocated_partial
    """
    scn = _three_reel_pool_allocated_once()
    reel_400, reel_1000, _ = scn["reels"]
    order_line_id = scn["order_lines"][0]["id"]

    release_allocations(scn["order"]["id"], scn["branch"]["id"])
    run_allocator(
        scn["order"]["id"], scn["branch"]["id"], policy="MINIMIZE_REMNANT"
    )

    reserved_again = read_reel(reel_400["id"])
    assert reserved_again["status"] == "ALLOCATED_PARTIAL"
    assert reserved_again["allocated_length_ft"] == 300
    assert reserved_again["current_length_ft"] == 400
    assert reserved_again["available_length_ft"] == 100
    spare = read_reel(reel_1000["id"])
    assert spare["allocated_length_ft"] == 0
    assert spare["status"] == "IN_STOCK"

    assert read_order(scn["order"]["id"])["fulfillment_status"] == "ALLOCATED"
    assert read_order_line(order_line_id)["allocation_status"] == "FULLY_ALLOCATED"

    rows = allocations_of_line(order_line_id)
    assert len(rows) == 2, f"expected one released and one reserved row, got {rows}"
    assert sorted(r["status"] for r in rows) == ["RELEASED", "RESERVED"]


# ══════════════════════════════════════════════════════════════════════════
# Branch available footage is conserved across allocate and release
# ══════════════════════════════════════════════════════════════════════════

def _branch_available_footage(branch_id, product_id):
    """The available footage a branch holds for a part."""
    reels = list_reels(branch_id=branch_id, product_id=product_id)
    return sum(
        reel["current_length_ft"] - reel["allocated_length_ft"]
        for reel in reels
        if reel["status"] in ("IN_STOCK", "ALLOCATED_PARTIAL")
    )


def test_branch_available_footage_after_release_equals_the_figure_before(api):
    """PRD §3.6: "The available footage a branch holds for a part is the sum,
    over every reel of that part at that branch whose `status` is `IN_STOCK`
    or `ALLOCATED_PARTIAL`, of that reel's `current_length_ft` less its
    `allocated_length_ft`; reels that are `ON_JOBSITE`, `DEPLETED` or
    `SCRAPPED` contribute nothing."
    PRD §3.6: "Reserving footage and then releasing it must leave that figure
    exactly as it was before the reservation, and must leave every touched
    reel's `current_length_ft` untouched — reservations move numbers, not
    cable."

    Design: Difficulty/compensating_invariant/branch_available_footage_conserved_across_allocate_and_release
    """
    scn = _three_reel_pool_allocated_once()
    branch_id, product_id = scn["branch"]["id"], scn["product"]["id"]
    assert _branch_available_footage(branch_id, product_id) == 1350, (
        "the reservation of 300 ft drops the pool from 1650 to 1350"
    )

    release_allocations(scn["order"]["id"], scn["branch"]["id"])

    assert _branch_available_footage(branch_id, product_id) == 1650
    for reel, expected in zip(scn["reels"], (400, 1000, 250)):
        refreshed = read_reel(reel["id"])
        assert refreshed["current_length_ft"] == expected
        assert refreshed["allocated_length_ft"] == 0
        assert refreshed["available_length_ft"] == expected
        assert refreshed["status"] == "IN_STOCK"


def test_release_writes_off_no_scrap_and_leaves_the_allocation_released(api):
    """PRD §3.6: "Because nothing physical moved, the branch's available
    footage for the part is exactly what it was before the run."
    PRD §3.1: "A new branch also starts with `scrap_ft_ytd` initialised to 0 —
    a running total of the footage its cuts have written off, which the branch
    record accumulates over its lifetime and which is visible whenever the
    branch is read."
    PRD §3.6: "Every `RESERVED` allocation moves `RESERVED → RELEASED`; each
    release decrements its reel's `allocated_length_ft` by the allocation's
    `length_ft`, and a reel whose `allocated_length_ft` returns to 0 moves
    `ALLOCATED_PARTIAL → IN_STOCK` provided it still carries physical
    footage."

    Design: Difficulty/compensating_invariant/branch_available_footage_conserved_across_allocate_and_release
    """
    scn = _three_reel_pool_allocated_once()
    allocation_id = scn["allocations"][0]["id"]

    release_allocations(scn["order"]["id"], scn["branch"]["id"])

    assert read_allocation(allocation_id)["status"] == "RELEASED"
    assert read_branch(scn["branch"]["id"])["scrap_ft_ytd"] == 0
    line = read_order_line(scn["order_lines"][0]["id"])
    assert line["allocated_length_ft"] == 0
    assert line["allocation_status"] == "UNALLOCATED"
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "PENDING_ALLOCATION"


# ══════════════════════════════════════════════════════════════════════════
# An empty candidate pool is fatal to the whole run
# ══════════════════════════════════════════════════════════════════════════

def test_allocation_against_an_empty_branch_fails_with_no_eligible_reel(api):
    """PRD §3.6: "Only one outcome is fatal: if the entire run creates zero
    allocations across the whole order, the request fails with
    `ERR_NO_ELIGIBLE_REEL` and nothing whatsoever is persisted."
    PRD §3.6: "The candidate pool for a line is every reel of that line's
    `product_id` sitting at the order's `branch_id`, in `status` `IN_STOCK` or
    `ALLOCATED_PARTIAL`, with available footage strictly greater than 0."

    Design: Difficulty/boundary_precision_check/allocation_with_empty_candidate_pool_yields_no_eligible_reel
    """
    scn = setup_converted_order(
        [{"put_up": "CUT", "requested_length_ft": 300}], reels=[]
    )

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(scn["order"]["version"]),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_REEL.value)
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "PENDING_ALLOCATION"


def test_a_fatal_allocation_run_persists_no_allocation_rows(api):
    """PRD §3.6: "Only one outcome is fatal: if the entire run creates zero
    allocations across the whole order, the request fails with
    `ERR_NO_ELIGIBLE_REEL` and nothing whatsoever is persisted."
    PRD §3.6: "Afterwards each line's `allocated_length_ft` is recomputed as
    the sum of the `length_ft` of its allocations in `RESERVED`, `COMMITTED`
    or `CONSUMED` status, and its `allocation_status` becomes
    `FULLY_ALLOCATED` when that equals `required_length_ft`, `SHORT` when it
    is greater than 0 but less than `required_length_ft`, and `UNALLOCATED`
    when it is 0."

    Design: Difficulty/boundary_precision_check/allocation_with_empty_candidate_pool_yields_no_eligible_reel
    """
    scn = setup_converted_order(
        [{"put_up": "CUT", "requested_length_ft": 300}], reels=[]
    )
    order_line_id = scn["order_lines"][0]["id"]

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(scn["order"]["version"]),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_REEL.value)

    line = read_order_line(order_line_id)
    assert line["allocation_status"] == "UNALLOCATED"
    assert line["allocated_length_ft"] == 0
    assert allocations_of_order(scn["order"]["id"]) == []


# ══════════════════════════════════════════════════════════════════════════
# Allocation is gated on the customer's credit posture
# ══════════════════════════════════════════════════════════════════════════

def _short_order_then_credit_hold():
    scn = setup_allocated_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 200}],
        customer_overrides={"credit_limit_cents": 100_000},
    )
    # Restock the branch so a second allocation attempt would find eligible
    # footage. PRD §2.7 ranks "The allocation run produced at least one
    # allocation row across the whole order" (item 20) ahead of the credit
    # hold (item 26), so an empty pool would mask the check under test.
    receive_reel(scn["product"]["id"], scn["branch"]["id"],
                 nominal_length_ft=500, lot_code="L2")
    post_credit_adjustment(
        scn["customer"]["id"], delta_open_balance_cents=150_000,
        reason="manual invoice posted",
    )
    return scn


def test_allocation_is_refused_while_the_customer_is_on_credit_hold(api):
    """PRD §3.6: "The order must be in `PENDING_ALLOCATION` or
    `PARTIALLY_ALLOCATED`, otherwise `ERR_ORDER_NOT_ALLOCATABLE`; the customer
    must not be on credit hold, otherwise `ERR_CUSTOMER_CREDIT_HOLD`; and the
    operator's `X-User-ID` must equal the order's `branch_id`, otherwise
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.9: "A customer who is `ACTIVE` and whose recomputed available
    credit is below 0 moves `ACTIVE → CREDIT_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/allocate_on_partially_allocated_order_gated_by_customer_credit_status
    """
    scn = _short_order_then_credit_hold()
    current_version = read_order(scn["order"]["id"])["version"]

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(current_version),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value)
    account = read_customer(scn["customer"]["id"])
    assert account["credit_status"] == "CREDIT_HOLD"
    assert account["available_credit_cents"] == -50000


def test_a_partially_allocated_order_keeps_its_reservations_on_credit_hold(api):
    """PRD §3.9: "An order that is already `PARTIALLY_ALLOCATED` is treated
    differently on purpose: it keeps its reservations and its status, and is
    instead stopped at the next allocation attempt by
    `ERR_CUSTOMER_CREDIT_HOLD`."
    PRD §3.6: "The order then follows: if every line is `FULLY_ALLOCATED` the
    order moves to `ALLOCATED`; if at least one allocation was created but at
    least one line ends `SHORT` or `UNALLOCATED`, the order moves to
    `PARTIALLY_ALLOCATED`."

    Design: Difficulty/cross_entity_state_dependency/allocate_on_partially_allocated_order_gated_by_customer_credit_status
    """
    scn = _short_order_then_credit_hold()

    order = read_order(scn["order"]["id"])
    assert order["fulfillment_status"] == "PARTIALLY_ALLOCATED"
    line = read_order_line(scn["order_lines"][0]["id"])
    assert line["allocation_status"] == "SHORT"
    assert line["allocated_length_ft"] == 200
    assert read_reel(scn["reels"][0]["id"])["allocated_length_ft"] == 200


# ══════════════════════════════════════════════════════════════════════════
# Paralleled sets
# ══════════════════════════════════════════════════════════════════════════

def test_a_paralleled_set_cannot_be_filled_across_two_lots(api):
    """PRD §3.6: "When `parallel_set_size` is greater than 1, the same-lot,
    whole-conductor rule applies and is all-or-nothing: each of the paralleled
    conductors must be one continuous run, so each needs its own reel holding
    at least `billable_length_ft` of available footage, and all of them must
    share one mill lot."
    PRD §3.6: "If no lot can furnish the whole set, the run fails with
    `ERR_PARALLEL_SET_INCOMPLETE` — a paralleled set is never partially
    filled."

    Design: Corner/validations/parallel_set_cannot_be_filled_across_two_lots
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    reel_a = receive_reel(product["id"], branch["id"], 500, lot_code="LA")
    reel_b = receive_reel(product["id"], branch["id"], 500, lot_code="LB")
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 200, "parallel_set_size": 3}],
    )
    issue_quote(quote["id"], issuer="rep-2")
    order = convert_quote(quote["id"], issuer="rep-2")

    response = api.allocate_sales_order(
        order["id"],
        allocate_payload(order["version"]),
        make_branch_ops_headers(branch["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PARALLEL_SET_INCOMPLETE.value)
    assert read_reel(reel_a["id"])["allocated_length_ft"] == 0
    assert read_reel(reel_b["id"])["allocated_length_ft"] == 0
    assert read_order(order["id"])["fulfillment_status"] == "PENDING_ALLOCATION"
    assert allocations_of_order(order["id"]) == []


def test_a_paralleled_set_takes_three_best_fit_reels_from_one_lot(api):
    """PRD §3.6: "Distinct `lot_code` values among the candidates are examined
    in ascending lexical order, and the first lot offering at least
    `parallel_set_size` qualifying reels is chosen; the line's `lot_code` is
    pinned to it."
    PRD §3.6: "Within the chosen lot, reels are ranked by the active policy
    and the first `parallel_set_size` of them are taken, one allocation per
    reel, each for exactly `billable_length_ft`."
    PRD §3.6: "Under `MINIMIZE_REMNANT` — the policy used when
    `allocation_policy` is omitted — the allocator best-fits: among candidates
    whose available footage is at least the footage still needed for this
    pick, it chooses the one with the smallest available footage, so that the
    least usable cable is left behind."

    Design: Corner/validations/parallel_set_takes_three_distinct_best_fit_reels_from_one_lot
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    la = {
        length: receive_reel(product["id"], branch["id"], length, lot_code="LA")
        for length in (300, 400, 900, 1000, 150)
    }
    lb_1000 = receive_reel(product["id"], branch["id"], 1000, lot_code="LB")
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 200, "parallel_set_size": 3}],
    )
    issue_quote(quote["id"], issuer="rep-2")
    order = convert_quote(quote["id"], issuer="rep-2")

    response = api.allocate_sales_order(
        order["id"],
        allocate_payload(order["version"]),
        make_branch_ops_headers(branch["id"]),
    )
    validate_success(response, 200)

    order_line = list_order_lines(sales_order_id=order["id"])[0]
    rows = allocations_of_line(order_line["id"])
    order_line = read_order_line(order_line["id"])
    assert len(rows) == 3
    assert all(row["length_ft"] == 200 for row in rows)
    assert all(row["status"] == "RESERVED" for row in rows)
    for length in (300, 400, 900):
        assert read_reel(la[length]["id"])["allocated_length_ft"] == 200
    untouched = read_reel(la[1000]["id"])
    assert untouched["allocated_length_ft"] == 0
    assert untouched["status"] == "IN_STOCK"
    assert read_reel(la[150]["id"])["allocated_length_ft"] == 0
    assert read_reel(lb_1000["id"])["allocated_length_ft"] == 0
    assert order_line["lot_code"] == "LA"
    assert order_line["allocated_length_ft"] == 600
    assert order_line["allocation_status"] == "FULLY_ALLOCATED"
    assert read_order(order["id"])["fulfillment_status"] == "ALLOCATED"


# ══════════════════════════════════════════════════════════════════════════
# Optimistic concurrency and immediate consistency
# ══════════════════════════════════════════════════════════════════════════

def test_stale_expected_sales_order_version_on_allocate_is_rejected(api):
    """PRD §2.8: "Running the allocator over a sales order requires
    `expected_sales_order_version` as a non-optional field of the request
    body, carrying the client's last observed `version` of the target
    `SalesOrder`. If that value does not equal the order's current `version`,
    the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and no
    allocation row is created or altered."
    PRD §3.6: "The order's `allocation_policy` is set to whatever policy this
    run used."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_sales_order_version_on_allocate_returns_412
    """
    scn = setup_converted_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 200}],
    )
    version_at_conversion = scn["order"]["version"]
    run_allocator(
        scn["order"]["id"], scn["branch"]["id"],
        policy="MINIMIZE_REMNANT", expected_version=version_at_conversion,
    )
    # Restock so the re-run would produce an allocation row. PRD §2.7 ranks
    # ERR_NO_ELIGIBLE_REEL (item 20) ahead of the optimistic-concurrency
    # check (item 28), so an exhausted pool would mask the stale-version
    # guard this test is about.
    receive_reel(scn["product"]["id"], scn["branch"]["id"],
                 nominal_length_ft=500, lot_code="L2")

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(version_at_conversion, allocation_policy="FEWEST_REELS"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION.value)
    order = read_order(scn["order"]["id"])
    assert order["fulfillment_status"] == "PARTIALLY_ALLOCATED"
    assert order["allocation_policy"] == "MINIMIZE_REMNANT"
    assert read_reel(scn["reels"][0]["id"])["allocated_length_ft"] == 200
    assert len(allocations_of_order(scn["order"]["id"])) == 1


def test_allocation_side_effects_are_visible_in_the_same_request(api):
    """PRD §2.10: "First, cascades are immediate and synchronous: by the time
    the response is written, every downstream resource already reflects its
    new state, and no background job is involved."
    PRD §3.6: "For each allocation created, the holding reel's
    `allocated_length_ft` rises by that allocation's `length_ft`; a reel whose
    `allocated_length_ft` becomes greater than 0 moves `IN_STOCK →
    ALLOCATED_PARTIAL`, and its `available_length_ft` is recomputed."
    PRD §2.4: "The `version` of a resource is 1 when the resource is created
    and increases by exactly 1 on every mutation of that resource;
    `updated_at` is refreshed to the current logical instant on the same
    mutations."

    Design: Corner/consistency_model/immediate_consistency_derived_fields_are_visible_in_the_same_response
    """
    scn = setup_converted_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 1000}],
    )

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(scn["order"]["version"]),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    order_in_response = validate_success(response, 200)

    assert order_in_response["fulfillment_status"] == "ALLOCATED"
    reel = read_reel(scn["reels"][0]["id"])
    assert reel["allocated_length_ft"] == 300
    assert reel["available_length_ft"] == 700
    assert reel["status"] == "ALLOCATED_PARTIAL"
    assert read_order_line(scn["order_lines"][0]["id"])["allocation_status"] == (
        "FULLY_ALLOCATED"
    )
    assert read_order(scn["order"]["id"])["version"] == 2
