"""The commit fork: cutting footage, picking whole reels and the cut floor."""


from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    commit_cut,
    cut_payload,
    list_allocations,
    list_order_lines,
    list_reels,
    make_branch_ops_headers,
    read_allocation,
    read_order,
    read_reel,
    setup_allocated_order,
    validate_error,
    validate_success,
)

CUT_LINE = {"put_up": "CUT", "requested_length_ft": 300}
MASTER_LINE = {"put_up": "MASTER_REEL", "requested_length_ft": 2500}


def _mixed_order_allocated():
    """A two-line order — one CUT line of 300 ft and one MASTER_REEL line of
    2500 ft — allocated against a 500 ft reel and an untouched master reel."""
    return setup_allocated_order(
        [CUT_LINE, MASTER_LINE],
        reels=[{"nominal_length_ft": 500}, {"nominal_length_ft": 2500}],
        policy="MINIMIZE_REMNANT",
    )


def test_cut_commit_spawns_a_remnant_and_depletes_the_source_reel(api):
    """PRD §3.7: "A permitted cut confirms the tiered charge into
    `cut_charge_applied_cents`, recomputing it from the order line's
    `billable_length_ft` and the part's `cut_charge_cents` under exactly the
    tier rules of Section 3.3, and stamps `cut_window_start` and
    `cut_window_end` onto the allocation."
    PRD §3.7: "Four: otherwise, if the reel's `reel_type` is `MASTER`, the
    viable remainder becomes a new reel — a fresh record with `reel_type`
    `REMNANT`, `parent_reel_id` pointing at the reel it came off, and
    `lot_code`, `product_id` and `branch_id` inherited from it, whose
    `nominal_length_ft` and `current_length_ft` both equal the remainder and
    whose `status` is `IN_STOCK`; the new reel's identifier is recorded on the
    cutting allocation as `remnant_reel_id`, and the source reel's
    `current_length_ft` is then set to 0 and the source reel moves to
    `DEPLETED`."

    Design: Difficulty/non_linear_state_machine/allocation_commit_fork_cut_and_pick_have_disjoint_side_effects
    """
    scn = _mixed_order_allocated()
    cut_allocation_id = scn["allocations_by_line"][0][0]["id"]
    source_reel_id = scn["reels"][0]["id"]

    commit_cut(
        cut_allocation_id, scn["branch"]["id"],
        "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z",
    )

    allocation = read_allocation(cut_allocation_id)
    assert allocation["commit_mode"] == "CUT"
    assert allocation["cut_charge_applied_cents"] == 3500
    assert allocation["scrap_ft"] == 0
    assert allocation["remnant_reel_id"] is not None

    source = read_reel(source_reel_id)
    assert source["status"] == "DEPLETED"
    assert source["current_length_ft"] == 0

    remnants = list_reels(parent_reel_id=source_reel_id)
    assert len(remnants) == 1, f"exactly one remnant is spawned, got {remnants}"
    remnant = remnants[0]
    assert remnant["reel_type"] == "REMNANT"
    assert remnant["current_length_ft"] == 200
    assert remnant["nominal_length_ft"] == 200
    assert remnant["status"] == "IN_STOCK"
    assert remnant["id"] == allocation["remnant_reel_id"]


