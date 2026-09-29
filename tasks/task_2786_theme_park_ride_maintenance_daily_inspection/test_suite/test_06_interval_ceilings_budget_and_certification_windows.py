"""Inclusive thresholds: testing intervals, the parts ceiling and interval overlap.

Each of these boundaries is stated inclusively in the contract, so a value sitting
exactly on the threshold has a decided outcome rather than an ambiguous one.
"""

from test_helpers import (
    MANAGER,
    TECHNICIAN,
    api_client,
    assert_component,
    assert_component_install_baseline,
    assert_operator_certification,
    assert_part_requisition,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"


def _steel_vortex_axle():
    """A safety-critical axle on a 50,000-cycle interval with a distant day interval."""
    attraction = fixtures.create_attraction(
        name="Steel Vortex",
        park_area="SKYLINE",
        manufacturer="B&M",
        model_code="IV-2",
        ride_class="THRILL",
        theoretical_hourly_capacity=1200,
        min_operators_required=3,
        parts_budget_cents=8000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Wheel bogie axle",
        component_type="AXLE",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=50000,
        ndt_interval_days=3650,
    )
    return {"attraction": attraction, "component": component}


def test_the_cycle_interval_comparison_is_inclusive_at_the_interval():
    """One cycle short of the interval is still current; landing on it is already due.

    PRD §3.1: "The component is **due by cycles** when the cycles elapsed is greater
    than or equal to `ndt_interval_cycles`, and **due by days** when the days elapsed
    is greater than or equal to `ndt_interval_days`."
    PRD §3.1: "Both comparisons are inclusive, so a cycles-elapsed figure exactly
    equal to `ndt_interval_cycles` is already `DUE` rather than still `CURRENT`."

    Design: Difficulty/boundary_precision_check/ndt_cycle_interval_and_grace_ceiling_are_inclusive_at_50000_and_60000
    """
    bundle = _steel_vortex_axle()
    baseline = fixtures.read_component(bundle["component"]["id"])
    assert_component(baseline)
    assert_component_install_baseline(baseline, CLOCK_START, 0)

    fixtures.log_cycles(bundle["attraction"]["id"], 49999, "2026-08-01")
    assert fixtures.read_component(bundle["component"]["id"])["ndt_status"] == "CURRENT"

    fixtures.log_cycles(bundle["attraction"]["id"], 1, "2026-08-01")
    assert fixtures.read_component(bundle["component"]["id"])["ndt_status"] == "DUE"


def test_the_grace_ceiling_is_inclusive_and_forces_the_attraction_down():
    """One cycle short of the ceiling is still due; landing on it is overdue.

    PRD §3.1: "It is **overdue by cycles** when the cycles elapsed is greater than or
    equal to `ndt_interval_cycles` multiplied by a grace factor of 1.20 and rounded
    up to a whole number".
    PRD §2.8: "`DOWN` — if any of the following holds: the attraction has a downtime
    event whose `status` is `OPEN`, `DIAGNOSED`, `AWAITING_PARTS` or `RESOLVED`; or
    any component of the attraction whose `criticality` is `SAFETY_CRITICAL` derives
    an `ndt_status` of `OVERDUE`; or the attraction's daily inspection for the current
    service date has a `status` of `BLOCKED`."

    Design: Difficulty/boundary_precision_check/ndt_cycle_interval_and_grace_ceiling_are_inclusive_at_50000_and_60000
    """
    bundle = _steel_vortex_axle()
    fixtures.log_cycles(bundle["attraction"]["id"], 59999, "2026-08-01")
    assert fixtures.read_component(bundle["component"]["id"])["ndt_status"] == "DUE"

    fixtures.log_cycles(bundle["attraction"]["id"], 1, "2026-08-01")
    component = fixtures.read_component(bundle["component"]["id"])
    assert component["ndt_status"] == "OVERDUE"
    assert fixtures.ndt_overdue_cycle_ceiling(50000) == 60000

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["cumulative_cycles"] == 60000
    assert attraction["operational_posture"] == "DOWN"


def _harbor_hopper_requisitions():
    """Three requisitions worth 750000, 250000 and 1 cent against a 1000000 ceiling."""
    attraction = fixtures.create_attraction(
        name="Harbor Hopper",
        park_area="LAGOON",
        manufacturer="Zierer",
        model_code="HH-6",
        ride_class="FAMILY",
        theoretical_hourly_capacity=520,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    first = fixtures.create_requisition(
        attraction["id"],
        part_number="P-750",
        quantity=3,
        unit_cost_cents=250000,
        needed_by_date="2026-08-20",
    )
    second = fixtures.create_requisition(
        attraction["id"],
        part_number="P-250",
        quantity=1,
        unit_cost_cents=250000,
        needed_by_date="2026-08-20",
    )
    third = fixtures.create_requisition(
        attraction["id"],
        part_number="P-001",
        quantity=1,
        unit_cost_cents=1,
        needed_by_date="2026-08-20",
    )
    return {
        "attraction": attraction,
        "first": first,
        "second": second,
        "third": third,
    }


def test_a_commitment_that_lands_exactly_on_the_ceiling_is_permitted():
    """Equality with the budget ceiling is legal, not a refusal.

    PRD §3.5: "Both are refused under exactly the same fiscal ceiling: if the
    attraction's current `parts_budget_committed_cents` plus this requisition's
    `total_cost_cents` would come to more than the attraction's `parts_budget_cents`,
    the commitment is refused with `ERR_PARTS_BUDGET_EXCEEDED` and HTTP 402.
    Equality is permitted — a commitment that lands the committed total exactly on
    the ceiling succeeds."
    PRD §3.5: "Reserving a requisition that is `REQUESTED` moves it `REQUESTED` →
    `RESERVED` and adds its `total_cost_cents` to the attraction's
    `parts_budget_committed_cents`."

    Design: Difficulty/boundary_precision_check/parts_budget_ceiling_permits_exact_equality_and_refuses_one_extra_cent
    """
    bundle = _harbor_hopper_requisitions()

    first = validate_success(
        api_client.reserve_part_requisition(bundle["first"]["id"], MANAGER)
    )
    assert_part_requisition(first)
    assert first["total_cost_cents"] == 750000
    assert (
        fixtures.read_attraction(bundle["attraction"]["id"])[
            "parts_budget_committed_cents"
        ]
        == 750000
    )

    second = validate_success(
        api_client.reserve_part_requisition(bundle["second"]["id"], MANAGER)
    )
    assert second["status"] == "RESERVED"
    assert (
        fixtures.read_attraction(bundle["attraction"]["id"])[
            "parts_budget_committed_cents"
        ]
        == 1000000
    )


def test_one_extra_cent_is_refused_on_both_commitment_routes():
    """Reserve and backorder share one ceiling, and neither admits a single cent over.

    PRD §2.6: "`ERR_PARTS_BUDGET_EXCEEDED` (402) — committing a requisition must not
    push the attraction's committed parts spend above its parts budget ceiling.
    Guards exactly two operations: reserving a requisition, and backordering one."
    PRD §3.5: "Nothing is committed against the budget while a requisition is merely
    `REQUESTED`."

    Design: Difficulty/boundary_precision_check/parts_budget_ceiling_permits_exact_equality_and_refuses_one_extra_cent
    """
    bundle = _harbor_hopper_requisitions()
    fixtures.walk_requisition_to(bundle["first"], "RESERVED")
    fixtures.walk_requisition_to(bundle["second"], "RESERVED")

    reserve = api_client.reserve_part_requisition(bundle["third"]["id"], MANAGER)
    validate_error(reserve, "ERR_PARTS_BUDGET_EXCEEDED", 402)

    backorder = api_client.backorder_part_requisition(
        bundle["third"]["id"], MANAGER, {"expected_availability_date": "2026-09-01"}
    )
    validate_error(backorder, "ERR_PARTS_BUDGET_EXCEEDED", 402)

    third = validate_success(
        api_client.get_part_requisition(bundle["third"]["id"], TECHNICIAN)
    )
    assert third["status"] == "REQUESTED"
    assert (
        fixtures.read_attraction(bundle["attraction"]["id"])[
            "parts_budget_committed_cents"
        ]
        == 1000000
    )


def _copper_canyon_requisitions():
    """Four requisitions worth 500000, 300000, 100000 and 700000 cents."""
    attraction = fixtures.create_attraction(
        name="Copper Canyon Rapids",
        park_area="FRONTIER",
        manufacturer="Intamin",
        model_code="CC-8",
        ride_class="WATER",
        theoretical_hourly_capacity=1100,
        min_operators_required=3,
        parts_budget_cents=1000000,
    )
    specs = [
        ("PR-A", 2, 250000, "2026-08-25"),
        ("PR-B", 3, 100000, "2026-08-26"),
        ("PR-C", 1, 100000, "2026-08-27"),
        ("PR-D", 7, 100000, "2026-08-28"),
    ]
    rows = [
        fixtures.create_requisition(
            attraction["id"],
            part_number=part_number,
            quantity=quantity,
            unit_cost_cents=unit_cost_cents,
            needed_by_date=needed_by_date,
        )
        for part_number, quantity, unit_cost_cents, needed_by_date in specs
    ]
    return {"attraction": attraction, "rows": rows}


def test_cancelling_a_committed_requisition_releases_exactly_its_total():
    """The reverse leg subtracts precisely what the forward leg added.

    PRD §2.9: "Reserving or backordering a requisition adds that requisition's
    `total_cost_cents` to the counter; cancelling a requisition that was `RESERVED`
    or `BACKORDERED` subtracts exactly that amount back out".
    PRD §3.5: "Cancelling a `RESERVED` or `BACKORDERED` requisition subtracts
    exactly its `total_cost_cents` back out of the attraction's
    `parts_budget_committed_cents`, restoring the counter to its precise
    pre-commitment value."

    Design: Difficulty/compensating_invariant/requisition_cancel_releases_exactly_what_it_committed_and_requested_cancel_is_a_no_op
    """
    bundle = _copper_canyon_requisitions()
    first, second, _third, fourth = bundle["rows"]
    attraction_id = bundle["attraction"]["id"]

    fixtures.walk_requisition_to(first, "RESERVED")
    fixtures.walk_requisition_to(second, "BACKORDERED", "2026-09-05")
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"]
        == 800000
    )

    validate_success(
        api_client.cancel_part_requisition(
            first["id"],
            factories.cancel_requisition_payload("Superseded by the rebuild kit"),
            MANAGER,
        )
    )
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"]
        == 300000
    )

    released = validate_success(
        api_client.reserve_part_requisition(fourth["id"], MANAGER)
    )
    assert released["status"] == "RESERVED"
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"]
        == 1000000
    )
    assert released["total_cost_cents"] == 700000

    cancelled = validate_success(
        api_client.get_part_requisition(first["id"], TECHNICIAN)
    )
    assert cancelled["total_cost_cents"] == 500000


