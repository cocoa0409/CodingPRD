"""Allocation cycles: week-window exclusion, posture-pinned capacity, the
waterfall split, waitlist ranking, and cycle state guards (PRD §3.4, §3.5)."""
from test_helpers import (
    WEEK_1_START,
    WEEK_2_START,
    ApiErrorId,
    assert_cycle_capacity_conserved,
    create_active_licensee,
    create_cycle,
    create_factory,
    create_licensee_order,
    create_retail_account,
    create_retail_order,
    get_cycle,
    get_licensee,
    get_order,
    get_retail_account,
    play_scored_cycle,
    run_cycle,
    setup_catalog,
    setup_open_cycle,
    submit_order,
    transition_factory,
    validate_error,
    validate_success,
)


class TestCycleWeekExclusion:
    """Difficulty instance: cycle_week_strict_exclusion_with_adjacency_allowed.
    C1 occupies the half-open week [2026-09-07, 2026-09-14)."""

    def test_overlapping_week_rejected(self, api, production_planner_headers):
        """PRD §3.4: "A cycle occupies a half-open week: it covers the instant of
        `week_start` and everything up to, but not including, the same instant seven
        days later. Week windows of the same factory must not overlap — a new cycle
        whose week intersects an existing cycle of that factory is rejected with
        `ERR_CYCLE_WEEK_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/cycle_week_strict_exclusion_with_adjacency_allowed
        """
        factory = create_factory()
        create_cycle(factory["id"], week_start=WEEK_1_START)
        resp = api.create_allocation_cycle(
            {"factory_id": factory["id"], "week_start": "2026-09-10T00:00:00Z"},
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_WEEK_OVERLAP.value)

    def test_exactly_adjacent_week_allowed(self, api, production_planner_headers):
        """PRD §3.4: "but exact adjacency is allowed: a cycle whose `week_start` equals
        another cycle's `week_start` plus seven days abuts it without overlapping."
        PRD §3.4: "At creation the cycle pins its `capacity_units` from the factory's
        posture at that moment: the factory's full `weekly_capacity_units` while the
        factory is `ACTIVE`"

        Design: Difficulty/resource_temporal_overlap/cycle_week_strict_exclusion_with_adjacency_allowed
        """
        factory = create_factory()
        create_cycle(factory["id"], week_start=WEEK_1_START)
        resp = api.create_allocation_cycle(
            {"factory_id": factory["id"], "week_start": WEEK_2_START},
            production_planner_headers,
        )
        cycle = validate_success(resp, 201)
        assert cycle["capacity_units"] == 100


class TestRunAllocation:
    def test_run_allocation_converts_and_locks_final_prices(self, api, production_planner_headers):
        """PRD §3.4: "Running the allocation moves the cycle `OPEN → ALLOCATED`, stamps
        `run_at`, and executes the capacity waterfall over the cycle's orders whose
        allocation state is `RESERVED` or `WAITLISTED`."
        PRD §3.4: "Each order that lands `ALLOCATED` locks its `final_total_cents` as
        its quantity re-priced under the product line's lifecycle at run time (§3.5)"

        Design: Corner/endpoints/run_allocation_converts_and_locks_final_prices
        """
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=3
        )
        submit_order(order)
        cycle = run_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "ALLOCATED"
        assert cycle["run_at"] is not None
        fetched = get_order(order["id"])
        assert fetched["allocation_state"] == "ALLOCATED"
        # Line still ACTIVE, so final == provisional: 62930 * 3.
        assert fetched["final_total_cents"] == 188790


