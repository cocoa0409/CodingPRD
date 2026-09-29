"""Compensating invariants: a reversal must undo exactly the ledgers its
originating write touched and must leave every other ledger where it stood.

The file covers two reversals — a hundred per cent cancellation, which must
return the budget and the inventory ledgers to their pre-placement values, and a
preemption, which must return only the inventory ledger while the committed money
stays exactly where the placement left it.
"""

from typing import Any, Dict, List

from test_helpers import (
    BUYER_HEADERS,
    BUYER_USER_ID,
    ApiErrorId,
    ApiClient,
    assert_allocation_posture,
    assert_append_only_shape,
    assert_budget_ledger_balances,
    assert_buy_axes,
    assert_campaign_axes,
    assert_cents,
    assert_impressions,
    assert_instant_field,
    assert_pct2,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    make_seller_rep_headers,
    validate_error,
    validate_success,
)

Json = Dict[str, Any]

#: The instant the logical clock reads before any test moves it, and the instant
#: the cancellation of the first instance is therefore stamped with.
CLOCK_AT_START = "2026-08-01T00:00:00Z"

#: The cost stack a 40,000,000 impression guarantee at CPM 2200 implies: the net
#: media cost reaches the lowest commission tier, so the rate is 0.0400.
GUARANTEED_IMPRESSIONS = 40_000_000
NET_MEDIA_COST_CENTS = 88_000_000
COMMISSION_RATE = 0.0400
AGENCY_COMMISSION_CENTS = 3_520_000
GROSS_COST_CENTS = 91_520_000

#: The campaign envelope both instances are built inside.
TOTAL_BUDGET_CENTS = 200_000_000
AVAIL_IMPRESSIONS = 40_000_000


