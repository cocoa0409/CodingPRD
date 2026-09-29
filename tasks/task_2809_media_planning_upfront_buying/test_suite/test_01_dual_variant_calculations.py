"""Dual-variant calculations: one body of rows read twice, two different answers.

The file covers the two delivery-credit views a single buy carries at once — the
provisional index against the final index — and the two deduplication methods a
reconciliation run may apply to one identical set of accepted reports.
"""

from test_helpers import (
    BUYER_HEADERS,
    PLANNER_HEADERS,
    assert_buy_axes,
    assert_impressions,
    assert_pct2,
    assert_pct4,
    dec,
    factories as fa,
    fixtures as fx,
    pct4,
    validate_paginated,
    validate_success,
)

#: An instant past the whole campaign flight, so every measured period is reportable.
_AFTER_FLIGHT = "2027-01-01T00:00:00Z"

#: The brand and the seller both instances trade between.
_ADVERTISER = {
    "name": "Cascadia Beverage",
    "category_code": "BEVERAGE",
    "credit_limit_cents": 500_000_000,
    "payment_terms_days": 45,
    "sequential_liability_enabled": True,
}
_SELLER = {
    "name": "Harbor Broadcasting",
    "platform_types": ["LINEAR", "CTV", "DIGITAL"],
    "make_good_capacity_impressions": 50_000_000,
}

#: The 200,000,000 cent fourth-quarter plan, split 60 linear / 40 digital.
_CAMPAIGN = {
    "name": "Q4 Reach Push",
    "target_demo": "A25-54",
    "universe_thousands": 120_000,
    "reach_goal_pct": 60.0,
    "frequency_goal": 4.0,
    "total_budget_cents": 200_000_000,
    "flight_start": "2026-11-01T00:00:00Z",
    "flight_end": "2026-12-31T23:59:59Z",
    "fiscal_quarter": "2026Q4",
}
_LINEAR_ALLOCATION = {
    "channel": "LINEAR_TV",
    "allocation_pct": 60.00,
    "planned_cpm_cents": 1800,
    "planned_market": "UPFRONT",
    "primary_daypart": "PRIME",
}
_DIGITAL_ALLOCATION = {
    "channel": "DIGITAL_VIDEO",
    "allocation_pct": 40.00,
    "planned_cpm_cents": 2500,
    "planned_market": "SCATTER",
    "primary_daypart": "DIGITAL_ANY",
}

#: The prime linear avail the 40,000,000 impression guarantee is served from.
_LINEAR_AVAIL = {
    "market": "UPFRONT",
    "fiscal_quarter": "2026Q4",
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "window_start": "2026-11-01T00:00:00Z",
    "window_end": "2026-12-31T23:59:59Z",
    "total_impressions": 60_000_000,
    "forecast_cpm_cents": 2200,
    "exclusivity_mode": "SHARED",
}
_LINEAR_NEGOTIATION = {
    "market": "UPFRONT",
    "channel": "LINEAR_TV",
    "requested_impressions": 40_000_000,
    "opening_cpm_cents": 2000,
    "guarantee_pct": 100,
    "make_good_provision": "MAKE_GOOD_UNITS",
    "option_pct_ceiling": 25,
}
_LINEAR_UNIT = {
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "units": 40,
    "unit_rate_cents": 2_200_000,
    "projected_impressions": 40_000_000,
    "air_window_start": "2026-11-02T00:00:00Z",
    "air_window_end": "2026-11-30T23:59:59Z",
}