def test_pick_commit_leaves_the_reel_intact_and_stages_the_order(api):
    """PRD §3.7: "It sets `commit_mode` to `PICK` and leaves
    `cut_window_start`, `cut_window_end`, `cut_charge_applied_cents`,
    `scrap_ft` and `remnant_reel_id` at their defaults — there is no cut
    window to reserve, no cut-floor capacity to test, no cut charge to apply,
    no remnant to spawn and no footage to scrap."
    PRD §3.7: "The reel's `current_length_ft`, `allocated_length_ft` and
    `status` are all left exactly as they are, because the whole reel travels
    intact and stays reserved to this order until it physically leaves."
    PRD §3.7: "When the commit that just happened was the last one — that is,
    when every allocation on the order has reached `COMMITTED` — the order
    bubbles up `ALLOCATED → STAGED` on its fulfilment axis, and the goods are
    ready for a truck."

    Design: Difficulty/non_linear_state_machine/allocation_commit_fork_cut_and_pick_have_disjoint_side_effects
    """
    scn = _mixed_order_allocated()
    cut_allocation_id = scn["allocations_by_line"][0][0]["id"]
    pick_allocation_id = scn["allocations_by_line"][1][0]["id"]
    master_reel_id = scn["reels"][1]["id"]

    commit_cut(
        cut_allocation_id, scn["branch"]["id"],
        "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z",
    )
    response = api.pick_allocation(
        pick_allocation_id, make_branch_ops_headers(scn["branch"]["id"])
    )
    validate_success(response, 200)

    allocation = read_allocation(pick_allocation_id)
    assert allocation["commit_mode"] == "PICK"
    assert allocation["cut_charge_applied_cents"] == 0
    assert allocation["remnant_reel_id"] is None
    assert allocation["cut_window_start"] is None
    assert allocation["cut_window_end"] is None
    assert allocation["scrap_ft"] == 0

    reel = read_reel(master_reel_id)
    assert reel["current_length_ft"] == 2500
    assert reel["allocated_length_ft"] == 2500
    assert reel["status"] == "ALLOCATED_PARTIAL"

    assert read_order(scn["order"]["id"])["fulfillment_status"] == "STAGED"


# ══════════════════════════════════════════════════════════════════════════
# The cut floor: closed endpoints plus a thirty-minute cleanup buffer
# ══════════════════════════════════════════════════════════════════════════

def _two_cut_lines_allocated_on_one_reel():
    return setup_allocated_order(
        [CUT_LINE, dict(CUT_LINE)],
        reels=[{"nominal_length_ft": 1000}],
        policy="MINIMIZE_REMNANT",
    )