def _placed_world(
    api: ApiClient,
    advertiser_name: str,
    category_code: str,
    seller_name: str,
    campaign_name: str,
    program: str,
    unit_specs: List[Json],
) -> Json:
    """One placed 91,520,000 cent linear buy holding a whole 40,000,000 avail.

    The campaign carries a single hundred per cent LINEAR_TV UPFRONT PRIME
    allocation, so ``allocated_cents`` is the full 200,000,000 and the placement
    leaves the allocation inside its plan.  The unit lines named by
    ``unit_specs`` together project the whole guarantee, which drains the avail to
    zero and leaves it EXHAUSTED.  The returned world carries the ledgers as they
    read immediately after placement, before any reversal.
    """
    advertiser = fx.register_advertiser(
        api,
        name=advertiser_name,
        category_code=category_code,
        credit_limit_cents=400_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name=seller_name,
        platform_types=["LINEAR"],
        make_good_capacity_impressions=5_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name=campaign_name,
        target_demo="A25-54",
        universe_thousands=120_000,
        reach_goal_pct=50.0,
        frequency_goal=4.0,
        total_budget_cents=TOTAL_BUDGET_CENTS,
        flight_start="2026-11-01T00:00:00Z",
        flight_end="2026-12-31T23:59:59Z",
        fiscal_quarter="2026Q4",
    )
    allocation = fx.add_allocation(
        api,
        campaign["id"],
        channel="LINEAR_TV",
        allocation_pct=100.00,
        planned_cpm_cents=1800,
        planned_market="UPFRONT",
        primary_daypart="PRIME",
    )
    fx.submit_plan(api, campaign["id"])
    fx.approve_plan(api, campaign["id"], advertiser["id"])
    avail = fx.file_avail(
        api,
        seller["id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program=program,
        platform="LINEAR",
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-12-31T23:59:59Z",
        total_impressions=AVAIL_IMPRESSIONS,
        forecast_cpm_cents=2200,
        exclusivity_mode="SHARED",
    )
    fx.publish_avail(api, avail["id"], seller["id"])
    negotiation = fx.open_negotiation(
        api,
        campaign["id"],
        seller["id"],
        allocation["id"],
        market="UPFRONT",
        channel="LINEAR_TV",
        requested_impressions=GUARANTEED_IMPRESSIONS,
        opening_cpm_cents=2000,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=2200,
        counter_impressions=GUARANTEED_IMPRESSIONS,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    units = [
        fx.add_unit(
            api,
            buy["id"],
            avail["id"],
            daypart="PRIME",
            program=program,
            platform="LINEAR",
            unit_rate_cents=2_200_000,
            **spec,
        )
        for spec in unit_specs
    ]
    fx.place_buy(api, buy["id"], campaign["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "seller_headers": make_seller_rep_headers(seller["id"]),
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "buy_id": buy["id"],
        "unit_ids": [unit["id"] for unit in units],
        "buy_before": fx.read_buy(api, buy["id"]),
        "allocation_before": fx.read_allocation(api, allocation["id"]),
        "campaign_before": fx.read_campaign(api, campaign["id"]),
        "avail_before": fx.read_avail(api, avail["id"]),
    }


# ==========================================================================
# full_cancellation_restores_budget_and_inventory_ledgers_exactly
# ==========================================================================
#: The single 40-unit line that holds the whole avail on the cancellation world.
_CANCELLATION_UNITS: List[Json] = [
    {
        "units": 40,
        "projected_impressions": 40_000_000,
        "air_window_start": "2026-11-02T00:00:00Z",
        "air_window_end": "2026-11-30T23:59:59Z",
    }
]


def _cancellation_world(api: ApiClient) -> Json:
    """The placed buy the cancellation is exercised against.

    The logical clock is still at 2026-08-01T00:00:00Z, strictly before the buy's
    cancel_window_1_close of 2026-09-02T00:00:00Z, so the hundred per cent
    cancellation ceiling is in force.
    """
    return _placed_world(
        api,
        advertiser_name="Perigee Airlines",
        category_code="TRAVEL",
        seller_name="Summit Vision TV",
        campaign_name="Perigee Q4 Linear",
        program="Summit Prime",
        unit_specs=_CANCELLATION_UNITS,
    )


def _cancel_in_full(api: ApiClient, buy_id: str):
    """The trigger: the placing buyer cancels 100.00 percent of the buy."""
    return api.create_rights_exercise(
        fa.cancellation_payload(buy_id, 100.00), BUYER_HEADERS
    )


class TestFullCancellationRestoresLedgersExactly:
    """A hundred per cent cancellation undoes every ledger the placement wrote."""

    def test_the_early_window_applies_the_hundred_percent_ceiling(self, api):
        """A cancellation recorded while the clock is still strictly before
        cancel_window_1_close is admitted at a ceiling of 100.00 percent.

        PRD: "For a `CANCELLATION` the ceiling steps down as the flight
        approaches: while the logical clock is strictly earlier than
        `cancel_window_1_close` — 60 days before flight start — the agency may
        cancel up to 100.00 percent of the buy; from `cancel_window_1_close`
        inclusive up to `cancel_window_2_close` exclusive the ceiling drops to
        25.00 percent; and at or after `cancel_window_2_close` no cancellation
        right exists at all, which is the window rule above."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)

        exercise = validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        assert exercise["buy_id"] == world["buy_id"]
        assert exercise["kind"] == "CANCELLATION"
        assert_pct2(exercise, "requested_pct", 100.00)
        assert_pct2(exercise, "applied_ceiling_pct", 100.00)

    def test_the_exercise_record_stamps_the_clock_and_the_acting_buyer(self, api):
        """The cancellation record carries the logical clock instant and the
        buyer's own identifier, and neither an update instant nor a version.

        PRD: "The record also stamps `exercised_at` from the logical clock and
        `exercised_by_user_id` from the acting `X-User-ID`, and it is never
        modified afterwards; as noted in §2.4, a rights exercise carries neither
        `updated_at` nor `version`."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)

        exercise = validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        assert_instant_field(exercise, "exercised_at", CLOCK_AT_START)
        assert exercise["exercised_by_user_id"] == BUYER_USER_ID
        assert_append_only_shape(exercise)

    def test_the_deltas_reverse_the_whole_placement(self, api):
        """Cancelling the whole guarantee records a delta of -40,000,000
        impressions and a gross delta of -91,520,000 cents.

        PRD: "The exercise records `delta_gross_cents`, the signed difference
        between the buy's `gross_cost_cents` after the recomputation and its value
        before it — a large option roll can therefore cross a tier boundary
        downward and produce a proportionally smaller commission increase than the
        impression increase would suggest."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)
        assert_cents(world["buy_before"], "gross_cost_cents", GROSS_COST_CENTS)

        exercise = validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        assert_impressions(exercise, "delta_impressions", -40_000_000)
        assert_cents(exercise, "delta_gross_cents", -91_520_000)

    def test_the_sweep_cancels_the_single_line_and_returns_the_whole_avail(self, api):
        """The one scheduled line is swept to CANCELLED and the avail it held
        goes from 0 available and EXHAUSTED back to 40,000,000 and PUBLISHED.

        PRD: "Each cancelled line releases its hold, so the avail it occupied
        gains back its `projected_impressions` in `available_impressions`, and an
        avail sitting at `EXHAUSTED` returns `EXHAUSTED → PUBLISHED` the moment
        its availability becomes positive again, with its `version` incrementing."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)
        assert_impressions(world["avail_before"], "available_impressions", 0)
        assert world["avail_before"]["status"] == "EXHAUSTED"

        exercise = validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        assert exercise["cancelled_unit_count"] == 1
        unit = validate_success(api.get_buy_unit(world["unit_ids"][0], BUYER_HEADERS))
        assert unit["status"] == "CANCELLED"
        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert_impressions(avail, "available_impressions", 40_000_000)
        assert avail["status"] == "PUBLISHED"
        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_impressions(buy, "placed_impressions", 0)

    def test_the_cost_tier_is_reselected_on_the_new_net_of_zero(self, api):
        """The cancelled buy's whole cost stack is rebuilt from a guarantee of 0,
        so the commission rate falls to the smallest tier's 0.0700 rather than
        staying at the 0.0400 it was placed at.

        PRD: "The buy's `guaranteed_impressions` is then adjusted by that signed
        amount and its entire cost stack is recomputed from scratch with the
        commission tier re-selected on the new pre-commission net:
        `net_media_cost_cents`, `commission_rate`, `agency_commission_cents` and
        `gross_cost_cents` are all rewritten by the three-tier arithmetic of §3.5."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)
        assert_pct4(world["buy_before"], "commission_rate", COMMISSION_RATE)

        validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_impressions(buy, "guaranteed_impressions", 0)
        assert_cents(buy, "net_media_cost_cents", 0)
        assert_cents(buy, "agency_commission_cents", 0)
        assert_cents(buy, "gross_cost_cents", 0)
        assert_pct4(buy, "commission_rate", 0.0700)

    def test_the_buy_reaches_cancelled_at_a_full_cumulative_percentage(self, api):
        """The buy itself is finished: it moves PLACED to CANCELLED with a
        cumulative cancelled percentage of 100.00.

        PRD: "When cumulative cancellation reaches 100.00 percent, the buy itself
        is finished: `buy_status` moves `PLACED → CANCELLED`,
        `guaranteed_impressions` is set to 0 and every cost field is recomputed to
        0, so the buy drops out of the allocation's `committed_cents` and the
        campaign's `committed_gross_cents` entirely, and the buy's `version`
        increments."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)
        assert_buy_axes(world["buy_before"], buy_status="PLACED")

        validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, buy_status="CANCELLED")
        assert_pct2(buy, "cancelled_pct_cumulative", 100.00)
        assert buy["version"] > world["buy_before"]["version"]

    def test_the_allocation_and_campaign_money_ledgers_return_to_zero(self, api):
        """Both money ledgers the placement wrote unwind exactly: the allocation
        returns to 0 committed and WITHIN_PLAN, and the campaign returns to 0
        committed with the whole 200,000,000 uncommitted again.

        PRD: "Separately, the campaign's `committed_gross_cents` is the sum of
        `gross_cost_cents` over the campaign's buys whose `buy_status` is `PLACED`,
        `IN_FLIGHT`, `COMPLETED` or `CLOSED` — buys still at `PENDING_PLACEMENT`
        and buys that reached `CANCELLED` are excluded — and its
        `uncommitted_budget_cents` is `total_budget_cents` less that committed
        figure."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)
        assert_cents(world["allocation_before"], "committed_cents", GROSS_COST_CENTS)
        assert_cents(
            world["campaign_before"], "committed_gross_cents", GROSS_COST_CENTS
        )

        validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], BUYER_HEADERS)
        )
        assert_cents(allocation, "committed_cents", 0)
        assert_allocation_posture(allocation, posture="WITHIN_PLAN")
        campaign = validate_success(
            api.get_campaign(world["campaign_id"], BUYER_HEADERS)
        )
        assert_cents(campaign, "committed_gross_cents", 0)
        assert_cents(campaign, "uncommitted_budget_cents", TOTAL_BUDGET_CENTS)
        assert_budget_ledger_balances(campaign)

    def test_the_reversal_does_not_run_the_overcommit_cascade_backwards(self, api):
        """The planning axes are the ledger that must not move: the campaign stays
        APPROVED and WITHIN_PLAN and the allocation stays LOCKED, because a
        reversal never drives the replan cascade.

        PRD: "When the system recomputes a campaign's `plan_posture` to
        `REPLAN_REQUIRED` while its `plan_status` sits at `APPROVED`, the campaign
        is automatically pushed `APPROVED → REVISION_REQUIRED`."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)
        assert_campaign_axes(
            world["campaign_before"], plan_status="APPROVED", plan_posture="WITHIN_PLAN"
        )

        validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        campaign = validate_success(
            api.get_campaign(world["campaign_id"], BUYER_HEADERS)
        )
        assert_campaign_axes(
            campaign, plan_status="APPROVED", plan_posture="WITHIN_PLAN"
        )
        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], BUYER_HEADERS)
        )
        assert_allocation_posture(allocation, status="LOCKED")

    def test_a_repeat_cancellation_cannot_reverse_the_ledgers_twice(self, api):
        """A second hundred per cent cancellation against the now CANCELLED buy is
        refused as already terminal, and every reversed ledger stands where the
        first exercise left it.

        PRD: "Rights may only be exercised while the buy sits at
        `PENDING_PLACEMENT` or `PLACED`; a buy that has reached `IN_FLIGHT`,
        `COMPLETED`, `CLOSED` or `CANCELLED` is refused with
        `ERR_BUY_NOT_IN_EXPECTED_STATE`, and the two terminal placement states are
        caught even earlier by `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/compensating_invariant/full_cancellation_restores_budget_and_inventory_ledgers_exactly
        """
        world = _cancellation_world(api)
        validate_success(_cancel_in_full(api, world["buy_id"]), 201)

        validate_error(
            _cancel_in_full(api, world["buy_id"]), ApiErrorId.ALREADY_TERMINAL, 409
        )

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, buy_status="CANCELLED")
        assert_pct2(buy, "cancelled_pct_cumulative", 100.00)
        assert_cents(buy, "gross_cost_cents", 0)
        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], BUYER_HEADERS)
        )
        assert_cents(allocation, "committed_cents", 0)
        campaign = validate_success(
            api.get_campaign(world["campaign_id"], BUYER_HEADERS)
        )
        assert_cents(campaign, "committed_gross_cents", 0)
        assert_cents(campaign, "uncommitted_budget_cents", TOTAL_BUDGET_CENTS)
        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert_impressions(avail, "available_impressions", AVAIL_IMPRESSIONS)
        assert avail["status"] == "PUBLISHED"