def test_cancelling_a_requested_requisition_and_receiving_both_move_no_money():
    """Two lifecycle steps deliberately leave the committed counter alone.

    PRD §2.9: "cancelling one that was still `REQUESTED` moves the counter not at
    all, because nothing had been committed; and receiving a requisition moves the
    counter not at all either, because `RECEIVED` stays inside the committed set."
    PRD §3.5: "Cancelling a `REQUESTED` requisition changes no ledger at all, because
    nothing had been committed."

    Design: Difficulty/compensating_invariant/requisition_cancel_releases_exactly_what_it_committed_and_requested_cancel_is_a_no_op
    """
    bundle = _copper_canyon_requisitions()
    first, second, third, _fourth = bundle["rows"]
    attraction_id = bundle["attraction"]["id"]

    fixtures.walk_requisition_to(first, "RESERVED")
    fixtures.walk_requisition_to(second, "BACKORDERED", "2026-09-05")
    fixtures.walk_requisition_to(first, "CANCELLED")

    validate_success(
        api_client.cancel_part_requisition(
            third["id"],
            factories.cancel_requisition_payload("Ordered in error"),
            MANAGER,
        )
    )
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"]
        == 300000
    )

    received = validate_success(
        api_client.receive_part_requisition(second["id"], TECHNICIAN)
    )
    assert received["status"] == "RECEIVED"
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"]
        == 300000
    )