def _approved_plan(api):
    """The brand, the seller and the approved two-channel plan they trade under."""
    advertiser = fx.register_advertiser(api, **_ADVERTISER)
    seller = fx.register_seller(api, **_SELLER)
    campaign = fx.open_campaign(api, advertiser["id"], **_CAMPAIGN)
    linear = fx.add_allocation(api, campaign["id"], **_LINEAR_ALLOCATION)
    digital = fx.add_allocation(api, campaign["id"], **_DIGITAL_ALLOCATION)
    fx.submit_plan(api, campaign["id"])
    fx.approve_plan(api, campaign["id"], advertiser["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "linear_allocation_id": linear["id"],
        "digital_allocation_id": digital["id"],
    }


def _place_linear_buy(api, world):
    """A placed linear buy guaranteeing 40,000,000 impressions at a 2200 cent CPM."""
    avail = fx.file_avail(api, world["seller_id"], **_LINEAR_AVAIL)
    fx.publish_avail(api, avail["id"], world["seller_id"])
    negotiation = fx.open_negotiation(
        api,
        world["campaign_id"],
        world["seller_id"],
        world["linear_allocation_id"],
        **_LINEAR_NEGOTIATION,
    )
    fx.counter(
        api,
        negotiation["id"],
        world["seller_id"],
        counter_cpm_cents=2200,
        counter_impressions=40_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    fx.add_unit(api, buy["id"], avail["id"], **_LINEAR_UNIT)
    fx.place_buy(api, buy["id"], world["campaign_id"])
    world["linear_forecast_id"] = avail["id"]
    world["linear_buy_id"] = buy["id"]
    return world


def _two_report_world(api):
    """One placed linear buy carrying two SUBMITTED reports, interim then post-buy.

    November credits 20,000,000 gross against 18,000,000 on the target demo and
    closes inside the flight, so it is not post-buy final; December credits
    21,000,000 gross against 19,200,000 demo and closes on the flight end, so it
    is.
    """
    world = _place_linear_buy(api, _approved_plan(api))
    fx.move_clock(api, _AFTER_FLIGHT)
    interim = fx.file_report(
        api,
        world["linear_buy_id"],
        20_000_000,
        18_000_000,
        seller_id=world["seller_id"],
        measurement_basis="LINEAR_C3",
        period_start="2026-11-01T00:00:00Z",
        period_end="2026-11-30T23:59:59Z",
    )
    post_buy = fx.file_report(
        api,
        world["linear_buy_id"],
        21_000_000,
        19_200_000,
        seller_id=world["seller_id"],
        measurement_basis="LINEAR_C3",
        period_start="2026-12-01T00:00:00Z",
        period_end="2026-12-31T23:59:59Z",
    )
    world["interim_report_id"] = interim["id"]
    world["post_buy_report_id"] = post_buy["id"]
    return world


def _accept_the_interim_report(api, world):
    """Accept the November report alone and read the buy back."""
    validate_success(
        api.accept_delivery_report(world["interim_report_id"], None, BUYER_HEADERS), 200
    )
    return validate_success(api.get_buy(world["linear_buy_id"], BUYER_HEADERS), 200)


class TestProvisionalVersusFinalDeliveryIndex:
    """Two credit views on one buy, over exactly the same two delivery reports."""

    def test_the_two_indices_diverge_on_one_report_set(self, api):
        """One accepted interim report and one still-submitted post-buy report leave
        the buy carrying a provisional index of 1.0250 against a final index of
        0.4500.

        PRD: "Because the final view counts only accepted reports and only
        target-demo impressions, the same body of reports always yields a final
        index no higher than the provisional one — and it is the final view alone
        that drives stewardship state and make-good creation."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_delivery_index_diverge_on_same_reports
        """
        world = _two_report_world(api)
        buy = _accept_the_interim_report(api, world)

        assert_impressions(buy, "credited_impressions_provisional", 41_000_000)
        assert_pct4(buy, "provisional_delivery_index", 1.0250)
        assert_impressions(buy, "credited_impressions_final", 18_000_000)
        assert_pct4(buy, "final_delivery_index", 0.4500)
        gap = pct4(
            dec(buy["provisional_delivery_index"]) - dec(buy["final_delivery_index"])
        )
        assert gap == 0.5750, f"expected a 0.5750 gap between the two indices, got {gap}"

    def test_the_provisional_credit_counts_the_unvetted_gross_claim(self, api):
        """The provisional credit adds the submitted December gross to the accepted
        November gross, reaching 41,000,000 impressions and an index of 1.0250.

        PRD: "The **provisional** view is the in-flight stewardship number:
        `credited_impressions_provisional` is the sum of `delivered_impressions`
        over the buy's reports whose `status` is `SUBMITTED` or `ACCEPTED`, so
        unvetted seller claims count toward it, and `provisional_delivery_index` is
        that credit divided by the buy's `guaranteed_impressions`, rounded half up
        to four decimal places, reading 0.0000 when `guaranteed_impressions` is 0."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_delivery_index_diverge_on_same_reports
        """
        world = _two_report_world(api)
        buy = _accept_the_interim_report(api, world)

        assert_impressions(buy, "credited_impressions_provisional", 41_000_000)
        assert_pct4(buy, "provisional_delivery_index", 1.0250)

    def test_the_final_credit_counts_only_the_accepted_demo_impressions(self, api):
        """The final credit takes the accepted November report's 18,000,000 demo
        impressions and nothing else, for an index of 0.4500.

        PRD: "The **final** view is the settlement number:
        `credited_impressions_final` is the sum of `delivered_demo_impressions` over
        the buy's reports whose `status` is exactly `ACCEPTED`, and
        `final_delivery_index` is that credit divided by `guaranteed_impressions`,
        likewise rounded half up to four decimal places and likewise 0.0000 when the
        guarantee is 0."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_delivery_index_diverge_on_same_reports
        """
        world = _two_report_world(api)
        buy = _accept_the_interim_report(api, world)

        assert_impressions(buy, "credited_impressions_final", 18_000_000)
        assert_pct4(buy, "final_delivery_index", 0.4500)

    def test_the_post_buy_flag_separates_the_two_reports(self, api):
        """November is accepted and not post-buy final while December is still
        submitted and is post-buy final, because its period closes on the flight end.

        PRD: "A filed report starts at `status` `SUBMITTED` with `dispute_reason`
        null, and the system computes `is_post_buy_final` for it at that moment: the
        flag reads true exactly when `period_end` is at or after the buy's
        `flight_end`, and it is that flag which makes a later acceptance run the
        post-buy shortfall evaluation."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_delivery_index_diverge_on_same_reports
        """
        world = _two_report_world(api)
        _accept_the_interim_report(api, world)

        interim = validate_success(
            api.get_delivery_report(world["interim_report_id"], BUYER_HEADERS), 200
        )
        post_buy = validate_success(
            api.get_delivery_report(world["post_buy_report_id"], BUYER_HEADERS), 200
        )

        assert interim["status"] == "ACCEPTED", (
            f"the accepted report must read ACCEPTED, got {interim['status']}"
        )
        assert interim["is_post_buy_final"] is False, (
            "a period closing inside the flight is not post-buy final"
        )
        assert post_buy["status"] == "SUBMITTED", (
            f"the unadjudicated report must stay SUBMITTED, got {post_buy['status']}"
        )
        assert post_buy["is_post_buy_final"] is True, (
            "a period closing on the flight end is post-buy final"
        )

    def test_the_first_acceptance_moves_the_buy_into_flight(self, api):
        """Accepting the first report of a placed buy advances the placement axis to
        IN_FLIGHT.

        PRD: "If the buy was at `PLACED`, it moves `PLACED → IN_FLIGHT` on this first
        acceptance."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_delivery_index_diverge_on_same_reports
        """
        world = _two_report_world(api)
        buy = _accept_the_interim_report(api, world)

        assert_buy_axes(buy, buy_status="IN_FLIGHT")

    def test_an_interim_acceptance_leaves_stewardship_on_track_and_opens_no_make_good(
        self, api
    ):
        """The accepted report is not post-buy final, so stewardship reads ON_TRACK and
        the shortfall chain never reaches make-good creation.

        PRD: "If the accepted report's `is_post_buy_final` is false, the stewardship
        axis moves `NOT_STARTED → ON_TRACK` and the chain stops here."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_delivery_index_diverge_on_same_reports
        """
        world = _two_report_world(api)
        buy = _accept_the_interim_report(api, world)

        assert_buy_axes(buy, stewardship_status="ON_TRACK")

        rows, meta = validate_paginated(
            api.list_make_goods(
                BUYER_HEADERS, params={"buy_id": world["linear_buy_id"], "limit": 100}
            )
        )
        assert rows == [], f"the interim acceptance must open no make-good, got {rows}"
        assert meta["total_count"] == 0, (
            f"expected no make-good on the buy, got {meta['total_count']}"
        )

    def test_the_open_shortfall_measures_the_final_credit_alone(self, api):
        """The buy still owes 22,000,000 impressions: its 40,000,000 guarantee less the
        18,000,000 the final view has credited, with nothing made good or waived.

        PRD: "The buy's `open_shortfall_impressions` is the live measure of what the
        seller still owes: it is the shortfall computed above, reduced by the buy's
        `made_good_impressions` and by its `waived_impressions`, and floored at 0 so
        it never reads negative."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_delivery_index_diverge_on_same_reports
        """
        world = _two_report_world(api)
        buy = _accept_the_interim_report(api, world)

        assert_impressions(buy, "open_shortfall_impressions", 22_000_000)
        assert_impressions(buy, "made_good_impressions", 0)
        assert_impressions(buy, "waived_impressions", 0)


#: The scatter digital avail the 24,000,000 impression guarantee is served from.
_DIGITAL_AVAIL = {
    "market": "SCATTER",
    "fiscal_quarter": "2026Q4",
    "daypart": "DIGITAL_ANY",
    "program": "Harbor Video Network",
    "platform": "DIGITAL",
    "window_start": "2026-11-01T00:00:00Z",
    "window_end": "2026-12-31T23:59:59Z",
    "total_impressions": 40_000_000,
    "forecast_cpm_cents": 1300,
    "exclusivity_mode": "SHARED",
}
_DIGITAL_NEGOTIATION = {
    "market": "SCATTER",
    "channel": "DIGITAL_VIDEO",
    "requested_impressions": 24_000_000,
    "opening_cpm_cents": 1100,
    "guarantee_pct": 100,
    "make_good_provision": "CASH_CREDIT",
    "option_pct_ceiling": 25,
}
_DIGITAL_UNIT = {
    "daypart": "DIGITAL_ANY",
    "program": "Harbor Video Network",
    "platform": "DIGITAL",
    "units": 24,
    "unit_rate_cents": 1_250_000,
    "projected_impressions": 24_000_000,
    "air_window_start": "2026-11-05T00:00:00Z",
    "air_window_end": "2026-12-20T23:59:59Z",
}


def _place_digital_buy(api, world):
    """A placed digital buy guaranteeing 24,000,000 impressions at a 1250 cent CPM."""
    avail = fx.file_avail(api, world["seller_id"], **_DIGITAL_AVAIL)
    fx.publish_avail(api, avail["id"], world["seller_id"])
    negotiation = fx.open_negotiation(
        api,
        world["campaign_id"],
        world["seller_id"],
        world["digital_allocation_id"],
        **_DIGITAL_NEGOTIATION,
    )
    fx.counter(
        api,
        negotiation["id"],
        world["seller_id"],
        counter_cpm_cents=1250,
        counter_impressions=24_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    fx.add_unit(api, buy["id"], avail["id"], **_DIGITAL_UNIT)
    fx.place_buy(api, buy["id"], world["campaign_id"])
    world["digital_forecast_id"] = avail["id"]
    world["digital_buy_id"] = buy["id"]
    return world


def _delivered_two_channel_world(api):
    """Both placed buys carrying nothing but ACCEPTED delivery reports.

    The linear buy's two accepted reports credit 18,000,000 plus 19,200,000 demo
    impressions, and the digital buy's single accepted post-buy report credits
    24,000,000 demo impressions against a 24,000,000 guarantee.
    """
    world = _approved_plan(api)
    _place_linear_buy(api, world)
    _place_digital_buy(api, world)
    fx.move_clock(api, _AFTER_FLIGHT)
    linear_periods = (
        ("2026-11-01T00:00:00Z", "2026-11-30T23:59:59Z", 20_000_000, 18_000_000),
        ("2026-12-01T00:00:00Z", "2026-12-31T23:59:59Z", 21_000_000, 19_200_000),
    )
    for period_start, period_end, gross, demo in linear_periods:
        report = fx.file_report(
            api,
            world["linear_buy_id"],
            gross,
            demo,
            seller_id=world["seller_id"],
            measurement_basis="LINEAR_C3",
            period_start=period_start,
            period_end=period_end,
        )
        fx.accept_report(api, report["id"])
    digital_report = fx.file_report(
        api,
        world["digital_buy_id"],
        26_000_000,
        24_000_000,
        measurement_basis="DIGITAL_VAST",
        period_start="2026-11-01T00:00:00Z",
        period_end="2026-12-31T23:59:59Z",
    )
    fx.accept_report(api, digital_report["id"])
    return world


def _sequential_run(api, campaign_id):
    """One SEQUENTIAL_DEDUP run carrying all three pairwise duplication estimates."""
    return validate_success(
        api.create_reconciliation_run(
            fa.sequential_dedup_payload(
                campaign_id,
                linear_ctv_duplication_pct=10.00,
                ctv_digital_duplication_pct=15.00,
                linear_digital_duplication_pct=30.00,
            ),
            PLANNER_HEADERS,
        ),
        201,
    )


def _aggregate_run(api, campaign_id):
    """One AGGREGATE_DEDUP run carrying the single blanket duplication estimate."""
    return validate_success(
        api.create_reconciliation_run(
            fa.aggregate_dedup_payload(campaign_id, aggregate_duplication_pct=20.00),
            PLANNER_HEADERS,
        ),
        201,
    )


class TestSequentialVersusAggregateDedup:
    """Two deduplication methods over one identical body of accepted delivery."""

    def test_both_buys_carry_only_their_accepted_demo_credit(self, api):
        """The linear buy's two accepted reports credit 37,200,000 demo impressions
        while the digital buy's single accepted report credits its whole 24,000,000
        guarantee, for a final index of 1.0000.

        PRD: "The **final** view is the settlement number:
        `credited_impressions_final` is the sum of `delivered_demo_impressions` over
        the buy's reports whose `status` is exactly `ACCEPTED`, and
        `final_delivery_index` is that credit divided by `guaranteed_impressions`,
        likewise rounded half up to four decimal places and likewise 0.0000 when the
        guarantee is 0."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        linear = validate_success(api.get_buy(world["linear_buy_id"], BUYER_HEADERS), 200)
        digital = validate_success(
            api.get_buy(world["digital_buy_id"], BUYER_HEADERS), 200
        )

        assert_impressions(linear, "credited_impressions_final", 37_200_000)
        assert_impressions(digital, "credited_impressions_final", 24_000_000)
        assert_pct4(digital, "final_delivery_index", 1.0000)

    def test_the_run_counts_every_accepted_report_of_the_campaign(self, api):
        """All three accepted reports across the two placed buys enter the run, which
        completes with data.

        PRD: "`included_report_count` is the number of delivery reports with `status`
        `ACCEPTED` belonging to the in-scope buys."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        run = _sequential_run(api, world["campaign_id"])

        assert run["status"] == "COMPLETED", (
            f"a run with accepted delivery must read COMPLETED, got {run['status']}"
        )
        assert run["included_report_count"] == 3, (
            f"expected 3 included reports, got {run['included_report_count']}"
        )

    def test_each_present_group_reaches_its_own_share_of_the_universe(self, api):
        """Against a 120,000,000 person universe and a frequency goal of 4.0, the linear
        group reaches 7.7500 percent and the digital group 5.0000 percent.

        PRD: "For each group the run sums `credited_impressions_final` over the
        in-scope buys of that group, converts that to rating points by dividing by
        the campaign's universe in people — `universe_thousands` multiplied by 1000 —
        and multiplying by 100, then divides those rating points by the campaign's
        `frequency_goal` and rounds half up to four decimal places."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        run = _sequential_run(api, world["campaign_id"])
        groups = run["group_reach_pct"]

        assert_pct4(groups, "LINEAR", 7.7500)
        assert_pct4(groups, "DIGITAL", 5.0000)

    def test_gross_reach_sums_the_present_groups_under_either_method(self, api):
        """Both runs read the same 12.7500 percent gross reach, because the sum of the
        present groups is taken before any deduplication.

        PRD: "`gross_reach_pct_total` is the sum of the present groups' reach
        percentages, rounded half up to four decimal places."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        sequential = _sequential_run(api, world["campaign_id"])
        aggregate = _aggregate_run(api, world["campaign_id"])

        assert_pct4(sequential, "gross_reach_pct_total", 12.7500)
        assert_pct4(aggregate, "gross_reach_pct_total", 12.7500)

    def test_sequential_dedup_walks_the_linear_to_digital_pair(self, api):
        """With CTV absent, the ladder starts at the linear 7.7500 and adds the digital
        5.0000 discounted by the 30.00 percent linear-to-digital duplication, giving
        11.2500 percent unduplicated reach.

        PRD: "Under `SEQUENTIAL_DEDUP` the system walks the present groups in the
        fixed group order and builds a pairwise ladder: `unduplicated_reach_pct`
        starts at the first present group's reach percentage, and each later present
        group contributes its own reach percentage multiplied by one minus the
        pairwise duplication between it and the previous present group divided by
        100."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        run = _sequential_run(api, world["campaign_id"])

        assert run["dedup_method"] == "SEQUENTIAL_DEDUP", (
            f"the run must record its method, got {run['dedup_method']}"
        )
        assert_pct4(run, "unduplicated_reach_pct", 11.2500)

    def test_aggregate_dedup_applies_one_blanket_factor(self, api):
        """The blanket 20.00 percent estimate discounts the whole 12.7500 percent gross
        reach to 10.2000 percent, ignoring the pairwise estimates entirely.

        PRD: "Under `AGGREGATE_DEDUP` one blanket overlap factor is applied instead:
        `unduplicated_reach_pct` is `gross_reach_pct_total` multiplied by one minus
        `aggregate_duplication_pct` divided by 100, rounded half up to four decimal
        places, and the three pairwise inputs are ignored entirely."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        run = _aggregate_run(api, world["campaign_id"])

        assert run["dedup_method"] == "AGGREGATE_DEDUP", (
            f"the run must record its method, got {run['dedup_method']}"
        )
        assert_pct4(run, "unduplicated_reach_pct", 10.2000)

    def test_the_two_methods_imply_different_frequencies(self, api):
        """The same 12.7500 percent gross reach over two different unduplicated figures
        implies 1.13 exposures under the sequential method and 1.25 under the
        aggregate one.

        PRD: "In both cases `unduplicated_reach_pct` is capped at 100.0000, and
        `implied_frequency` is `gross_reach_pct_total` divided by
        `unduplicated_reach_pct`, rounded half up to two decimal places, reading 0.00
        when the unduplicated figure is 0."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        sequential = _sequential_run(api, world["campaign_id"])
        aggregate = _aggregate_run(api, world["campaign_id"])

        assert_pct2(sequential, "implied_frequency", 1.13)
        assert_pct2(aggregate, "implied_frequency", 1.25)

    def test_the_methods_diverge_on_identical_input_data(self, api):
        """Read over exactly the same three accepted reports, the sequential run's
        unduplicated reach stands 1.0500 points above the aggregate run's.

        PRD: "Identical delivery data therefore yields a different unduplicated
        reach, and a different implied frequency, under the two methods — which is
        exactly why the method is recorded on the run."

        Design: Difficulty/dual_variant_calc/sequential_vs_aggregate_dedup_diverge_on_same_delivery
        """
        world = _delivered_two_channel_world(api)

        sequential = _sequential_run(api, world["campaign_id"])
        aggregate = _aggregate_run(api, world["campaign_id"])

        assert sequential["included_report_count"] == aggregate["included_report_count"], (
            "both runs must read the same body of accepted reports"
        )
        gap = pct4(
            dec(sequential["unduplicated_reach_pct"])
            - dec(aggregate["unduplicated_reach_pct"])
        )
        assert gap == 1.0500, (
            f"expected a 1.0500 point gap between the two methods, got {gap}"
        )