# ==========================================================================
# preemption_reverses_inventory_hold_without_touching_committed_money
# ==========================================================================
#: Two 20-unit lines of 20,000,000 projected impressions that together exhaust
#: the avail, airing in the first and the second half of November.
_PREEMPTION_UNITS: List[Json] = [
    {
        "units": 20,
        "projected_impressions": 20_000_000,
        "air_window_start": "2026-11-02T00:00:00Z",
        "air_window_end": "2026-11-15T23:59:59Z",
    },
    {
        "units": 20,
        "projected_impressions": 20_000_000,
        "air_window_start": "2026-11-16T00:00:00Z",
        "air_window_end": "2026-11-30T23:59:59Z",
    },
]


def _preemption_world(api: ApiClient) -> Json:
    """The two-line placed buy whose first line is about to be preempted.

    The logical clock is advanced to 2026-12-01T00:00:00Z so both air windows have
    elapsed and either line may be settled.  The ledger snapshots are refreshed
    after the clock move so they read exactly as they stand before the trigger.
    """
    world = _placed_world(
        api,
        advertiser_name="Kestrel Bank",
        category_code="FINANCE",
        seller_name="Arbor Broadcasting",
        campaign_name="Kestrel Q4 Linear",
        program="Arbor Prime",
        unit_specs=_PREEMPTION_UNITS,
    )
    fx.move_clock(api, "2026-12-01T00:00:00Z")
    world["buy_before"] = fx.read_buy(api, world["buy_id"])
    world["allocation_before"] = fx.read_allocation(api, world["allocation_id"])
    world["campaign_before"] = fx.read_campaign(api, world["campaign_id"])
    world["avail_before"] = fx.read_avail(api, world["forecast_id"])
    return world


