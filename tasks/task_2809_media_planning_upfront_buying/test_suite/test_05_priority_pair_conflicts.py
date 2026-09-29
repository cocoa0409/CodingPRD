"""Rejection-precedence pairs: two rules broken at once, one identifier answered.

The file pins the two priority pairs of the design index — the buy-state check
outranking the campaign-budget check on a replacement placement, and the
cancellation-window check outranking the cancellation percentage ceiling.
"""

from test_helpers import (
    BUYER_HEADERS,
    ApiErrorId,
    assert_allocation_posture,
    assert_buy_axes,
    assert_cents,
    assert_close,
    assert_impressions,
    assert_instant_field,
    assert_pagination_meta,
    factories as fa,
    fixtures as fx,
    validate_error,
    validate_paginated,
)

# ==========================================================================
# Instance 1 — buy_state_check_outranks_campaign_budget_check_on_replacement
# ==========================================================================
#: The authorised working budget of the Ironwood plan.
_CAMPAIGN_BUDGET_CENTS = 160_000_000

#: The gross cost the 40,000,000 impression guarantee at CPM 2200 carries.
_BUY_GROSS_COST_CENTS = 91_520_000

#: What a second commitment of the same buy would take the campaign to.
_DOUBLE_COMMITMENT_CENTS = 183_040_000

_FLIGHT_START = "2026-11-01T00:00:00Z"
_FLIGHT_END = "2026-12-31T23:59:59Z"


