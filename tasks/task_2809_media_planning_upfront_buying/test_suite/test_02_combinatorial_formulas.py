"""Combinatorial formula instances: the two places where the order in which the
cost arithmetic is applied changes the answer.

The invoice rollup rounds each line's commission before summing rather than
summing the nets and rounding once, and the commission tier is selected on the
pre-commission net media cost rather than on the gross the commission produces.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    assert_buy_axes,
    assert_cents,
    assert_invoice_axes,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    validate_success,
)


# ==========================================================================
# Difficulty/combinatorial_formula/invoice_commission_rounded_per_line_then_summed
# ==========================================================================
#: The three billable unit lines, in the order the design creates them.  Each
#: line's net lands exactly on a half cent once the 0.0700 rate is applied.
_BILLABLE_LINES = (
    {
        "units": 2,
        "unit_rate_cents": 550_075,
        "projected_impressions": 500_000,
        "air_window_start": "2026-11-02T00:00:00Z",
        "air_window_end": "2026-11-15T23:59:59Z",
    },
    {
        "units": 5,
        "unit_rate_cents": 132_010,
        "projected_impressions": 300_000,
        "air_window_start": "2026-11-16T00:00:00Z",
        "air_window_end": "2026-11-29T23:59:59Z",
    },
    {
        "units": 3,
        "unit_rate_cents": 146_750,
        "projected_impressions": 200_000,
        "air_window_start": "2026-12-01T00:00:00Z",
        "air_window_end": "2026-12-15T23:59:59Z",
    },
)


def _scatter_buy_with_three_aired_lines(api):
    """A placed SCATTER buy whose three lines have all aired and are billable.

    The guarantee of 1,000,000 impressions at CPM 2200 puts the buy's net media
    cost at 2,200,000 cents, which is inside the smallest commission tier, so
    every line is commissioned at 0.0700.  The logical clock is left at
    2026-12-16T00:00:00Z so all three air windows have elapsed.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Northwind Motors",
        category_code="AUTOMOTIVE",
        credit_limit_cents=100_000_000,
        payment_terms_days=45,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Cascade Cable",
        platform_types=["LINEAR", "CTV"],
        make_good_capacity_impressions=5_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Model Launch Scatter",
        target_demo="A18-49",
        universe_thousands=100_000,
        reach_goal_pct=40.00,
        frequency_goal=3.00,
        total_budget_cents=10_000_000,
        flight_start="2026-11-01T00:00:00Z",
        flight_end="2026-12-31T23:59:59Z",
        fiscal_quarter="2026Q4",
    )
    allocation = fx.add_allocation(
        api,
        campaign["id"],
        channel="LINEAR_TV",
        allocation_pct=100.00,
        planned_cpm_cents=2200,
        planned_market="SCATTER",
        primary_daypart="LATE",
    )
    fx.submit_plan(api, campaign["id"])
    fx.approve_plan(api, campaign["id"], advertiser["id"])
    avail = fx.file_avail(
        api,
        seller["id"],
        market="SCATTER",
        fiscal_quarter="2026Q4",
        daypart="LATE",
        program="Late Edition",
        platform="LINEAR",
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-12-31T23:59:59Z",
        total_impressions=3_000_000,
        forecast_cpm_cents=2300,
        exclusivity_mode="SHARED",
    )
    fx.publish_avail(api, avail["id"], seller["id"])
    negotiation = fx.open_negotiation(
        api,
        campaign["id"],
        seller["id"],
        allocation["id"],
        market="SCATTER",
        channel="LINEAR_TV",
        requested_impressions=1_000_000,
        opening_cpm_cents=2000,
        guarantee_pct=100,
        make_good_provision="CASH_CREDIT",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=2200,
        counter_impressions=1_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    units = [
        fx.add_unit(
            api,
            buy["id"],
            avail["id"],
            daypart="LATE",
            program="Late Edition",
            platform="LINEAR",
            **spec,
        )
        for spec in _BILLABLE_LINES
    ]
    fx.place_buy(api, buy["id"], campaign["id"])
    fx.move_clock(api, "2026-12-16T00:00:00Z")
    for unit, spec in zip(units, _BILLABLE_LINES):
        fx.settle_aired(
            api, unit["id"], seller["id"], spec["projected_impressions"]
        )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "buy_id": buy["id"],
        "unit_ids": [unit["id"] for unit in units],
    }