def _preempt_first_line(api: ApiClient, world: Json):
    """The trigger: the seller settles the first line as PREEMPTED."""
    return api.settle_airing(
        world["unit_ids"][0], fa.settle_preempted_payload(), world["seller_headers"]
    )


def _air_second_line(api: ApiClient, world: Json):
    """The follow-on trigger: the sibling line airs 21,000,000 impressions."""
    return api.settle_airing(
        world["unit_ids"][1],
        fa.settle_aired_payload(21_000_000),
        world["seller_headers"],
    )


class TestPreemptionReversesInventoryHoldOnly:
    """A preemption gives back inventory and leaves the committed money alone."""

    def test_the_preempted_line_gives_back_exactly_its_own_projection(self, api):
        """Preempting one of the two lines returns that line's 20,000,000
        projected impressions to the avail, which held 0 before.

        PRD: "First, because the line no longer holds inventory, the avail's
        `available_impressions` grows by that line's `projected_impressions`."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        assert_impressions(world["avail_before"], "available_impressions", 0)

        unit = validate_success(_preempt_first_line(api, world))

        assert unit["status"] == "PREEMPTED"
        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert_impressions(avail, "available_impressions", 20_000_000)

    def test_the_released_hold_makes_the_exhausted_avail_sellable_again(self, api):
        """The avail was EXHAUSTED while both lines held it; the released hold
        pushes it back to PUBLISHED with a further version increment.

        PRD: "When a hold is released — by a preemption or by a cancellation sweep
        — and `available_impressions` becomes greater than 0 again, the avail moves
        `EXHAUSTED → PUBLISHED` with another `version` increment, and it is
        immediately sellable once more."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        assert world["avail_before"]["status"] == "EXHAUSTED"

        validate_success(_preempt_first_line(api, world))

        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert avail["status"] == "PUBLISHED"
        assert avail["version"] > world["avail_before"]["version"]

    def test_the_aired_sibling_releases_nothing_at_all(self, api):
        """Settling the second line AIRED at 21,000,000 actual impressions leaves
        availability at 20,000,000, because an AIRED line still occupies its avail.

        PRD: "The remaining-availability figure is a live subtraction rather than a
        counter that only ever decreases: at any moment `available_impressions` is
        `total_impressions` less the sum of `projected_impressions` over the unit
        lines occupying this avail whose `status` is `SCHEDULED`, `AIRED`,
        `MAKE_GOOD_SCHEDULED` or `MAKE_GOOD_AIRED`."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        validate_success(_preempt_first_line(api, world))

        aired = validate_success(_air_second_line(api, world))

        assert aired["status"] == "AIRED"
        assert_impressions(aired, "actual_impressions", 21_000_000)
        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert_impressions(avail, "available_impressions", 20_000_000)
        assert avail["status"] == "PUBLISHED"

    def test_the_shrunken_placement_puts_the_buy_at_risk(self, api):
        """With one line preempted the buy holds only 20,000,000 placed impressions
        against a 40,000,000 guarantee, so stewardship moves to AT_RISK while the
        placement axis stays PLACED.

        PRD: "Third, because the buy's recomputed `placed_impressions` has fallen
        below its `guaranteed_impressions`, the buy's `stewardship_status` moves to
        `AT_RISK` — from `NOT_STARTED` if no delivery had yet been accepted, or from
        `ON_TRACK` if some had."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        assert_buy_axes(world["buy_before"], stewardship_status="NOT_STARTED")

        validate_success(_preempt_first_line(api, world))

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_impressions(buy, "placed_impressions", 20_000_000)
        assert_impressions(buy, "guaranteed_impressions", GUARANTEED_IMPRESSIONS)
        assert_buy_axes(buy, buy_status="PLACED", stewardship_status="AT_RISK")

    def test_the_buy_cost_stack_is_untouched_by_either_settlement(self, api):
        """Neither the preemption nor the airing rewrites the buy's cost: it still
        stands at 88,000,000 net, rate 0.0400 and 91,520,000 gross.

        PRD: "The buy's cost is computed at this moment from two inputs and nothing
        else."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        validate_success(_preempt_first_line(api, world))
        validate_success(_air_second_line(api, world))

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))

        assert_cents(buy, "net_media_cost_cents", NET_MEDIA_COST_CENTS)
        assert_pct4(buy, "commission_rate", COMMISSION_RATE)
        assert_cents(buy, "agency_commission_cents", AGENCY_COMMISSION_CENTS)
        assert_cents(buy, "gross_cost_cents", GROSS_COST_CENTS)

    def test_the_allocation_still_carries_the_whole_commitment(self, api):
        """The allocation's committed money is the ledger that must not move: the
        buy is still PLACED, so 91,520,000 stays committed and the posture stays
        WITHIN_PLAN.

        PRD: "An allocation's `committed_cents` is the sum of `gross_cost_cents`
        over buys whose `channel_allocation_id` is this allocation and whose
        `buy_status` is `PLACED`, `IN_FLIGHT`, `COMPLETED` or `CLOSED`."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        assert_cents(world["allocation_before"], "committed_cents", GROSS_COST_CENTS)
        validate_success(_preempt_first_line(api, world))
        validate_success(_air_second_line(api, world))

        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], BUYER_HEADERS)
        )

        assert_cents(allocation, "committed_cents", GROSS_COST_CENTS)
        assert_allocation_posture(allocation, posture="WITHIN_PLAN")

    def test_the_campaign_budget_residue_does_not_move(self, api):
        """The campaign still shows 91,520,000 committed and 108,480,000
        uncommitted after the preemption, because a preempted line does not take
        its buy out of the committed set.

        PRD: "Separately, the campaign's `committed_gross_cents` is the sum of
        `gross_cost_cents` over the campaign's buys whose `buy_status` is `PLACED`,
        `IN_FLIGHT`, `COMPLETED` or `CLOSED` — buys still at `PENDING_PLACEMENT`
        and buys that reached `CANCELLED` are excluded — and its
        `uncommitted_budget_cents` is `total_budget_cents` less that committed
        figure."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        validate_success(_preempt_first_line(api, world))
        validate_success(_air_second_line(api, world))

        campaign = validate_success(
            api.get_campaign(world["campaign_id"], BUYER_HEADERS)
        )

        assert_cents(campaign, "committed_gross_cents", GROSS_COST_CENTS)
        assert_cents(campaign, "uncommitted_budget_cents", 108_480_000)
        assert_budget_ledger_balances(campaign)

    def test_no_settlement_credit_arises_from_an_airing_alone(self, api):
        """Airing 21,000,000 impressions credits nothing on its own: no delivery
        report has been accepted, so the final credit stays 0 and the final
        delivery index stays 0.0000.

        PRD: "The **final** view is the settlement number:
        `credited_impressions_final` is the sum of `delivered_demo_impressions` over
        the buy's reports whose `status` is exactly `ACCEPTED`, and
        `final_delivery_index` is that credit divided by `guaranteed_impressions`,
        likewise rounded half up to four decimal places and likewise 0.0000 when
        the guarantee is 0."

        Design: Difficulty/compensating_invariant/preemption_reverses_inventory_hold_without_touching_committed_money
        """
        world = _preemption_world(api)
        validate_success(_preempt_first_line(api, world))
        validate_success(_air_second_line(api, world))

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))

        assert_impressions(buy, "credited_impressions_final", 0)
        assert_pct4(buy, "final_delivery_index", 0.0000)