def _two_lifts_for_one_operator():
    first = fixtures.create_attraction(
        name="Cliffside Chairlift",
        park_area="SKYLINE",
        manufacturer="Doppelmayr",
        model_code="CL-2",
        ride_class="FAMILY",
        theoretical_hourly_capacity=900,
        min_operators_required=2,
        parts_budget_cents=1100000,
    )
    second = fixtures.create_attraction(
        name="Meadow Monorail",
        park_area="KIDS_COVE",
        manufacturer="Doppelmayr",
        model_code="MM-3",
        ride_class="KIDDIE",
        theoretical_hourly_capacity=400,
        min_operators_required=1,
        parts_budget_cents=700000,
    )
    incumbent = fixtures.create_certification(
        first["id"],
        operator_user_id="op-20",
        effective_from="2026-08-01T00:00:00.000Z",
        expires_at="2026-09-01T00:00:00.000Z",
        restraint_verification_score=91,
        dispatch_procedure_score=86,
    )
    return {"first": first, "second": second, "incumbent": incumbent}


def test_exact_adjacency_is_not_a_certification_window_overlap():
    """A window starting on the incumbent's exclusive end instant is accepted.

    PRD §3.7: "Exact adjacency is not an overlap and is accepted: a new certification
    whose `effective_from` equals an existing one's `expires_at`, or whose
    `expires_at` equals an existing one's `effective_from`, is perfectly legal."
    PRD §3.7: "Otherwise, if the clock is still before `effective_from`, the status
    is `TRAINEE`, because a future-dated certification is not yet in force."

    Design: Difficulty/resource_temporal_overlap/certification_half_open_intervals_accept_exact_adjacency_and_split_on_one_second
    """
    bundle = _two_lifts_for_one_operator()
    assert bundle["incumbent"]["status"] == "CERTIFIED"

    adjacent = validate_success(
        api_client.create_operator_certification(
            factories.create_operator_certification_payload(
                bundle["first"]["id"],
                operator_user_id="op-20",
                effective_from="2026-09-01T00:00:00.000Z",
                expires_at="2026-10-01T00:00:00.000Z",
                restraint_verification_score=93,
                dispatch_procedure_score=88,
            ),
            MANAGER,
        ),
        201,
    )
    assert_operator_certification(adjacent)
    assert adjacent["status"] == "TRAINEE"

    assert (
        fixtures.read_attraction(bundle["first"]["id"])["certified_operator_count"] == 1
    )