class TestWaterfallSplit:
    def test_waterfall_demotes_early_wholesale_when_licensee_cap_binds(self, api, production_planner_headers):
        """PRD §3.4: "The wholesale floor is K times 0.25, rounded down to a whole unit
        — one quarter of the week is reserved for wholesale demand — and the licensee
        cap is K minus that floor."
        PRD §3.4: "Every selected order lands in `ALLOCATED`; every candidate that does
        not fit lands in `WAITLISTED` — including orders that had been `RESERVED`, so
        demotion at run time is possible, releasing its held capacity back into the
        cycle."
        PRD §3.4: "The wholesale pass then walks the retail-buyer orders in rank order
        with an allowance equal to K minus the total quantity selected in the licensee
        pass"

        Design: Corner/calculations/waterfall_demotes_early_wholesale_when_licensee_cap_binds
        """
        ctx = setup_catalog(
            factory_over={
                "code": "FAC-W1",
                "region": "OVERSEAS",
                "component_lines": ["FRAMES"],
                "weekly_capacity_units": 20,
            }
        )
        ctx["cycle"] = create_cycle(ctx["factory"]["id"], week_start=WEEK_1_START)
        account = create_retail_account(credit_limit_cents=5_000_000)
        # WA qty 18 submits first -> RESERVED (18 <= 20).
        wa = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=18)
        wa = submit_order(wa)
        assert wa["allocation_state"] == "RESERVED"
        # LA qty 10 submits second -> WAITLISTED (18 + 10 > 20).
        la = create_licensee_order(ctx["licensee"], ctx["cycle"], ctx["line"], quantity=10)
        la = submit_order(la)
        assert la["allocation_state"] == "WAITLISTED"

        run_cycle(ctx["cycle"]["id"])

        # licensee_cap == 20 - floor(20*0.25) == 15 covers LA's 10.
        la_post = get_order(la["id"])
        assert la_post["allocation_state"] == "ALLOCATED"
        assert la_post["final_total_cents"] == 629300  # 62930 * 10
        # wholesale_cap == 20 - 10 == 10 < 18: the early wholesale order demotes.
        wa_post = get_order(wa["id"])
        assert wa_post["allocation_state"] == "WAITLISTED", (
            f"early wholesale order must demote to WAITLISTED, got {wa_post['allocation_state']}"
        )
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["licensee_reserved_units"] == 10
        assert cycle["wholesale_reserved_units"] == 0
        assert cycle["available_units"] == 10
        assert_cycle_capacity_conserved(cycle)
        # WAITLISTED holds no credit exposure (PRD §3.3).
        assert get_retail_account(account["id"])["credit_used_cents"] == 0


class TestWaitlistRanking:
    def test_waitlist_ranking_preferred_tier_beats_earlier_creation(self, api, production_planner_headers):
        """PRD §3.4: "A licensee buyer earns tier 1 when its `seasoned_score` is
        non-null and at least 75.00; any licensee without such a qualifying score is
        tier 2."
        PRD §3.4: "Orders sort by standing tier ascending, then by `created_at`
        ascending; order ids are never used for ranking, and chronological order is the
        final tie-break."

        Design: Corner/calculations/waitlist_ranking_preferred_tier_beats_earlier_creation
        """
        factory = create_factory(
            code="FAC-R1",
            region="DOMESTIC",
            component_lines=["UPHOLSTERY"],
            weekly_capacity_units=10,
        )
        ctx = setup_catalog()
        ctx["factory"] = factory
        star = ctx["licensee"]  # will earn a seasoned score in cycle A
        new_town = create_active_licensee(business_name="New Town Furniture")
        # Cycle A: STAR delivers a qty-2 order; default audit 80, no claims.
        # I = 0.5*100 + 0.3*80 + 0.2*100 = 94.00 -> PREFERRED tier (>= 75.00).
        play_scored_cycle(ctx, WEEK_1_START, [2], deliver_count=1)
        assert get_licensee(star["id"])["seasoned_score"] == 94.00

        # Cycle B (cap 10): NEW's qty-6 order is created FIRST (RESERVED),
        # STAR's qty-6 second (WAITLISTED at submit, 6 + 6 > 10).
        cycle_b = create_cycle(factory["id"], week_start=WEEK_2_START)
        o_new = create_licensee_order(new_town, cycle_b, ctx["line"], quantity=6)
        o_new = submit_order(o_new)
        assert o_new["allocation_state"] == "RESERVED"
        o_star = create_licensee_order(star, cycle_b, ctx["line"], quantity=6)
        o_star = submit_order(o_star)
        assert o_star["allocation_state"] == "WAITLISTED"

        run_cycle(cycle_b["id"])

        # licensee_cap == 10 - floor(10*0.25) == 8 fits only one 6-unit order, and the
        # PREFERRED tier outranks earlier creation.
        assert get_order(o_star["id"])["allocation_state"] == "ALLOCATED"
        assert get_order(o_new["id"])["allocation_state"] == "WAITLISTED"