def _placed_linear_buy(api):
    """One placed 91,520,000 cent buy against a 160,000,000 cent campaign.

    The single allocation claims the whole budget, so the placement leaves the
    allocation at ``WITHIN_PLAN`` and the plan still ``APPROVED``.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Ironwood Motors",
        category_code="AUTOMOTIVE",
        credit_limit_cents=300_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Granite Media Group",
        platform_types=["LINEAR"],
        make_good_capacity_impressions=10_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Ironwood Q4 Linear",
        target_demo="A25-54",
        universe_thousands=120_000,
        reach_goal_pct=50.0,
        frequency_goal=4.0,
        total_budget_cents=_CAMPAIGN_BUDGET_CENTS,
        flight_start=_FLIGHT_START,
        flight_end=_FLIGHT_END,
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
        program="Granite Prime",
        platform="LINEAR",
        window_start=_FLIGHT_START,
        window_end=_FLIGHT_END,
        total_impressions=60_000_000,
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
        requested_impressions=40_000_000,
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
        counter_impressions=40_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    fx.add_unit(
        api,
        buy["id"],
        avail["id"],
        daypart="PRIME",
        program="Granite Prime",
        platform="LINEAR",
        units=40,
        unit_rate_cents=2_200_000,
        projected_impressions=40_000_000,
        air_window_start="2026-11-02T00:00:00Z",
        air_window_end="2026-11-30T23:59:59Z",
    )
    fx.place_buy(api, buy["id"], campaign["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "buy_id": buy["id"],
    }


def _replace_the_placement(api, world):
    """Place the already-placed buy a second time on a freshly read version.

    Returns the campaign version the guard quoted and the raw response, so the
    optimistic-concurrency rung is satisfied and only the state and budget rungs
    are in contention.
    """
    version = fx.campaign_version(api, world["campaign_id"])
    response = api.place_buy(
        world["buy_id"], fa.place_payload(version), BUYER_HEADERS
    )
    return version, response


def _second_pending_buy(api, world):
    """A second, still ``PENDING_PLACEMENT`` buy of the same 91,520,000 cent shape.

    It is served from a second published avail of the same seller, so placing it
    would take the campaign's commitment to 183,040,000 cents against a
    160,000,000 cent budget while the buy-state rung is satisfied.
    """
    avail = fx.file_avail(
        api,
        world["seller_id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Granite Late",
        platform="LINEAR",
        window_start=_FLIGHT_START,
        window_end=_FLIGHT_END,
        total_impressions=60_000_000,
        forecast_cpm_cents=2200,
        exclusivity_mode="SHARED",
    )
    fx.publish_avail(api, avail["id"], world["seller_id"])
    negotiation = fx.open_negotiation(
        api,
        world["campaign_id"],
        world["seller_id"],
        world["allocation_id"],
        market="UPFRONT",
        channel="LINEAR_TV",
        requested_impressions=40_000_000,
        opening_cpm_cents=2000,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        negotiation["id"],
        world["seller_id"],
        counter_cpm_cents=2200,
        counter_impressions=40_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    fx.add_unit(
        api,
        buy["id"],
        avail["id"],
        daypart="PRIME",
        program="Granite Late",
        platform="LINEAR",
        units=40,
        unit_rate_cents=2_200_000,
        projected_impressions=40_000_000,
        air_window_start="2026-11-02T00:00:00Z",
        air_window_end="2026-11-30T23:59:59Z",
    )
    return buy["id"]


class TestBuyStateOutranksCampaignBudgetOnReplacement:
    """Replacing a placement breaks ladder rungs 11 and 42 at once."""

    def test_the_replacement_reports_the_buy_state_rung(self, api):
        """A second placement of a PLACED buy that would also double the campaign's
        commitment is answered with 409 ERR_BUY_NOT_IN_EXPECTED_STATE, never with
        the budget identifier.

        PRD: "When a request violates more than one rule, the system reports the
        rule that appears **earliest** in the ladder below and evaluates nothing
        further."

        Design: Difficulty/priority_pair_validation_conflict/buy_state_check_outranks_campaign_budget_check_on_replacement
        """
        world = _placed_linear_buy(api)
        _, response = _replace_the_placement(api, world)
        error = validate_error(response, ApiErrorId.BUY_NOT_IN_EXPECTED_STATE, 409)
        assert error["error_id"] != ApiErrorId.CAMPAIGN_BUDGET_EXCEEDED, (
            "the buy-state rung sits above the campaign-budget rung, so the "
            "budget identifier must never surface on a replacement placement"
        )

    def test_the_refused_replacement_moves_no_campaign_money(self, api):
        """The campaign still carries one commitment of 91,520,000 cents against
        68,480,000 cents of headroom, and its version did not advance.

        PRD: "Separately, the campaign's `committed_gross_cents` is the sum of
        `gross_cost_cents` over the campaign's buys whose `buy_status` is
        `PLACED`, `IN_FLIGHT`, `COMPLETED` or `CLOSED` — buys still at
        `PENDING_PLACEMENT` and buys that reached `CANCELLED` are excluded — and
        its `uncommitted_budget_cents` is `total_budget_cents` less that
        committed figure."

        Design: Difficulty/priority_pair_validation_conflict/buy_state_check_outranks_campaign_budget_check_on_replacement
        """
        world = _placed_linear_buy(api)
        version_before, response = _replace_the_placement(api, world)
        validate_error(response, ApiErrorId.BUY_NOT_IN_EXPECTED_STATE, 409)

        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_cents(campaign, "committed_gross_cents", _BUY_GROSS_COST_CENTS)
        assert_cents(
            campaign,
            "uncommitted_budget_cents",
            _CAMPAIGN_BUDGET_CENTS - _BUY_GROSS_COST_CENTS,
        )
        assert campaign["version"] == version_before, (
            f"the refused placement must increment nothing, but the campaign "
            f"version moved from {version_before} to {campaign['version']}"
        )

    def test_the_allocation_stays_within_plan_and_the_buy_stays_placed(self, api):
        """The single allocation still shows one 91,520,000 cent commitment inside
        its 160,000,000 cent share, and the buy is untouched at PLACED.

        PRD: "Its `posture` reads `OVERCOMMITTED` when `committed_cents` is
        strictly greater than `allocated_cents`, and `WITHIN_PLAN` otherwise — an
        allocation committed to exactly its allocated amount is still within
        plan."

        Design: Difficulty/priority_pair_validation_conflict/buy_state_check_outranks_campaign_budget_check_on_replacement
        """
        world = _placed_linear_buy(api)
        _, response = _replace_the_placement(api, world)
        validate_error(response, ApiErrorId.BUY_NOT_IN_EXPECTED_STATE, 409)

        allocation = fx.read_allocation(api, world["allocation_id"])
        assert_cents(allocation, "committed_cents", _BUY_GROSS_COST_CENTS)
        assert_cents(allocation, "allocated_cents", _CAMPAIGN_BUDGET_CENTS)
        assert_allocation_posture(allocation, posture="WITHIN_PLAN")
        assert_buy_axes(fx.read_buy(api, world["buy_id"]), buy_status="PLACED")

    def test_the_budget_rung_surfaces_once_the_buy_state_rung_is_satisfied(self, api):
        """The very same 183,040,000 cent overcommitment reported through a second,
        still PENDING_PLACEMENT buy is answered with ERR_CAMPAIGN_BUDGET_EXCEEDED,
        which is the rung the replacement placement suppressed.

        PRD: "Landing exactly on the budget is permitted; exceeding it by a cent
        is refused with `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/buy_state_check_outranks_campaign_budget_check_on_replacement
        """
        world = _placed_linear_buy(api)
        second_buy_id = _second_pending_buy(api, world)
        assert_buy_axes(
            fx.read_buy(api, second_buy_id), buy_status="PENDING_PLACEMENT"
        )

        version = fx.campaign_version(api, world["campaign_id"])
        response = api.place_buy(
            second_buy_id, fa.place_payload(version), BUYER_HEADERS
        )
        validate_error(response, ApiErrorId.CAMPAIGN_BUDGET_EXCEEDED, 409)

        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_cents(campaign, "committed_gross_cents", _BUY_GROSS_COST_CENTS)
        assert campaign["committed_gross_cents"] + _BUY_GROSS_COST_CENTS == (
            _DOUBLE_COMMITMENT_CENTS
        ), "the refused commitment would have doubled the campaign's outlay"


# ==========================================================================
# Instance 2 — cancellation_window_close_outranks_pct_ceiling
# ==========================================================================
#: The instant the cancellation ceiling steps down from 100.00 to 25.00 percent.
_CANCEL_WINDOW_1_CLOSE = "2026-09-02T00:00:00Z"

#: The instant the cancellation right disappears altogether.
_CANCEL_WINDOW_2_CLOSE = "2026-10-02T00:00:00Z"

#: A reading inside window two, where only the late ceiling can bite.
_INSIDE_LATE_WINDOW = "2026-09-15T00:00:00Z"

#: The cancellation both triggers ask for, twice the late ceiling of 25.00.
_REQUESTED_PCT = 50.00

#: The cost stack the 2,000,000 impression guarantee at CPM 2200 carries.
_TRAVEL_GROSS_COST_CENTS = 4_708_000


def _placed_travel_buy(api):
    """A placed 2,000,000 impression buy whose flight opens 2026-11-01.

    The clock is left at ``2026-09-15T00:00:00Z`` — inside cancellation window
    two, where the late 25.00 percent ceiling applies and the right is still
    exercisable.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Halcyon Travel",
        category_code="TRAVEL",
        credit_limit_cents=50_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Coastline Stations",
        platform_types=["LINEAR"],
        make_good_capacity_impressions=2_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Winter Escapes",
        target_demo="A25-54",
        universe_thousands=100_000,
        reach_goal_pct=40.0,
        frequency_goal=3.0,
        total_budget_cents=30_000_000,
        flight_start=_FLIGHT_START,
        flight_end=_FLIGHT_END,
        fiscal_quarter="2026Q4",
    )
    allocation = fx.add_allocation(
        api,
        campaign["id"],
        channel="LINEAR_TV",
        allocation_pct=100.00,
        planned_cpm_cents=2200,
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
        program="Coastline Tonight",
        platform="LINEAR",
        window_start=_FLIGHT_START,
        window_end=_FLIGHT_END,
        total_impressions=5_000_000,
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
        requested_impressions=2_000_000,
        opening_cpm_cents=2100,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=2200,
        counter_impressions=2_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    fx.add_unit(
        api,
        buy["id"],
        avail["id"],
        daypart="PRIME",
        program="Coastline Tonight",
        platform="LINEAR",
        units=1,
        unit_rate_cents=4_400_000,
        projected_impressions=2_000_000,
        air_window_start="2026-11-02T00:00:00Z",
        air_window_end="2026-11-30T23:59:59Z",
    )
    fx.place_buy(api, buy["id"], campaign["id"])
    fx.move_clock(api, _INSIDE_LATE_WINDOW)
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "buy_id": buy["id"],
    }


def _cancel_half(api, buy_id):
    """Ask to cancel 50.00 percent of the buy, whatever the clock reads."""
    return api.create_rights_exercise(
        fa.cancellation_payload(buy_id, _REQUESTED_PCT), BUYER_HEADERS
    )


class TestCancellationWindowCloseOutranksPctCeiling:
    """One 50.00 percent cancellation, two clock readings, two identifiers."""

    def test_the_buy_inherits_both_cancellation_deadlines(self, api):
        """A flight opening 2026-11-01 gives the buy cancel_window_1_close
        2026-09-02T00:00:00Z and cancel_window_2_close 2026-10-02T00:00:00Z.

        PRD: "Its `flight_start` and `flight_end` are copied from the campaign's
        flight window, and from that start instant three contractual deadlines are
        derived: `option_window_close` sits 45 days before `flight_start`,
        `cancel_window_1_close` sits 60 days before it, and
        `cancel_window_2_close` sits 30 days before it."

        Design: Difficulty/priority_pair_validation_conflict/cancellation_window_close_outranks_pct_ceiling
        """
        world = _placed_travel_buy(api)
        buy = fx.read_buy(api, world["buy_id"])
        assert_instant_field(buy, "flight_start", _FLIGHT_START)
        assert_instant_field(buy, "cancel_window_1_close", _CANCEL_WINDOW_1_CLOSE)
        assert_instant_field(buy, "cancel_window_2_close", _CANCEL_WINDOW_2_CLOSE)

    def test_inside_the_open_window_only_the_late_ceiling_bites(self, api):
        """At 2026-09-15, past window one but before window two, a 50.00 percent
        cancellation breaches the 25.00 percent late ceiling and is refused with
        422 ERR_RIGHTS_PCT_ABOVE_CEILING.

        PRD: "For a `CANCELLATION` the ceiling steps down as the flight
        approaches: while the logical clock is strictly earlier than
        `cancel_window_1_close` — 60 days before flight start — the agency may
        cancel up to 100.00 percent of the buy; from `cancel_window_1_close`
        inclusive up to `cancel_window_2_close` exclusive the ceiling drops to
        25.00 percent; and at or after `cancel_window_2_close` no cancellation
        right exists at all, which is the window rule above."

        Design: Difficulty/priority_pair_validation_conflict/cancellation_window_close_outranks_pct_ceiling
        """
        world = _placed_travel_buy(api)
        validate_error(
            _cancel_half(api, world["buy_id"]),
            ApiErrorId.RIGHTS_PCT_ABOVE_CEILING,
            422,
        )

    def test_at_the_window_close_the_window_rule_outranks_the_ceiling(self, api):
        """The identical payload answered with the ceiling identifier at 2026-09-15
        is answered with ERR_RIGHTS_WINDOW_CLOSED once the clock stands exactly on
        cancel_window_2_close.

        PRD: "An exercise attempted at exactly the closing instant, or after it,
        is refused with `ERR_RIGHTS_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/cancellation_window_close_outranks_pct_ceiling
        """
        world = _placed_travel_buy(api)
        validate_error(
            _cancel_half(api, world["buy_id"]),
            ApiErrorId.RIGHTS_PCT_ABOVE_CEILING,
            422,
        )

        fx.move_clock(api, _CANCEL_WINDOW_2_CLOSE)
        error = validate_error(
            _cancel_half(api, world["buy_id"]),
            ApiErrorId.RIGHTS_WINDOW_CLOSED,
            422,
        )
        assert error["error_id"] != ApiErrorId.RIGHTS_PCT_ABOVE_CEILING, (
            "the rights-window rung sits above the percentage-ceiling rung, so "
            "the ceiling identifier must not surface once the window has closed"
        )

    def test_both_refusals_leave_the_buy_and_the_ledger_untouched(self, api):
        """After both refusals the buy still guarantees 2,000,000 impressions at a
        gross of 4,708,000 cents with nothing cancelled and no exercise recorded.

        PRD: "In either case the test is cumulative: `requested_pct` plus the
        matching cumulative already exercised must be no greater than the ceiling,
        where the matching cumulative is `option_pct_cumulative` (the sum of
        `requested_pct` over this buy's `OPTION_ROLL` exercises) for an option and
        `cancelled_pct_cumulative` (the sum over its `CANCELLATION` exercises) for
        a cancellation."

        Design: Difficulty/priority_pair_validation_conflict/cancellation_window_close_outranks_pct_ceiling
        """
        world = _placed_travel_buy(api)
        validate_error(
            _cancel_half(api, world["buy_id"]),
            ApiErrorId.RIGHTS_PCT_ABOVE_CEILING,
            422,
        )
        fx.move_clock(api, _CANCEL_WINDOW_2_CLOSE)
        validate_error(
            _cancel_half(api, world["buy_id"]),
            ApiErrorId.RIGHTS_WINDOW_CLOSED,
            422,
        )

        buy = fx.read_buy(api, world["buy_id"])
        assert_close(
            buy["cancelled_pct_cumulative"], 0, "cancelled_pct_cumulative"
        )
        assert_impressions(buy, "guaranteed_impressions", 2_000_000)
        assert_cents(buy, "gross_cost_cents", _TRAVEL_GROSS_COST_CENTS)
        assert_buy_axes(buy, buy_status="PLACED")

        rows, meta = validate_paginated(
            api.list_rights_exercises(
                BUYER_HEADERS, params={"buy_id": world["buy_id"], "limit": 100}
            )
        )
        assert_pagination_meta(meta, expected_total=0)
        assert rows == [], f"no exercise record may exist, found {rows}"