def test_cut_starting_on_a_buffered_window_boundary_is_a_collision(api):
    """PRD §3.7: "The window a cut actually consumes is not the window
    requested: a cleanup buffer of thirty minutes is appended to the end, and
    the cut is treated as occupying the closed interval from
    `cut_window_start` through `cut_window_end` plus thirty minutes."
    PRD §3.7: "The requested interval collides with such an existing interval
    when the requested start is at or before the existing `cut_window_end`
    plus thirty minutes, and the existing `cut_window_start` is at or before
    the requested buffered end."
    PRD §3.7: "Both comparisons are inclusive, so touching endpoints collide —
    a cut starting at exactly the instant a previous cut's buffered window
    ends is a collision, not an adjacency."
    PRD §3.7: "If the number of colliding intervals reaches the branch's
    `concurrent_cut_capacity`, the request is refused with
    `ERR_CUT_BAY_CAPACITY_EXCEEDED`; a branch with capacity 1 therefore admits
    a cut only when nothing else overlaps it."

    Design: Difficulty/resource_temporal_overlap/cut_floor_closed_buffered_window_aggregate_with_adjacency_rejected
    """
    scn = _two_cut_lines_allocated_on_one_reel()
    first, second = scn["allocations"][0], scn["allocations"][1]
    commit_cut(
        first["id"], scn["branch"]["id"],
        "2026-08-10T08:00:00Z", "2026-08-10T09:00:00Z",
    )

    response = api.cut_allocation(
        second["id"],
        cut_payload("2026-08-10T09:30:00Z", "2026-08-10T10:30:00Z"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CUT_BAY_CAPACITY_EXCEEDED.value)
    assert read_allocation(second["id"])["status"] == "RESERVED"


def test_cut_one_minute_past_the_buffered_window_is_admitted(api):
    """PRD §3.7: "Both comparisons are inclusive, so touching endpoints
    collide — a cut starting at exactly the instant a previous cut's buffered
    window ends is a collision, not an adjacency."
    PRD §3.7: "A permitted cut confirms the tiered charge into
    `cut_charge_applied_cents`, recomputing it from the order line's
    `billable_length_ft` and the part's `cut_charge_cents` under exactly the
    tier rules of Section 3.3, and stamps `cut_window_start` and
    `cut_window_end` onto the allocation."
    PRD §3.7: "When the commit that just happened was the last one — that is,
    when every allocation on the order has reached `COMMITTED` — the order
    bubbles up `ALLOCATED → STAGED` on its fulfilment axis, and the goods are
    ready for a truck."

    Design: Difficulty/resource_temporal_overlap/cut_floor_closed_buffered_window_aggregate_with_adjacency_rejected
    """
    scn = _two_cut_lines_allocated_on_one_reel()
    first, second = scn["allocations"][0], scn["allocations"][1]
    source_reel_id = scn["reels"][0]["id"]
    commit_cut(
        first["id"], scn["branch"]["id"],
        "2026-08-10T08:00:00Z", "2026-08-10T09:00:00Z",
    )

    response = api.cut_allocation(
        second["id"],
        cut_payload("2026-08-10T09:31:00Z", "2026-08-10T10:31:00Z"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    validate_success(response, 200)

    allocation = read_allocation(second["id"])
    assert allocation["status"] == "COMMITTED"
    assert allocation["commit_mode"] == "CUT"
    assert_same_instant(
        allocation["cut_window_start"], "2026-08-10T09:31:00Z",
        "Allocation.cut_window_start",
    )
    assert allocation["cut_charge_applied_cents"] == 3500

    source = read_reel(source_reel_id)
    assert source["status"] == "DEPLETED"
    assert source["current_length_ft"] == 0
    remnants = list_reels(parent_reel_id=source_reel_id)
    assert len(remnants) == 1
    assert remnants[0]["current_length_ft"] == 400
    assert remnants[0]["reel_type"] == "REMNANT"
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "STAGED"


# ══════════════════════════════════════════════════════════════════════════
# Admission order: the put-up match is decided before the cut-floor capacity
# ══════════════════════════════════════════════════════════════════════════

def _mixed_order_with_the_bay_already_occupied():
    scn = _mixed_order_allocated()
    commit_cut(
        scn["allocations_by_line"][0][0]["id"], scn["branch"]["id"],
        "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z",
    )
    return scn


def test_put_up_mismatch_is_reported_before_cut_bay_capacity(api):
    """PRD §2.7: "Checks are evaluated in the fixed order below; the first
    violated check determines the response, and no later check is evaluated.
    The lowest number wins."
    PRD §2.7: "The commit branch matches the line's put-up: a cut requires the
    order line's `put_up` to be `CUT` and a pick requires it to be
    `MASTER_REEL` — otherwise `ERR_PUT_UP_MISMATCH` (409), on the allocation
    cut and allocation pick endpoints."
    PRD §2.7: "The buffered cut window collides with fewer than the branch's
    `concurrent_cut_capacity` existing buffered windows at that branch —
    otherwise `ERR_CUT_BAY_CAPACITY_EXCEEDED` (409), on the allocation cut
    endpoint."

    Design: Difficulty/priority_pair_validation_conflict/put_up_mismatch_referential_beats_cut_bay_capacity_temporal
    """
    scn = _mixed_order_with_the_bay_already_occupied()
    master_allocation_id = scn["allocations_by_line"][1][0]["id"]

    response = api.cut_allocation(
        master_allocation_id,
        cut_payload("2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PUT_UP_MISMATCH.value)


def test_a_rejected_cut_leaves_the_master_reel_allocation_untouched(api):
    """PRD §3.7: "Choosing the wrong branch for the line is rejected with
    `ERR_PUT_UP_MISMATCH`: cutting is only for a `CUT` line, picking only for
    a `MASTER_REEL` line."
    PRD §3.7: "The reel's `current_length_ft`, `allocated_length_ft` and
    `status` are all left exactly as they are, because the whole reel travels
    intact and stays reserved to this order until it physically leaves."

    Design: Difficulty/priority_pair_validation_conflict/put_up_mismatch_referential_beats_cut_bay_capacity_temporal
    """
    scn = _mixed_order_with_the_bay_already_occupied()
    master_allocation_id = scn["allocations_by_line"][1][0]["id"]
    master_reel_id = scn["reels"][1]["id"]

    response = api.cut_allocation(
        master_allocation_id,
        cut_payload("2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PUT_UP_MISMATCH.value)

    allocation = read_allocation(master_allocation_id)
    assert allocation["status"] == "RESERVED"
    assert allocation["commit_mode"] is None
    assert read_reel(master_reel_id)["current_length_ft"] == 2500


# ══════════════════════════════════════════════════════════════════════════
# Commit-fork corners
# ══════════════════════════════════════════════════════════════════════════

def test_picking_an_already_committed_allocation_is_rejected(api):
    """PRD §3.7: "Both branches are driven by the `BranchOps` operator who
    owns the reel's `branch_id`, both require the allocation to still be
    `RESERVED` (otherwise `ERR_ALLOCATION_NOT_RESERVED`), and both move the
    allocation `RESERVED → COMMITTED` while recording which branch was taken
    in `commit_mode`, valued `CUT` or `PICK`."

    Design: Corner/state_machines/second_pick_on_committed_allocation_returns_allocation_not_reserved
    """
    scn = setup_allocated_order(
        [MASTER_LINE], reels=[{"nominal_length_ft": 2500}]
    )
    allocation_id = scn["allocations"][0]["id"]
    branch_ops = make_branch_ops_headers(scn["branch"]["id"])
    validate_success(api.pick_allocation(allocation_id, branch_ops), 200)

    response = api.pick_allocation(allocation_id, branch_ops)

    validate_error(response, ApiErrorId.ERR_ALLOCATION_NOT_RESERVED.value)
    allocation = read_allocation(allocation_id)
    assert allocation["status"] == "COMMITTED"
    assert allocation["commit_mode"] == "PICK"
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "STAGED"


def test_cut_window_ending_at_its_start_is_rejected(api):
    """PRD §3.7: "Cutting occupies the branch's cut floor, so the request
    supplies the two instants `cut_window_start` and `cut_window_end`. The end
    must be strictly after the start, otherwise `ERR_INVALID_CUT_WINDOW`."

    Design: Corner/validations/cut_window_end_equal_to_start_returns_invalid_cut_window
    """
    scn = setup_allocated_order(
        [CUT_LINE], reels=[{"nominal_length_ft": 1000}]
    )
    allocation_id = scn["allocations"][0]["id"]

    response = api.cut_allocation(
        allocation_id,
        cut_payload("2026-08-02T08:00:00Z", "2026-08-02T08:00:00Z"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CUT_WINDOW.value)
    allocation = read_allocation(allocation_id)
    assert allocation["status"] == "RESERVED"
    assert allocation["commit_mode"] is None
    reel = read_reel(scn["reels"][0]["id"])
    assert reel["current_length_ft"] == 1000
    assert reel["allocated_length_ft"] == 300


def test_every_declared_foreign_key_is_reverse_reachable_from_its_list(api):
    """PRD §3.6: "Reels can be listed and narrowed by `branch_id`,
    `product_id`, `status`, `lot_code` and `reel_type`; filtering on
    `parent_reel_id` finds every remnant spawned from a given reel, and
    filtering on `delivered_sales_order_id` finds the reels a customer is
    currently holding at a jobsite."
    PRD §3.6: "Allocations can be read individually or listed, narrowed by
    `order_line_id`, `sales_order_id`, `reel_id`, `status`, or by
    `remnant_reel_id` to find the cut that produced a given remnant."
    PRD §3.5: "Orders and their lines can be listed and narrowed by
    `customer_id`, `quote_id`, `branch_id`, `fulfillment_status`,
    `billing_status`, `sales_order_id`, `product_id` or `allocation_status`."

    Design: Corner/endpoints/filtered_child_lists_resolve_every_declared_foreign_key
    """
    scn = setup_allocated_order(
        [CUT_LINE], reels=[{"nominal_length_ft": 1000}]
    )
    allocation_id = scn["allocations"][0]["id"]
    source_reel_id = scn["reels"][0]["id"]
    order_line_id = scn["order_lines"][0]["id"]
    commit_cut(
        allocation_id, scn["branch"]["id"],
        "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z",
    )

    remnants = list_reels(parent_reel_id=source_reel_id)
    assert len(remnants) == 1
    remnant = remnants[0]
    assert remnant["reel_type"] == "REMNANT"
    assert remnant["current_length_ft"] == 700
    assert remnant["parent_reel_id"] == source_reel_id

    cutting = list_allocations(remnant_reel_id=remnant["id"])
    assert [row["id"] for row in cutting] == [allocation_id]
    assert read_allocation(allocation_id)["remnant_reel_id"] == remnant["id"]

    lines = list_order_lines(sales_order_id=scn["order"]["id"])
    assert [row["id"] for row in lines] == [order_line_id]