def _draft_period_invoice(api, buy_id, period_start, period_end):
    """Draft one invoice over the named billing period, as the controller."""
    return validate_success(
        api.create_invoice(
            fa.invoice_payload(
                buy_id,
                billing_period_start=period_start,
                billing_period_end=period_end,
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )


def _draft_both_invoices(api, buy_id):
    """The whole-flight invoice and then the November-only invoice."""
    whole_flight = _draft_period_invoice(
        api, buy_id, "2026-11-01T00:00:00Z", "2026-12-31T23:59:59Z"
    )
    november = _draft_period_invoice(
        api, buy_id, "2026-11-01T00:00:00Z", "2026-11-30T23:59:59Z"
    )
    return whole_flight, november


class TestInvoiceCommissionRoundedPerLineThenSummed:
    """The invoice commission is the sum of already-rounded per-line figures."""

    def test_each_line_rounds_its_own_half_cent_commission_up(self, api):
        """All three lines carry a net whose 0.0700 commission lands on a half
        cent, and each line rounds that half cent up on its own.

        PRD: "`line_commission_cents` is `line_net_cents` multiplied by the
        parent buy's `commission_rate`, rounded half up to a whole cent — the
        rounding happens on this line, in isolation, and this per-line rounding
        is what §3.9's invoice arithmetic later sums."

        Design: Difficulty/combinatorial_formula/invoice_commission_rounded_per_line_then_summed
        """
        world = _scatter_buy_with_three_aired_lines(api)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_pct4(buy, "commission_rate", 0.0700)

        expected = (
            {"net": 1_100_150, "commission": 77_011, "gross": 1_177_161},
            {"net": 660_050, "commission": 46_204, "gross": 706_254},
            {"net": 440_250, "commission": 30_818, "gross": 471_068},
        )
        for unit_id, figures in zip(world["unit_ids"], expected):
            line = validate_success(api.get_buy_unit(unit_id, BUYER_HEADERS))
            assert_cents(line, "line_net_cents", figures["net"])
            assert_cents(line, "line_commission_cents", figures["commission"])
            assert_cents(line, "line_gross_cents", figures["gross"])

    def test_whole_flight_invoice_sums_the_rounded_line_commissions(self, api):
        """The three-line invoice reports 154,033 cents of commission, not the
        154,032 that summing the nets and rounding once would produce.

        PRD: "Summing the raw line nets first and rounding the commission once at
        the end is explicitly not the required behaviour."

        Design: Difficulty/combinatorial_formula/invoice_commission_rounded_per_line_then_summed
        """
        world = _scatter_buy_with_three_aired_lines(api)

        whole_flight, _november = _draft_both_invoices(api, world["buy_id"])

        assert whole_flight["line_count"] == 3, (
            f"line_count: expected 3, got {whole_flight['line_count']}"
        )
        assert_cents(whole_flight, "seller_payable_cents", 2_200_450)
        assert_cents(whole_flight, "agency_commission_cents", 154_033)
        assert whole_flight["agency_commission_cents"] != 154_032, (
            "154,032 cents is the sum-then-round result and is not the contract"
        )
        assert_cents(whole_flight, "gross_billable_cents", 2_354_483)

    def test_whole_flight_invoice_bills_the_gross_with_no_credit(self, api):
        """With no waived make-good the whole-flight invoice bills its gross of
        2,354,483 cents in full, and it opens unissued and unremitted with
        nothing releasable to the seller.

        PRD: "Against that gross, `make_good_credit_cents` is the sum of
        `waived_credit_cents` over every make-good of the buy whose `status` is
        `WAIVED`, and `net_payable_cents` — the amount actually billed to the
        client — is `gross_billable_cents` less `make_good_credit_cents`, floored
        at 0 so a credit larger than the period's billing never produces a
        negative bill."

        Design: Difficulty/combinatorial_formula/invoice_commission_rounded_per_line_then_summed
        """
        world = _scatter_buy_with_three_aired_lines(api)

        whole_flight, _november = _draft_both_invoices(api, world["buy_id"])

        assert_cents(whole_flight, "make_good_credit_cents", 0)
        assert_cents(whole_flight, "net_payable_cents", 2_354_483)
        assert_cents(whole_flight, "max_remittable_cents", 0)
        assert_invoice_axes(
            whole_flight, client_status="DRAFT", seller_status="UNREMITTED"
        )

    def test_november_invoice_drops_the_december_line_and_still_rounds_per_line(
        self, api
    ):
        """The November-only period captures two of the three lines and reports
        123,215 cents of commission, one cent above the 123,214 that the
        sum-then-round order produces exactly.

        PRD: "The invoice's lines are the buy's unit lines whose `status` is
        `AIRED` or `MAKE_GOOD_AIRED` and whose `air_window_end` falls inside the
        billing period inclusive of both endpoints, taken in order of
        `air_window_start` ascending with ties broken by `created_at` ascending."

        Design: Difficulty/combinatorial_formula/invoice_commission_rounded_per_line_then_summed
        """
        world = _scatter_buy_with_three_aired_lines(api)

        _whole_flight, november = _draft_both_invoices(api, world["buy_id"])

        assert november["line_count"] == 2, (
            f"line_count: expected 2, got {november['line_count']}"
        )
        assert_cents(november, "seller_payable_cents", 1_760_200)
        assert_cents(november, "agency_commission_cents", 123_215)
        assert november["agency_commission_cents"] != 123_214, (
            "123,214 cents is the sum-then-round result and is not the contract"
        )
        assert_cents(november, "gross_billable_cents", 1_883_415)


# ==========================================================================
# Difficulty/combinatorial_formula/commission_tier_selected_on_pre_commission_net
# ==========================================================================
def _two_countered_negotiations_astride_the_mid_tier_floor(api):
    """One approved plan facing two seller counters that straddle the tier floor.

    Counter A settles 2,272,000 impressions at CPM 2200, a net of 4,998,400
    cents that sits just under the 5,000,000 cent mid-tier floor even though the
    gross it produces sits above it.  Counter B settles 2,500,000 impressions at
    CPM 2000, a net of exactly 5,000,000 cents, on the floor itself.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Meridian Bank",
        category_code="FINANCE",
        credit_limit_cents=50_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Summit Networks",
        platform_types=["LINEAR"],
        make_good_capacity_impressions=2_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Tier Probe Q4",
        target_demo="A25-54",
        universe_thousands=100_000,
        reach_goal_pct=50.00,
        frequency_goal=3.00,
        total_budget_cents=30_000_000,
        flight_start="2026-11-01T00:00:00Z",
        flight_end="2026-12-31T23:59:59Z",
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

    under_floor = fx.open_negotiation(
        api,
        campaign["id"],
        seller["id"],
        allocation["id"],
        market="UPFRONT",
        channel="LINEAR_TV",
        requested_impressions=2_272_000,
        opening_cpm_cents=2100,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        under_floor["id"],
        seller["id"],
        counter_cpm_cents=2200,
        counter_impressions=2_272_000,
    )
    on_floor = fx.open_negotiation(
        api,
        campaign["id"],
        seller["id"],
        allocation["id"],
        market="UPFRONT",
        channel="LINEAR_TV",
        requested_impressions=2_500_000,
        opening_cpm_cents=1900,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        on_floor["id"],
        seller["id"],
        counter_cpm_cents=2000,
        counter_impressions=2_500_000,
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "under_floor_negotiation_id": under_floor["id"],
        "on_floor_negotiation_id": on_floor["id"],
    }


def _accept_both_counters(api, world):
    """Accept both counters in the design's order, returning the two buys."""
    under_floor = validate_success(
        api.accept_negotiation(
            world["under_floor_negotiation_id"], None, BUYER_HEADERS
        ),
        201,
    )
    on_floor = validate_success(
        api.accept_negotiation(world["on_floor_negotiation_id"], None, BUYER_HEADERS),
        201,
    )
    return under_floor, on_floor


class TestCommissionTierSelectedOnPreCommissionNet:
    """The tier is chosen on the net, never on the gross that net produces."""

    def test_net_just_under_the_floor_keeps_the_small_tier_despite_its_gross(
        self, api
    ):
        """A net of 4,998,400 cents keeps the 0.0700 rate and earns 349,888 cents
        of commission, even though the gross of 5,348,288 cents it produces sits
        above the mid-tier floor.

        PRD: "From that pre-commission net figure — and never from any figure that
        already includes commission — the agency's `commission_rate` is selected
        on a three-tier schedule: 0.0700 while the net media cost is below
        5,000,000 cents (that is, below fifty thousand dollars); 0.0550 while it
        is at or above 5,000,000 cents and below 25,000,000 cents; and 0.0400 once
        it reaches 25,000,000 cents (two hundred and fifty thousand dollars) or
        more."

        Design: Difficulty/combinatorial_formula/commission_tier_selected_on_pre_commission_net
        """
        world = _two_countered_negotiations_astride_the_mid_tier_floor(api)

        under_floor, _on_floor = _accept_both_counters(api, world)

        buy = validate_success(api.get_buy(under_floor["id"], BUYER_HEADERS))
        assert buy["guaranteed_impressions"] == 2_272_000, (
            f"guaranteed_impressions: expected 2272000, "
            f"got {buy['guaranteed_impressions']}"
        )
        assert_cents(buy, "agreed_cpm_cents", 2200)
        assert_cents(buy, "net_media_cost_cents", 4_998_400)
        assert_pct4(buy, "commission_rate", 0.0700)
        assert_cents(buy, "agency_commission_cents", 349_888)
        assert_cents(buy, "gross_cost_cents", 5_348_288)
        assert buy["agency_commission_cents"] != 274_912, (
            "274,912 cents is what feeding the gross back into tier selection "
            "would produce and is not the contract"
        )

    def test_net_exactly_on_the_floor_takes_the_mid_tier_rate(self, api):
        """A net of exactly 5,000,000 cents takes the 0.0550 mid-tier rate,
        earning 275,000 cents of commission on a gross of 5,275,000 cents.

        PRD: "Both tier floors are inclusive, so a net media cost of exactly
        5,000,000 cents earns the middle rate and exactly 25,000,000 cents earns
        the lowest."

        Design: Difficulty/combinatorial_formula/commission_tier_selected_on_pre_commission_net
        """
        world = _two_countered_negotiations_astride_the_mid_tier_floor(api)

        _under_floor, on_floor = _accept_both_counters(api, world)

        buy = validate_success(api.get_buy(on_floor["id"], BUYER_HEADERS))
        assert_cents(buy, "net_media_cost_cents", 5_000_000)
        assert_pct4(buy, "commission_rate", 0.0550)
        assert_cents(buy, "agency_commission_cents", 275_000)
        assert_cents(buy, "gross_cost_cents", 5_275_000)

    def test_both_buys_carry_their_cost_stack_before_any_placement(self, api):
        """Acceptance alone computes both cost stacks: the two buys still sit at
        PENDING_PLACEMENT, unbilled and with stewardship not started.

        PRD: "Its three axes start at `buy_status` `PENDING_PLACEMENT`,
        `stewardship_status` `NOT_STARTED` and `settlement_status` `UNBILLED`."

        Design: Difficulty/combinatorial_formula/commission_tier_selected_on_pre_commission_net
        """
        world = _two_countered_negotiations_astride_the_mid_tier_floor(api)

        under_floor, on_floor = _accept_both_counters(api, world)

        for buy_id in (under_floor["id"], on_floor["id"]):
            buy = validate_success(api.get_buy(buy_id, BUYER_HEADERS))
            assert_buy_axes(
                buy,
                buy_status="PENDING_PLACEMENT",
                stewardship_status="NOT_STARTED",
                settlement_status="UNBILLED",
            )
