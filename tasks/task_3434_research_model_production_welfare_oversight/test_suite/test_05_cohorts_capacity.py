"""Room cage accounting (aggregate capacity with per-cohort ceilings), the
partial-cull bookkeeping, and allocation-release terminal idempotency.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    allocate_order_to_cohort,
    api_client,
    compute_occupied_cages,
    create_colony_in_room,
    create_cohort_in_colony,
    create_cohort_payload,
    find_protocol_in_facility,
    read_cohort,
    read_room,
    release_allocation_and_refresh,
    setup_colony_with_cohorts,
    setup_production_site,
    setup_sourcing_order,
    transition_colony,
    transition_cohort,
    validate_error,
)

_FM = TEST_USERS["facility_manager_headers"]
_VET = TEST_USERS["veterinarian_headers"]


def test_room_cage_aggregate_capacity_boundary():
    """PRD Section 3.4: "recording a cohort requires `occupied_cages` plus the
    ceiling of the new cohort's total headcount divided by 5 to be less than
    or equal to `cage_capacity`; exceeding capacity in either case is
    `ERR_CAGE_CAPACITY_EXCEEDED` (HTTP 422)."
    PRD Section 3.4: "The ceiling is taken per cohort before the per-cohort
    results are summed".

    Design: Difficulty/resource_temporal_overlap/room_cage_aggregate_capacity_boundary
    """
    site = setup_production_site(room_overrides={"cage_capacity": 10})
    colony = create_colony_in_room(site, breeding_pair_count=4)
    transition_colony(colony["id"], "EXPANDING")

    # 4 pair cages + ceil(25/5) = 5 cohort cages -> 9 of 10 occupied.
    cohort = create_cohort_in_colony(colony["id"], count_male=13, count_female=12)
    assert cohort["id"]
    room = read_room(site["room"]["id"])
    assert room["occupied_cages"] == compute_occupied_cages([4], [25])
    assert room["occupied_cages"] == 9

    # A cohort needing ceil(6/5) = 2 cages would push occupancy to 11 > 10.
    resp = api_client.create_cohort(
        create_cohort_payload(colony["id"], count_male=3, count_female=3), _FM
    )
    validate_error(resp, ApiErrorId.ERR_CAGE_CAPACITY_EXCEEDED)

    # The rejected write changes nothing.
    assert read_room(site["room"]["id"])["occupied_cages"] == 9


def test_room_cage_aggregate_capacity_equality_passes():
    """PRD Section 3.4: "The two creation checks built on this occupancy both
    admit equality: founding a colony requires `occupied_cages` plus the
    incoming `breeding_pair_count` to be less than or equal to
    `cage_capacity`, and recording a cohort requires `occupied_cages` plus the
    ceiling of the new cohort's total headcount divided by 5 to be less than
    or equal to `cage_capacity`".

    Design: Difficulty/resource_temporal_overlap/room_cage_aggregate_capacity_boundary
    """
    site = setup_production_site(room_overrides={"cage_capacity": 10})
    colony = create_colony_in_room(site, breeding_pair_count=4)
    transition_colony(colony["id"], "EXPANDING")
    create_cohort_in_colony(colony["id"], count_male=13, count_female=12)
    assert read_room(site["room"]["id"])["occupied_cages"] == 9

    # Exactly one free cage: a 5-animal cohort takes ceil(5/5) = 1 cage and
    # lands the room at exactly capacity — equality passes.
    cohort = create_cohort_in_colony(colony["id"], count_male=3, count_female=2)
    assert cohort["initial_count_total"] == 5
    room = read_room(site["room"]["id"])
    assert room["occupied_cages"] == compute_occupied_cages([4], [25, 5])
    assert room["occupied_cages"] == 10


def test_cohort_partial_cull_recomputes_counts():
    """PRD Section 3.3: "A partial cull — cull counts smaller than the current
    counts — is permitted from the same three states provided `cull_male` does
    not exceed `available_male` and `cull_female` does not exceed
    `available_female`, because reserved animals can never be culled; it
    decrements `count_male` and `count_female` without changing `status`".
    PRD Section 3.3: "The `initial_count_total` field snapshots `count_male`
    plus `count_female` at creation and never changes afterward".
    PRD Section 3.4: "The accumulator is strictly monotonic: culls, allocation
    releases, shipment departures, and colony retirements never refund it".

    Design: Corner/state_machines/cohort_partial_cull_recomputes_counts
    """
    bundle = setup_colony_with_cohorts(
        breeding_pair_count=2,
        cohorts=[{"count_male": 10, "count_female": 10, "hold": True}],
        advance_to_production=False,
    )
    site = bundle["site"]
    cohort = bundle["cohorts"][0]

    updated = transition_cohort(
        cohort["id"], "CULLED", _VET, cull_male=4, cull_female=0
    )
    assert updated["count_male"] == 6
    assert updated["count_female"] == 10
    assert updated["status"] == "HOLD"  # partial cull changes no status
    assert updated["initial_count_total"] == 20

    room = read_room(site["room"]["id"])
    assert room["occupied_cages"] == compute_occupied_cages([2], [16])
    assert room["occupied_cages"] == 6

    protocol = find_protocol_in_facility(
        site["protocol"]["id"], site["facility"]["id"]
    )
    # 2 pairs * 2 animals + the immutable cohort snapshot 20 = 24; the cull
    # never refunds the monotonic accumulator.
    assert protocol["animals_used"] == 24


def test_allocation_release_twice_rejected():
    """PRD Section 3.7: "A `FacilityManager` may release any allocation in
    `RESERVED`, moving it to `RELEASED`".
    PRD Section 2.7: "And any transition or action requested against a
    resource whose current state does not declare that transition — including
    any further transition out of a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/allocation_release_twice_rejected
    """
    bundle = setup_sourcing_order(quantity_male=4, quantity_female=4)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]
    allocation, order = allocate_order_to_cohort(order, cohort, 2, 2)

    released, _order = release_allocation_and_refresh(allocation["id"], order["id"])
    assert released["status"] == "RELEASED"

    resp = api_client.release_allocation(allocation["id"], _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
