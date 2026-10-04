"""Allocations: the order-state and cohort-state gates, strain/weight/age
spec windows, the panel-overdue gate, reserve-release compensation, and
junction reachability from both parent sublists.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    allocate_order_to_cohort,
    api_client,
    assert_cohort_availability_invariants,
    compute_age_weeks,
    create_active_customer,
    create_allocation_payload,
    create_catalog_strain,
    create_colony_in_room,
    create_colony_payload,
    create_cohort_in_colony,
    create_order_submitted,
    hold_cohort,
    list_allocations_for_cohort,
    list_allocations_for_order,
    read_cohort,
    read_colony,
    read_order,
    release_allocation_and_refresh,
    setup_allocated_order,
    setup_colony_with_cohorts,
    setup_sourcing_order,
    source_order,
    transition_colony,
    validate_error,
    validate_paginated,
    validate_success,
)

_FM = TEST_USERS["facility_manager_headers"]


def test_allocation_rejected_while_order_submitted():
    """PRD Section 3.7: "the order itself must stand in `SOURCING` or
    `BACKORDERED`, else `ERR_ORDER_NOT_SOURCING` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/allocation_gated_by_order_and_cohort_states
    """
    bundle = setup_colony_with_cohorts(
        cohorts=[
            {"count_male": 10, "count_female": 10, "hold": True},
            {"count_male": 10, "count_female": 10},
        ]
    )
    site = bundle["site"]
    customer = create_active_customer()
    order = create_order_submitted(
        customer, site["strain"]["id"], quantity_male=10, quantity_female=10
    )
    assert order["status"] == "SUBMITTED"

    payload = create_allocation_payload(
        order["id"], bundle["cohorts"][0]["id"], order["version"],
        qty_male=5, qty_female=5,
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SOURCING)


def test_allocation_baseline_then_weaned_cohort_rejected():
    """PRD Section 3.7: "the cohort must stand in `HOLD` or
    `PARTIALLY_ALLOCATED` with sufficient free headcount — `available_male` at
    least `qty_male` and `available_female` at least `qty_female` — else
    `ERR_COHORT_NOT_ALLOCATABLE` (HTTP 409)" and "The allocation is born in
    `RESERVED`."

    Design: Difficulty/cross_entity_state_dependency/allocation_gated_by_order_and_cohort_states
    """
    bundle = setup_colony_with_cohorts(
        cohorts=[
            {"count_male": 10, "count_female": 10, "hold": True},
            {"count_male": 10, "count_female": 10},
        ]
    )
    site = bundle["site"]
    customer = create_active_customer()
    order = create_order_submitted(
        customer, site["strain"]["id"], quantity_male=10, quantity_female=10
    )
    order = source_order(order)

    allocation, order = allocate_order_to_cohort(order, bundle["cohorts"][0], 5, 5)
    assert allocation["status"] == "RESERVED"
    assert order["allocated_male"] == 5

    # Cohort B never left WEANED: not allocatable even though the order is
    # SOURCING with a fresh version.
    payload = create_allocation_payload(
        order["id"], bundle["cohorts"][1]["id"], order["version"],
        qty_male=5, qty_female=5,
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_COHORT_NOT_ALLOCATABLE)


def test_reserve_release_conserves_cohort_headcount():
    """PRD Section 3.7: "A `FacilityManager` may release any allocation in
    `RESERVED`, moving it to `RELEASED`; the cohort's reserved counts fall,
    and its status recomputes — `FULLY_ALLOCATED` relaxes to
    `PARTIALLY_ALLOCATED`, and a `PARTIALLY_ALLOCATED` cohort whose last
    reservation disappears returns to `HOLD`".

    Design: Difficulty/compensating_invariant/reserve_release_conserves_cohort_headcount
    """
    bundle = setup_sourcing_order(quantity_male=4, quantity_female=4)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]

    allocation, order = allocate_order_to_cohort(order, cohort, 4, 4)
    released, order = release_allocation_and_refresh(allocation["id"], order["id"])
    assert released["status"] == "RELEASED"

    cohort = read_cohort(cohort["id"])
    # Headcount conserved: reserve then release restores the exact tuple.
    assert cohort["count_male"] == 10
    assert cohort["count_female"] == 10
    assert cohort["reserved_male"] == 0
    assert cohort["reserved_female"] == 0
    assert cohort["status"] == "HOLD"
    assert_cohort_availability_invariants(cohort)


def test_release_drops_order_back_to_sourcing():
    """PRD Section 3.7: "the order's allocated totals fall, and an order that
    loses full coverage drops from `ALLOCATED` back to `SOURCING`."

    Design: Difficulty/compensating_invariant/reserve_release_conserves_cohort_headcount
    """
    bundle = setup_sourcing_order(quantity_male=4, quantity_female=4)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]

    allocation, order = allocate_order_to_cohort(order, cohort, 4, 4)
    assert order["status"] == "ALLOCATED"

    _released, order = release_allocation_and_refresh(allocation["id"], order["id"])
    assert order["status"] == "SOURCING"
    assert order["allocated_male"] == 0
    assert order["allocated_female"] == 0


def test_allocation_strain_mismatch_rejected():
    """PRD Section 3.7: "the cohort's colony must produce the very strain the
    order requests — a differing strain is `ERR_STRAIN_MISMATCH` (HTTP 422)".

    Design: Corner/validations/allocation_strain_mismatch_rejected
    """
    bundle = setup_colony_with_cohorts(
        cohorts=[{"count_male": 10, "count_female": 10, "hold": True}]
    )
    site = bundle["site"]
    cohort_a = bundle["cohorts"][0]  # colony of the site's strain A

    # A second strain with its own PRODUCTION colony so the order's sourcing
    # feasibility passes on its own merits.
    strain_b = create_catalog_strain(strain_code="BALBC", base_price_cents=1200)
    payload = create_colony_payload(
        site["room"]["id"], strain_b["id"], site["protocol"]["id"],
        breeding_pair_count=10,
    )
    colony_b = validate_success(api_client.create_colony(payload, _FM), 201)
    transition_colony(colony_b["id"], "EXPANDING")
    create_cohort_in_colony(colony_b["id"], count_male=5, count_female=5)
    transition_colony(colony_b["id"], "PRODUCTION")

    customer = create_active_customer()
    order = create_order_submitted(
        customer, strain_b["id"], quantity_male=5, quantity_female=5
    )
    order = source_order(order)

    payload = create_allocation_payload(
        order["id"], cohort_a["id"], order["version"], qty_male=5, qty_female=5
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_STRAIN_MISMATCH)


def test_allocation_weight_window_mismatch():
    """PRD Section 3.7: "for each sex allocated, the cohort's average weight
    (`avg_weight_g_male` for males, `avg_weight_g_female` for females) must
    lie within the order's `min_weight_g` to `max_weight_g` window, both
    bounds inclusive, else `ERR_WEIGHT_SPEC_MISMATCH` (HTTP 422)".

    Design: Corner/validations/allocation_weight_window_mismatch
    """
    bundle = setup_sourcing_order(
        quantity_male=5, quantity_female=5,
        cohorts=[{
            "count_male": 10, "count_female": 10,
            "avg_weight_g_male": 26.0, "avg_weight_g_female": 26.0,
            "hold": True,
        }],
    )
    order = bundle["order"]
    cohort = bundle["cohorts"][0]

    payload = create_allocation_payload(
        order["id"], cohort["id"], order["version"], qty_male=5, qty_female=5
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_WEIGHT_SPEC_MISMATCH)


def test_age_window_inclusive_boundary():
    """PRD Section 3.7: "the cohort's age, evaluated per Section 3.3 at the
    order's `required_delivery_date`, must lie within the order's
    `min_age_weeks` to `max_age_weeks` window, both bounds inclusive, else
    `ERR_AGE_SPEC_MISMATCH` (HTTP 422)."
    PRD Section 2.9: "Ages are integer weeks computed by flooring: elapsed
    days are floored to whole days first, then floored again to whole weeks."

    Design: Corner/calculations/age_window_inclusive_boundary
    """
    bundle = setup_sourcing_order(
        quantity_male=5, quantity_female=5,
        order_overrides={"required_delivery_date": "2026-10-13T00:00:00Z"},
        cohorts=[
            {"count_male": 10, "count_female": 10,
             "birth_date": "2026-08-26T00:00:00Z", "hold": True},
            {"count_male": 10, "count_female": 10,
             "birth_date": "2026-08-25T00:00:00Z", "hold": True},
        ],
    )
    order = bundle["order"]
    cohort_a, cohort_b = bundle["cohorts"]

    delivery = order["required_delivery_date"]
    # Cohort A: 48 days at delivery -> exactly 6 weeks == max_age_weeks.
    assert compute_age_weeks("2026-08-26T00:00:00Z", delivery) == 6
    # Cohort B: 49 days at delivery -> 7 weeks, above the window.
    assert compute_age_weeks("2026-08-25T00:00:00Z", delivery) == 7

    allocation, order = allocate_order_to_cohort(order, cohort_a, 2, 2)
    assert allocation["status"] == "RESERVED"

    payload = create_allocation_payload(
        order["id"], cohort_b["id"], order["version"], qty_male=3, qty_female=3
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_AGE_SPEC_MISMATCH)


def test_panel_overdue_blocks_allocation():
    """PRD Section 3.7: "a colony merely in `PANEL_DUE`, its surveillance
    overdue but no drift found, rejects with the distinct `ERR_PANEL_OVERDUE`
    (HTTP 409)".

    Design: Corner/validations/panel_overdue_blocks_allocation
    """
    bundle = setup_sourcing_order(quantity_male=5, quantity_female=5)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]

    # 12 weeks after the 2026-09-01 creation clock is 2026-11-24; the sweep at
    # 2026-11-26 flips the colony to PANEL_DUE.
    advance_clock("2026-11-26T00:00:00Z")
    assert read_colony(bundle["colony"]["id"])["genetic_status"] == "PANEL_DUE"

    payload = create_allocation_payload(
        order["id"], cohort["id"], order["version"], qty_male=5, qty_female=5
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_PANEL_OVERDUE)


def test_allocation_visible_from_order_and_cohort_sublists():
    """PRD Section 4: "List allocations serving this order." and "List
    allocations drawing from this cohort."
    PRD Section 3.7: "An allocation reserves specific animals from a specific
    cohort for a specific order."

    Design: Corner/endpoints/allocation_visible_from_order_and_cohort_sublists
    """
    bundle = setup_allocated_order(quantity_male=2, quantity_female=2)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]
    allocation = bundle["allocations"][0]

    order_side, meta_o = validate_paginated(
        api_client.list_order_allocations(order["id"], _FM, params={"limit": 100})
    )
    assert meta_o["total_count"] == 1
    assert [a["id"] for a in order_side] == [allocation["id"]]
    assert order_side[0]["qty_male"] == 2
    assert order_side[0]["status"] == "RESERVED"

    cohort_side, meta_c = validate_paginated(
        api_client.list_cohort_allocations(cohort["id"], _FM, params={"limit": 100})
    )
    assert meta_c["total_count"] == 1
    assert [a["id"] for a in cohort_side] == [allocation["id"]]
    assert cohort_side[0]["qty_male"] == 2
    assert cohort_side[0]["status"] == "RESERVED"