def test_a_one_second_intrusion_overlaps_but_only_on_the_same_attraction():
    """The exclusion key is the attraction and operator pair, not the operator alone.

    PRD §3.7: "A requested interval is refused with
    `ERR_CERTIFICATION_WINDOW_OVERLAP` when it intersects an existing certification's
    interval for the same operator on the same attraction for a positive duration."
    PRD §3.7: "Certification validity is a **half-open** interval — the instant
    `effective_from` is inside the interval and the instant `expires_at` is outside
    it — and for any one pairing of `attraction_id` and `operator_user_id` those
    intervals must be strictly pairwise exclusive with no buffer of any kind."

    Design: Difficulty/resource_temporal_overlap/certification_half_open_intervals_accept_exact_adjacency_and_split_on_one_second
    """
    bundle = _two_lifts_for_one_operator()
    fixtures.create_certification(
        bundle["first"]["id"],
        operator_user_id="op-20",
        effective_from="2026-09-01T00:00:00.000Z",
        expires_at="2026-10-01T00:00:00.000Z",
        restraint_verification_score=93,
        dispatch_procedure_score=88,
    )

    intruding = api_client.create_operator_certification(
        factories.create_operator_certification_payload(
            bundle["first"]["id"],
            operator_user_id="op-20",
            effective_from="2026-08-31T23:59:59.000Z",
            expires_at="2026-09-30T00:00:00.000Z",
            restraint_verification_score=93,
            dispatch_procedure_score=88,
        ),
        MANAGER,
    )
    validate_error(intruding, "ERR_CERTIFICATION_WINDOW_OVERLAP", 409)

    elsewhere = validate_success(
        api_client.create_operator_certification(
            factories.create_operator_certification_payload(
                bundle["second"]["id"],
                operator_user_id="op-20",
                effective_from="2026-08-01T00:00:00.000Z",
                expires_at="2026-09-01T00:00:00.000Z",
                restraint_verification_score=91,
                dispatch_procedure_score=86,
            ),
            MANAGER,
        ),
        201,
    )
    assert elsewhere["status"] == "CERTIFIED"

    assert (
        fixtures.read_attraction(bundle["second"]["id"])["certified_operator_count"] == 1
    )

    rows, _meta = validate_paginated(
        api_client.list_operator_certifications(
            MANAGER, params={"operator_user_id": "op-20", "limit": 100}
        )
    )
    assert len(rows) == 3
