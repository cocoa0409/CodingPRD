"""Turn operations: the move-out turn loop, window shape rules and maintenance capacity."""

from test_helpers import (
    ApiErrorId,
    activate_lease,
    assert_homesite,
    assert_instant_equals,
    assert_lease,
    assert_ratio_equals,
    assert_turn_allocation_sums,
    assert_turn_work_order,
    create_homesite,
    create_household,
    create_lease_payload,
    create_turn_work_order,
    create_turn_work_order_payload,
    draft_lease,
    give_notice,
    make_household_headers,
    read_community,
    read_homesite,
    read_lease,
    read_turn_work_order,
    setup_homesite_on_notice,
    setup_released_community,
    sign_lease,
    signature_payload,
    submit_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

SINGLE_UNIT_MIX = {"DETACHED": 1, "COTTAGE": 0, "TOWNHOME": 0}
TWO_UNIT_MIX = {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0}
FOUR_UNIT_MIX = {"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0}
CLOCK = "2026-08-01T00:00:00Z"


def test_a_completed_turn_returns_the_homesite_to_available_with_its_cycle_counted(
    api, property_manager_headers
):
    """A home on notice is taken through a 48-hour make-ready turn, and the completion returns
    it to AVAILABLE with the cycle counted and the ready instant stamped.

    `window_hours` is the length of the window expressed in whole hours.
    `labor_cost_cents` is `tech_count` multiplied by `window_hours` multiplied by the hourly rate for the scope: 6,500 cents per technician-hour for `MAKE_READY`, 8,000 for `DETACHED_YARD_RESTORE` and 11,000 for `MAJOR_REHAB`.
    The home moves `NOTICE_GIVEN → IN_TURN`; the `ENDING` lease on that home moves `ENDING → ENDED`, which is terminal; the community's `leased_unit_count` and `occupancy_ratio` are recomputed, since a home in turn no longer counts as occupied; and the community's `lifecycle_status` reverts `STABILIZED → LEASE_UP` when the recomputed `occupancy_ratio` falls below 0.7500, taking `facility_status` `CONVERSION_PENDING → ADVANCE_ELIGIBLE` with it.
    Then, and only when no other work order on that home still has `status` `SCHEDULED`, the home moves `IN_TURN → AVAILABLE`, its `turn_cycle_count` increases by 1, its `last_turn_ready_at` is stamped at the current logical clock, and the community's `available_unit_count` and `posture` are recomputed.

    Design: Difficulty/non_linear_state_machine/homesite_turn_loop_returns_to_available_and_relets_after_full_cycle
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=1,
        product_mix=SINGLE_UNIT_MIX,
        maintenance_tech_headcount=1,
    )
    homesite = scenario["homesites"][0]
    departing_lease = scenario["lease"]

    order = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                homesite["id"],
                window_start=CLOCK,
                window_end="2026-08-03T00:00:00Z",
                scope="MAKE_READY",
                tech_count=1,
                material_cost_cents=12_000,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert_turn_work_order(order)
    assert order["window_hours"] == 48
    assert order["labor_cost_cents"] == 312_000
    assert order["total_turn_cost_cents"] == 324_000
    assert order["tenant_recoverable_cents"] == 298_050
    assert order["community_opex_cents"] == 25_950
    assert order["capital_reserve_cents"] == 0
    assert order["status"] == "SCHEDULED"

    assert read_homesite(homesite["id"])["status"] == "IN_TURN"
    assert read_lease(departing_lease["id"])["lease_status"] == "ENDED"

    completed = validate_success(
        api.complete_turn_work_order(order["id"], {}, property_manager_headers), 201
    )
    assert completed["status"] == "COMPLETED"
    assert_instant_equals(completed["completed_at"], CLOCK, "completed_at")

    turned = read_homesite(homesite["id"])
    assert_homesite(turned)
    assert turned["status"] == "AVAILABLE"
    assert turned["turn_cycle_count"] == 1
    assert_instant_equals(turned["last_turn_ready_at"], CLOCK, "last_turn_ready_at")
    assert_instant_equals(turned["released_at"], CLOCK, "released_at")

    community = read_community(scenario["community"]["id"])
    assert community["available_unit_count"] == 1
    assert community["released_unit_count"] == 1
    assert community["leased_unit_count"] == 0
    assert_ratio_equals(community["occupancy_ratio"], 0.0, "occupancy_ratio")


def test_a_second_household_may_lease_the_same_homesite_once_the_turn_cycle_has_closed(
    api, property_manager_headers, leasing_agent_headers
):
    """After a full turn cycle the same home is let again to a different household, and the
    cycle counter records the single completed loop rather than being reset by the new lease.

    That closes the cyclic turn loop `AVAILABLE → LEASED → NOTICE_GIVEN → IN_TURN → AVAILABLE`, and the home is ready to be leased again.
    The home must have `status` `AVAILABLE` and its phase must be in `status` `SECTIONS_RELEASED` or `COMPLETE`, failing which the draft is `ERR_HOMESITE_NOT_LEASABLE` — which is what a caller sees when it tries to draft against a home that is still `PLANNED`, already `LEASED`, on `NOTICE_GIVEN`, `IN_TURN`, or parked `OFF_MARKET`.
    Hop one, caused by hop zero, moves the home `AVAILABLE → LEASED`.

    Design: Difficulty/non_linear_state_machine/homesite_turn_loop_returns_to_available_and_relets_after_full_cycle
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=1,
        product_mix=SINGLE_UNIT_MIX,
        maintenance_tech_headcount=1,
    )
    homesite = scenario["homesites"][0]
    first_lease = scenario["lease"]

    order = create_turn_work_order(
        homesite["id"],
        window_start=CLOCK,
        window_end="2026-08-03T00:00:00Z",
        scope="MAKE_READY",
        tech_count=1,
        material_cost_cents=12_000,
    )
    validate_success(
        api.complete_turn_work_order(order["id"], {}, property_manager_headers), 201
    )
    relisted = read_homesite(homesite["id"])
    assert relisted["status"] == "AVAILABLE"
    assert relisted["turn_cycle_count"] == 1
    assert read_lease(first_lease["id"])["lease_status"] == "ENDED"

    next_household = create_household(
        primary_applicant_name="Ivo Sandt",
        household_size=2,
        monthly_income_cents=1_200_000,
        credit_tier="B",
    )
    relet = validate_success(
        api.create_lease(
            create_lease_payload(
                homesite["id"],
                next_household["id"],
                term_months=12,
                start_date=CLOCK,
            ),
            leasing_agent_headers,
        ),
        201,
    )
    assert_lease(relet)
    assert relet["base_rent_cents"] == 285_000
    assert relet["gross_monthly_charge_cents"] == 298_050

    validate_success(api.submit_lease(relet["id"], {}, leasing_agent_headers), 201)
    signed = validate_success(
        api.sign_lease(
            relet["id"],
            signature_payload("Ivo Sandt"),
            make_household_headers(next_household["id"]),
        ),
        201,
    )
    assert signed["lease_status"] == "EXECUTED"

    released_again = read_homesite(homesite["id"])
    assert released_again["status"] == "LEASED"
    assert released_again["turn_cycle_count"] == 1

    community = read_community(scenario["community"]["id"])
    assert community["leased_unit_count"] == 1
    assert_ratio_equals(community["occupancy_ratio"], 1.0, "occupancy_ratio")


def test_a_turn_window_beginning_at_the_instant_the_previous_one_ends_is_accepted(
    api, property_manager_headers
):
    """A yard restoration scheduled to begin at exactly the instant the make-ready window ends is
    accepted, and its cost waterfall fills the tenant bucket, the operating cap and the reserve.

    First, two work orders on the same home may not have overlapping windows; because the windows are half-open, one ending at exactly the instant the next begins is allowed, while any genuine intersection is `ERR_TURN_WINDOW_OVERLAP`.
    Whatever remains after the tenant bucket flows to `community_opex_cents`, which takes whichever is smaller of that remainder and the community operating cap of 80,000 cents.
    A work order opened against a home that is already `IN_TURN` — a second scope on the same move-out — leaves the home and the outgoing lease where they are.

    Design: Difficulty/resource_temporal_overlap/turn_windows_adjacent_at_the_shared_boundary_are_accepted_but_overlap_is_rejected
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=2,
        product_mix=TWO_UNIT_MIX,
        maintenance_tech_headcount=2,
    )
    homesite = scenario["homesites"][0]
    departing_lease = scenario["lease"]

    make_ready = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                homesite["id"],
                window_start="2026-10-01T00:00:00Z",
                window_end="2026-10-03T00:00:00Z",
                scope="MAKE_READY",
                tech_count=1,
                material_cost_cents=12_000,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert make_ready["window_hours"] == 48
    assert make_ready["labor_cost_cents"] == 312_000
    assert make_ready["total_turn_cost_cents"] == 324_000
    assert make_ready["tenant_recoverable_cents"] == 298_050
    assert make_ready["community_opex_cents"] == 25_950
    assert make_ready["capital_reserve_cents"] == 0

    assert read_homesite(homesite["id"])["status"] == "IN_TURN"
    assert read_lease(departing_lease["id"])["lease_status"] == "ENDED"
    community = read_community(scenario["community"]["id"])
    assert community["leased_unit_count"] == 0
    assert_ratio_equals(community["occupancy_ratio"], 0.0, "occupancy_ratio")

    yard_restore = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                homesite["id"],
                window_start="2026-10-03T00:00:00Z",
                window_end="2026-10-04T00:00:00Z",
                scope="DETACHED_YARD_RESTORE",
                tech_count=2,
                material_cost_cents=45_000,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert_turn_work_order(yard_restore)
    assert yard_restore["window_hours"] == 24
    assert yard_restore["labor_cost_cents"] == 384_000
    assert yard_restore["total_turn_cost_cents"] == 429_000
    assert yard_restore["tenant_recoverable_cents"] == 298_050
    assert yard_restore["community_opex_cents"] == 80_000
    assert yard_restore["capital_reserve_cents"] == 50_950
    assert_turn_allocation_sums(yard_restore)

    assert read_homesite(homesite["id"])["status"] == "IN_TURN"
    assert read_lease(departing_lease["id"])["lease_status"] == "ENDED"


def test_a_turn_window_that_intersects_another_order_is_refused_as_an_overlap(
    api, property_manager_headers
):
    """A make-ready window starting twelve hours into the yard restoration intersects it and also
    starts inside the make-ready rework buffer; the overlap rule is the one that answers.

    Four temporal and capacity rules police the window, and they are evaluated in the order given here.
    First, two work orders on the same home may not have overlapping windows; because the windows are half-open, one ending at exactly the instant the next begins is allowed, while any genuine intersection is `ERR_TURN_WINDOW_OVERLAP`.
    Third, a rework buffer applies per scope: a new order of the same `scope` on the same home may not begin within two full days — 48 hours — of a prior order's `window_end` for that scope, and a closer start is `ERR_TURN_REWORK_BUFFER`.

    Design: Difficulty/resource_temporal_overlap/turn_windows_adjacent_at_the_shared_boundary_are_accepted_but_overlap_is_rejected
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=2,
        product_mix=TWO_UNIT_MIX,
        maintenance_tech_headcount=2,
    )
    homesite = scenario["homesites"][0]

    create_turn_work_order(
        homesite["id"],
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-03T00:00:00Z",
        scope="MAKE_READY",
        tech_count=1,
        material_cost_cents=12_000,
    )
    create_turn_work_order(
        homesite["id"],
        window_start="2026-10-03T00:00:00Z",
        window_end="2026-10-04T00:00:00Z",
        scope="DETACHED_YARD_RESTORE",
        tech_count=2,
        material_cost_cents=45_000,
    )

    response = api.create_turn_work_order(
        create_turn_work_order_payload(
            homesite["id"],
            window_start="2026-10-03T12:00:00Z",
            window_end="2026-10-04T12:00:00Z",
            scope="MAKE_READY",
            tech_count=1,
            material_cost_cents=0,
        ),
        property_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_TURN_WINDOW_OVERLAP.value)

    orders, meta = validate_paginated(
        api.list_turn_work_orders(
            property_manager_headers, {"homesite_id": homesite["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert all(order["status"] == "SCHEDULED" for order in orders)


def test_the_same_scope_rework_buffer_is_inclusive_at_exactly_forty_eight_hours(
    api, property_manager_headers
):
    """A second make-ready starting 24 hours after the first one's window end is refused on the
    rework buffer even though it overlaps nothing, while one starting exactly 48 hours after is taken.

    Third, a rework buffer applies per scope: a new order of the same `scope` on the same home may not begin within two full days — 48 hours — of a prior order's `window_end` for that scope, and a closer start is `ERR_TURN_REWORK_BUFFER`.
    `tenant_recoverable_cents` is whichever is smaller of `total_turn_cost_cents` and that cap.
    The order itself is stored with `status` `SCHEDULED` and `completed_at` null.

    Design: Difficulty/resource_temporal_overlap/turn_windows_adjacent_at_the_shared_boundary_are_accepted_but_overlap_is_rejected
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=2,
        product_mix=TWO_UNIT_MIX,
        maintenance_tech_headcount=2,
    )
    homesite = scenario["homesites"][0]

    create_turn_work_order(
        homesite["id"],
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-03T00:00:00Z",
        scope="MAKE_READY",
        tech_count=1,
        material_cost_cents=12_000,
    )
    create_turn_work_order(
        homesite["id"],
        window_start="2026-10-03T00:00:00Z",
        window_end="2026-10-04T00:00:00Z",
        scope="DETACHED_YARD_RESTORE",
        tech_count=2,
        material_cost_cents=45_000,
    )

    too_soon = api.create_turn_work_order(
        create_turn_work_order_payload(
            homesite["id"],
            window_start="2026-10-04T00:00:00Z",
            window_end="2026-10-05T00:00:00Z",
            scope="MAKE_READY",
            tech_count=1,
            material_cost_cents=0,
        ),
        property_manager_headers,
    )
    validate_error(too_soon, ApiErrorId.ERR_TURN_REWORK_BUFFER.value)

    at_the_buffer = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                homesite["id"],
                window_start="2026-10-05T00:00:00Z",
                window_end="2026-10-06T00:00:00Z",
                scope="MAKE_READY",
                tech_count=1,
                material_cost_cents=0,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert_turn_work_order(at_the_buffer)
    assert at_the_buffer["window_hours"] == 24
    assert at_the_buffer["labor_cost_cents"] == 156_000
    assert at_the_buffer["total_turn_cost_cents"] == 156_000
    assert at_the_buffer["tenant_recoverable_cents"] == 156_000
    assert at_the_buffer["community_opex_cents"] == 0
    assert at_the_buffer["capital_reserve_cents"] == 0
    assert at_the_buffer["status"] == "SCHEDULED"
    assert at_the_buffer["completed_at"] is None

    orders, meta = validate_paginated(
        api.list_turn_work_orders(
            property_manager_headers, {"homesite_id": homesite["id"]}
        )
    )
    assert meta["total_count"] == 3
    assert all(order["status"] == "SCHEDULED" for order in orders)


def test_completing_the_only_scheduled_order_closes_the_inventory_loop(
    api, property_manager_headers
):
    """Opening the work order ends the tenancy and takes the home to IN_TURN; completing it is what
    returns the home to AVAILABLE, leaving the release stamp and the released counter alone.

    On completion `status` becomes `COMPLETED` and `completed_at` is stamped at the current logical clock, and `labor_cost_cents`, `total_turn_cost_cents` and the three allocation buckets are recomputed against the recoverable cap in force at completion — which can differ from the cap at scheduling time if the departing lease reached `ENDED` in between.
    Then, and only when no other work order on that home still has `status` `SCHEDULED`, the home moves `IN_TURN → AVAILABLE`, its `turn_cycle_count` increases by 1, its `last_turn_ready_at` is stamped at the current logical clock, and the community's `available_unit_count` and `posture` are recomputed.
    In particular, a homesite's `released_at` is never rewritten, so a community's `released_unit_count` is unchanged by a halt, by a resume, by a cancellation or by a turn — once a home has been released to leasing it stays counted as released for the rest of its life.

    Design: Corner/state_machines/turn_completion_closes_the_homesite_loop_back_to_available
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        maintenance_tech_headcount=2,
    )
    homesite = scenario["homesites"][0]
    departing_lease = scenario["lease"]

    order = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                homesite["id"],
                window_start=CLOCK,
                window_end="2026-08-03T00:00:00Z",
                scope="MAKE_READY",
                tech_count=1,
                material_cost_cents=12_000,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert order["status"] == "SCHEDULED"
    assert order["window_hours"] == 48
    assert order["labor_cost_cents"] == 312_000
    assert order["total_turn_cost_cents"] == 324_000

    assert read_homesite(homesite["id"])["status"] == "IN_TURN"
    assert read_lease(departing_lease["id"])["lease_status"] == "ENDED"
    mid_turn_community = read_community(scenario["community"]["id"])
    assert mid_turn_community["leased_unit_count"] == 0
    assert_ratio_equals(mid_turn_community["occupancy_ratio"], 0.0, "occupancy_ratio")

    completed = validate_success(
        api.complete_turn_work_order(order["id"], {}, property_manager_headers), 201
    )
    assert_turn_work_order(completed)
    assert completed["status"] == "COMPLETED"
    assert_instant_equals(completed["completed_at"], CLOCK, "completed_at")
    assert completed["tenant_recoverable_cents"] == 298_050
    assert completed["community_opex_cents"] == 25_950
    assert completed["capital_reserve_cents"] == 0

    turned = read_homesite(homesite["id"])
    assert turned["status"] == "AVAILABLE"
    assert turned["turn_cycle_count"] == 1
    assert_instant_equals(turned["last_turn_ready_at"], CLOCK, "last_turn_ready_at")
    assert_instant_equals(turned["released_at"], CLOCK, "released_at")

    community = read_community(scenario["community"]["id"])
    assert community["available_unit_count"] == 1
    assert community["released_unit_count"] == 1
    assert community["posture"] == "OPEN"


def test_a_major_rehab_fills_all_three_buckets_and_overflows_into_the_capital_reserve(
    api, property_manager_headers
):
    """A five-day major rehab with two technicians costs far more than either of the first two
    buckets can hold, so the tenant cap and the operating cap fill and the reserve absorbs the rest.

    `total_turn_cost_cents` is `labor_cost_cents` plus `material_cost_cents`.
    That total is then allocated across three buckets in a strict waterfall, each filling completely before the next receives anything.
    The recoverable cap is the `gross_monthly_charge_cents` of the most recent departing lease on that same home — the lease whose `lease_status` is `ENDING` or `ENDED`, ranked by `executed_at` descending and then by `created_at` descending — and the cap is 0 when no such lease exists.
    `capital_reserve_cents` absorbs everything still left.
    The three buckets always sum to exactly `total_turn_cost_cents`, and because every factor is an integer no rounding is required anywhere in the allocation.

    Design: Corner/calculations/turn_cost_waterfall_overflows_into_the_capital_reserve_after_the_opex_cap
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        maintenance_tech_headcount=2,
        homesite_specs=[{"product_type": "DETACHED", "bedrooms": 5, "square_feet": 2600}],
    )
    homesite = scenario["homesites"][0]
    assert scenario["lease"]["gross_monthly_charge_cents"] == 298_050

    order = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                homesite["id"],
                window_start=CLOCK,
                window_end="2026-08-06T00:00:00Z",
                scope="MAJOR_REHAB",
                tech_count=2,
                material_cost_cents=250_000,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert_turn_work_order(order)
    assert order["window_hours"] == 120
    assert order["labor_cost_cents"] == 2_640_000
    assert order["total_turn_cost_cents"] == 2_890_000
    assert order["tenant_recoverable_cents"] == 298_050
    assert order["community_opex_cents"] == 80_000
    assert order["capital_reserve_cents"] == 2_511_950
    assert (
        order["tenant_recoverable_cents"]
        + order["community_opex_cents"]
        + order["capital_reserve_cents"]
    ) == 2_890_000
    assert_turn_allocation_sums(order)


def test_turn_windows_that_break_the_shape_rules_are_refused(api, property_manager_headers):
    """A half-hour span, a span above the ten-day ceiling and a window starting behind the logical
    clock are each refused, and none of them puts the home into turn.

    Second, the window must be well formed: `window_start` strictly before `window_end`, a span that is a positive whole number of hours and no longer than ten days — 240 hours — and a `window_start` at or after the current logical clock; any of those failures is `ERR_INVALID_TURN_WINDOW`.

    Design: Corner/validations/turn_windows_that_break_the_shape_rules_are_rejected
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 4},
    )
    homesite = scenario["homesites"][0]

    sub_hour = api.create_turn_work_order(
        create_turn_work_order_payload(
            homesite["id"],
            window_start=CLOCK,
            window_end="2026-08-01T00:30:00Z",
            scope="MAKE_READY",
            tech_count=1,
            material_cost_cents=40_000,
        ),
        property_manager_headers,
    )
    validate_error(sub_hour, ApiErrorId.ERR_INVALID_TURN_WINDOW.value)

    over_ceiling = api.create_turn_work_order(
        create_turn_work_order_payload(
            homesite["id"],
            window_start=CLOCK,
            window_end="2026-08-12T00:00:00Z",
            scope="MAKE_READY",
            tech_count=1,
            material_cost_cents=40_000,
        ),
        property_manager_headers,
    )
    validate_error(over_ceiling, ApiErrorId.ERR_INVALID_TURN_WINDOW.value)

    in_the_past = api.create_turn_work_order(
        create_turn_work_order_payload(
            homesite["id"],
            window_start="2026-07-31T00:00:00Z",
            window_end=CLOCK,
            scope="MAKE_READY",
            tech_count=1,
            material_cost_cents=40_000,
        ),
        property_manager_headers,
    )
    validate_error(in_the_past, ApiErrorId.ERR_INVALID_TURN_WINDOW.value)

    assert read_homesite(homesite["id"])["status"] == "NOTICE_GIVEN"
    _, meta = validate_paginated(
        api.list_turn_work_orders(
            property_manager_headers, {"homesite_id": homesite["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_seventy_two_hour_window_starting_at_the_logical_clock_is_accepted(
    api, property_manager_headers
):
    """A three-day window whose start sits exactly on the logical clock satisfies the near edge of
    the shape rule and carries the departure cascade with it.

    Second, the window must be well formed: `window_start` strictly before `window_end`, a span that is a positive whole number of hours and no longer than ten days — 240 hours — and a `window_start` at or after the current logical clock; any of those failures is `ERR_INVALID_TURN_WINDOW`.
    `window_hours` is the length of the window expressed in whole hours.
    The home moves `NOTICE_GIVEN → IN_TURN`; the `ENDING` lease on that home moves `ENDING → ENDED`, which is terminal; the community's `leased_unit_count` and `occupancy_ratio` are recomputed, since a home in turn no longer counts as occupied; and the community's `lifecycle_status` reverts `STABILIZED → LEASE_UP` when the recomputed `occupancy_ratio` falls below 0.7500, taking `facility_status` `CONVERSION_PENDING → ADVANCE_ELIGIBLE` with it.

    Design: Corner/validations/turn_windows_that_break_the_shape_rules_are_rejected
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        maintenance_tech_headcount=2,
        phase_overrides={"planned_unit_count": 4},
    )
    homesite = scenario["homesites"][0]
    departing_lease = scenario["lease"]

    order = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                homesite["id"],
                window_start=CLOCK,
                window_end="2026-08-04T00:00:00Z",
                scope="MAKE_READY",
                tech_count=1,
                material_cost_cents=40_000,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert_turn_work_order(order)
    assert order["window_hours"] == 72
    assert order["status"] == "SCHEDULED"

    assert read_homesite(homesite["id"])["status"] == "IN_TURN"
    assert read_lease(departing_lease["id"])["lease_status"] == "ENDED"


def test_turn_capacity_is_an_hour_by_hour_cap_across_the_whole_community(
    api, property_manager_headers
):
    """Two technicians already booked on one home consume the community's entire staffing, so a
    one-technician order on a different home whose window merely overlaps is refused.

    Fourth, the community's maintenance staffing is a hard aggregate cap: summed across the scheduled work orders of the community, the technicians required at any hour covered by the requested window must not exceed the community's `maintenance_tech_headcount`, and an over-subscription is `ERR_TURN_CAPACITY_EXCEEDED`.
    `maintenance_tech_headcount` is the number of maintenance technicians staffed for turns; it is optional, defaults to 2 when omitted, and must be at least 1.

    Design: Corner/validations/turn_capacity_across_the_community_is_capped_by_the_tech_headcount
    """
    scenario = setup_released_community(
        homesite_count=2,
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        maintenance_tech_headcount=2,
    )
    first_home, second_home = scenario["homesites"]
    noticed_leases = []
    for home in (first_home, second_home):
        household = create_household()
        lease = draft_lease(home["id"], household["id"])
        submit_lease(lease["id"])
        sign_lease(lease["id"], household["id"], household["primary_applicant_name"])
        activate_lease(lease["id"])
        give_notice(lease["id"], household["id"])
        noticed_leases.append(read_lease(lease["id"]))

    booked = create_turn_work_order(
        first_home["id"],
        window_start=CLOCK,
        window_end="2026-08-03T00:00:00Z",
        scope="MAKE_READY",
        tech_count=2,
        material_cost_cents=50_000,
    )
    assert booked["tech_count"] == 2

    oversubscribed = api.create_turn_work_order(
        create_turn_work_order_payload(
            second_home["id"],
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-04T00:00:00Z",
            scope="MAKE_READY",
            tech_count=1,
            material_cost_cents=50_000,
        ),
        property_manager_headers,
    )
    validate_error(oversubscribed, ApiErrorId.ERR_TURN_CAPACITY_EXCEEDED.value)

    assert read_homesite(second_home["id"])["status"] == "NOTICE_GIVEN"
    assert read_lease(noticed_leases[1]["id"])["lease_status"] == "ENDING"
    assert read_turn_work_order(booked["id"])["status"] == "SCHEDULED"


def test_a_turn_order_starting_when_the_technicians_free_up_is_accepted(
    api, property_manager_headers
):
    """The same one-technician order shifted to begin exactly when the two-technician window ends
    needs no overlapping labour, so it is accepted and carries its own departure cascade.

    Fourth, the community's maintenance staffing is a hard aggregate cap: summed across the scheduled work orders of the community, the technicians required at any hour covered by the requested window must not exceed the community's `maintenance_tech_headcount`, and an over-subscription is `ERR_TURN_CAPACITY_EXCEEDED`.
    The order occupies the half-open interval from `window_start` inclusive to `window_end` exclusive, declares a `scope` of `MAKE_READY`, `DETACHED_YARD_RESTORE` or `MAJOR_REHAB`, assigns a `tech_count` of between 1 and 3 technicians for the whole window, and estimates `material_cost_cents`, which may not be negative.

    Design: Corner/validations/turn_capacity_across_the_community_is_capped_by_the_tech_headcount
    """
    scenario = setup_released_community(
        homesite_count=2,
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        maintenance_tech_headcount=2,
    )
    first_home, second_home = scenario["homesites"]
    noticed_leases = []
    for home in (first_home, second_home):
        household = create_household()
        lease = draft_lease(home["id"], household["id"])
        submit_lease(lease["id"])
        sign_lease(lease["id"], household["id"], household["primary_applicant_name"])
        activate_lease(lease["id"])
        give_notice(lease["id"], household["id"])
        noticed_leases.append(read_lease(lease["id"]))

    booked = create_turn_work_order(
        first_home["id"],
        window_start=CLOCK,
        window_end="2026-08-03T00:00:00Z",
        scope="MAKE_READY",
        tech_count=2,
        material_cost_cents=50_000,
    )

    adjacent = validate_success(
        api.create_turn_work_order(
            create_turn_work_order_payload(
                second_home["id"],
                window_start="2026-08-03T00:00:00Z",
                window_end="2026-08-05T00:00:00Z",
                scope="MAKE_READY",
                tech_count=1,
                material_cost_cents=50_000,
            ),
            property_manager_headers,
        ),
        201,
    )
    assert_turn_work_order(adjacent)
    assert adjacent["window_hours"] == 48
    assert adjacent["status"] == "SCHEDULED"

    assert read_homesite(second_home["id"])["status"] == "IN_TURN"
    assert read_lease(noticed_leases[1]["id"])["lease_status"] == "ENDED"
    assert read_turn_work_order(booked["id"])["status"] == "SCHEDULED"

    _, meta = validate_paginated(
        api.list_turn_work_orders(property_manager_headers, {"status": "SCHEDULED"})
    )
    assert meta["total_count"] == 2


def test_turn_work_on_a_home_with_no_move_out_is_refused(api, property_manager_headers):
    """Make-ready labour may not be booked against inventory nobody is vacating: an available home
    that was never leased and a home still under construction are both refused.

    Opening a turn work order is what actually ends the tenancy.
    A `PropertyManager` schedules turn work against a `homesite_id` whose `status` is `NOTICE_GIVEN` or already `IN_TURN`; opening one against a home that is `AVAILABLE`, `PLANNED`, `LEASED` or `OFF_MARKET` is `ERR_HOMESITE_NOT_IN_TURN`.

    Design: Corner/validations/a_turn_order_on_a_homesite_that_is_not_in_turn_is_rejected
    """
    scenario = setup_released_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        phase_overrides={"planned_unit_count": 4},
    )
    available_home = scenario["homesites"][0]
    assert available_home["status"] == "AVAILABLE"

    planned_home = create_homesite(
        scenario["phase"]["id"],
        lot_number="P2",
        product_type="DETACHED",
        bedrooms=3,
        square_feet=1900,
    )
    assert planned_home["status"] == "PLANNED"

    for home in (available_home, planned_home):
        response = api.create_turn_work_order(
            create_turn_work_order_payload(
                home["id"],
                window_start=CLOCK,
                window_end="2026-08-03T00:00:00Z",
                scope="MAKE_READY",
                tech_count=1,
                material_cost_cents=30_000,
            ),
            property_manager_headers,
        )
        validate_error(response, ApiErrorId.ERR_HOMESITE_NOT_IN_TURN.value)

    untouched_available = read_homesite(available_home["id"])
    assert untouched_available["status"] == "AVAILABLE"
    assert untouched_available["turn_cycle_count"] == 0
    assert read_homesite(planned_home["id"])["status"] == "PLANNED"

    _, meta = validate_paginated(api.list_turn_work_orders(property_manager_headers))
    assert meta["total_count"] == 0


def test_completing_a_turn_work_order_a_second_time_is_refused(api, property_manager_headers):
    """A completed work order is terminal, so a repeat completion is refused rather than treated as
    idempotent, and the closing side effects of the turn do not run a second time.

    A `PropertyManager` completes a work order whose `status` is `SCHEDULED` once the logical clock has reached its `window_start`; completing an order that is already `COMPLETED` is `ERR_INVALID_TURN_STATE`.
    Then, and only when no other work order on that home still has `status` `SCHEDULED`, the home moves `IN_TURN → AVAILABLE`, its `turn_cycle_count` increases by 1, its `last_turn_ready_at` is stamped at the current logical clock, and the community's `available_unit_count` and `posture` are recomputed.

    Design: Corner/errors/completing_a_turn_work_order_twice_is_rejected
    """
    scenario = setup_homesite_on_notice(
        total_planned_units=4,
        product_mix=FOUR_UNIT_MIX,
        maintenance_tech_headcount=2,
    )
    homesite = scenario["homesites"][0]
    departing_lease = scenario["lease"]

    order = create_turn_work_order(
        homesite["id"],
        window_start=CLOCK,
        window_end="2026-08-03T00:00:00Z",
        scope="MAKE_READY",
        tech_count=1,
        material_cost_cents=60_000,
    )
    first_completion = validate_success(
        api.complete_turn_work_order(order["id"], {}, property_manager_headers), 201
    )
    assert first_completion["status"] == "COMPLETED"
    assert_instant_equals(first_completion["completed_at"], CLOCK, "completed_at")

    after_first = read_homesite(homesite["id"])
    assert after_first["status"] == "AVAILABLE"
    assert after_first["turn_cycle_count"] == 1
    assert_instant_equals(after_first["last_turn_ready_at"], CLOCK, "last_turn_ready_at")

    second_completion = api.complete_turn_work_order(
        order["id"], {}, property_manager_headers
    )
    validate_error(second_completion, ApiErrorId.ERR_INVALID_TURN_STATE.value)

    reread_order = read_turn_work_order(order["id"])
    assert reread_order["status"] == "COMPLETED"
    for field in (
        "labor_cost_cents",
        "total_turn_cost_cents",
        "tenant_recoverable_cents",
        "community_opex_cents",
        "capital_reserve_cents",
    ):
        assert reread_order[field] == first_completion[field], field
    assert_instant_equals(
        reread_order["completed_at"], first_completion["completed_at"], "completed_at"
    )

    after_second = read_homesite(homesite["id"])
    assert after_second["status"] == "AVAILABLE"
    assert after_second["turn_cycle_count"] == 1
    assert_instant_equals(
        after_second["last_turn_ready_at"],
        after_first["last_turn_ready_at"],
        "last_turn_ready_at",
    )

    assert read_lease(departing_lease["id"])["lease_status"] == "ENDED"
    assert read_community(scenario["community"]["id"])["leased_unit_count"] == 0