class TestCycleStateGuards:
    def test_submit_against_allocated_cycle_returns_409(self, api, platform_admin_headers):
        """PRD §3.5: "The order names an `allocation_cycle_id` whose cycle must be
        `OPEN` — at create and again at submit — otherwise `ERR_CYCLE_NOT_OPEN`"

        Design: Corner/errors/submit_against_allocated_cycle_returns_409
        """
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=3
        )
        run_cycle(ctx["cycle"]["id"])  # cycle leaves OPEN before the submit
        from test_helpers import make_licensee_manager_headers

        resp = api.transition_order(
            order["id"],
            {"action": "SUBMIT"},
            make_licensee_manager_headers(ctx["licensee"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN.value)
        assert get_order(order["id"])["allocation_state"] == "UNALLOCATED"

    def test_cycle_close_from_open_returns_409(self, api, production_planner_headers):
        """PRD §3.4: "Closing the cycle (`ALLOCATED → CLOSED`, stamped `closed_at`)
        finishes the week."
        PRD §2.8: "Transition validity (`ERR_INVALID_TRANSITION`, HTTP 409)"
        PRD §3.4: "`run_at` and `closed_at` are null until the run and the close
        respectively."

        Design: Corner/state_machines/cycle_close_from_open_returns_409
        """
        factory = create_factory()
        cycle = create_cycle(factory["id"], week_start=WEEK_1_START)
        resp = api.close_cycle(cycle["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)
        fetched = get_cycle(cycle["id"])
        assert fetched["status"] == "OPEN"
        assert fetched["closed_at"] is None


class TestCycleCreation:
    def test_week_start_not_midnight_returns_400(self, api, production_planner_headers):
        """PRD §3.4: "The `week_start` must be midnight-aligned — time component exactly
        00:00:00Z — otherwise `ERR_VALIDATION`"

        Design: Corner/endpoints/week_start_not_midnight_returns_400
        """
        factory = create_factory()
        resp = api.create_allocation_cycle(
            {"factory_id": factory["id"], "week_start": "2026-09-07T06:00:00Z"},
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_constrained_factory_halves_cycle_capacity(self, api, production_planner_headers):
        """PRD §3.4: "At creation the cycle pins its `capacity_units` from the factory's
        posture at that moment: the factory's full `weekly_capacity_units` while the
        factory is `ACTIVE`, or half of that figure rounded down to a whole unit while
        the factory is `CONSTRAINED`. Later posture changes do not retroactively alter
        an existing cycle's pinned capacity."

        Design: Corner/errors/constrained_factory_halves_cycle_capacity
        """
        factory = create_factory()  # weekly_capacity_units 100
        transition_factory(factory["id"], "CONSTRAINED")
        cycle = create_cycle(factory["id"], week_start=WEEK_1_START)
        assert cycle["capacity_units"] == 50, (
            f"CONSTRAINED factory must pin half capacity, got {cycle['capacity_units']}"
        )
        transition_factory(factory["id"], "ACTIVE")
        assert get_cycle(cycle["id"])["capacity_units"] == 50, (
            "pinned capacity must not change when the factory returns to ACTIVE"
        )

    def test_cycle_create_on_offline_factory_returns_409(self, api, production_planner_headers):
        """PRD §3.4: "and the factory must not be `OFFLINE`, otherwise
        `ERR_FACTORY_OFFLINE`."

        Design: Corner/errors/cycle_create_on_offline_factory_returns_409
        """
        factory = create_factory()
        transition_factory(factory["id"], "OFFLINE")
        resp = api.create_allocation_cycle(
            {"factory_id": factory["id"], "week_start": WEEK_1_START},
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FACTORY_OFFLINE.value)
