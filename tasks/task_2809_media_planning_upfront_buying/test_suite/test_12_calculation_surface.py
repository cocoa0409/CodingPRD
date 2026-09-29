"""Corner cases of the domain's calculation surface.

Covers the planning CPM band clamps, the floored budget split and its residue,
the four-decimal delivery indices and their two input sets, the invoice's aired
line filter and the reconciliation run's accepted-report-only input set.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    PLANNER_HEADERS,
    assert_cents,
    assert_impressions,
    assert_pct2,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    make_seller_rep_headers,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# The payload literals the design's pinned figures were computed from
# --------------------------------------------------------------------------
ADVERTISER = {
    "name": "Cascadia Beverage",
    "category_code": "BEVERAGE",
    "credit_limit_cents": 500_000_000,
    "payment_terms_days": 30,
    "sequential_liability_enabled": True,
}

SELLER = {
    "name": "Harbor Broadcasting",
    "platform_types": ["LINEAR", "CTV", "DIGITAL"],
    "make_good_capacity_impressions": 50_000_000,
}

CAMPAIGN = {
    "name": "Q4 Linear Base",
    "target_demo": "A25-54",
    "universe_thousands": 120_000,
    "reach_goal_pct": 60.0,
    "frequency_goal": 4.0,
    "total_budget_cents": 10_000_000,
    "flight_start": "2026-11-01T00:00:00Z",
    "flight_end": "2026-12-31T23:59:59Z",
    "fiscal_quarter": "2026Q4",
}

LINEAR_ALLOCATION = {
    "channel": "LINEAR_TV",
    "allocation_pct": 100.00,
    "planned_cpm_cents": 2000,
    "planned_market": "UPFRONT",
    "primary_daypart": "PRIME",
}

AVAIL = {
    "market": "UPFRONT",
    "fiscal_quarter": "2026Q4",
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "window_start": "2026-11-01T00:00:00Z",
    "window_end": "2026-12-31T23:59:59Z",
    "total_impressions": 10_000_000,
    "forecast_cpm_cents": 2200,
    "exclusivity_mode": "SHARED",
}

NEGOTIATION = {
    "market": "UPFRONT",
    "channel": "LINEAR_TV",
    "requested_impressions": 1_000_000,
    "opening_cpm_cents": 2000,
    "guarantee_pct": 100,
    "make_good_provision": "MAKE_GOOD_UNITS",
    "option_pct_ceiling": 25,
}

COUNTER_CPM_CENTS = 2200
COUNTER_IMPRESSIONS = 1_000_000

NOVEMBER_UNIT = {
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "units": 1,
    "unit_rate_cents": 2_200_000,
    "projected_impressions": 1_000_000,
    "air_window_start": "2026-11-02T00:00:00Z",
    "air_window_end": "2026-11-30T23:59:59Z",
    "exclusive": False,
}

DECEMBER_UNIT = {
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "units": 1,
    "unit_rate_cents": 1_100_000,
    "projected_impressions": 500_000,
    "air_window_start": "2026-12-01T00:00:00Z",
    "air_window_end": "2026-12-15T23:59:59Z",
    "exclusive": False,
}

#: The November reporting period, which closes before the flight does.
REPORT_PERIOD_START = "2026-11-01T00:00:00Z"
REPORT_PERIOD_END = "2026-11-30T23:59:59Z"

#: The instant the November air window and reporting period have both closed.
AFTER_NOVEMBER = "2026-12-01T00:00:00Z"


# --------------------------------------------------------------------------
# Shared setup
# --------------------------------------------------------------------------
def _planning_shell(api, **campaign_overrides):
    """One advertiser and one DRAFT campaign carrying the brand objective."""
    spec = dict(CAMPAIGN)
    spec.update(campaign_overrides)
    advertiser = fx.register_advertiser(api, **ADVERTISER)
    campaign = fx.open_campaign(api, advertiser["id"], **spec)
    return {
        "advertiser_id": advertiser["id"],
        "campaign_id": campaign["id"],
    }


def _placed_linear_buy(api, unit_specs=None):
    """A PLACED LINEAR_TV buy guaranteeing 1,000,000 impressions at 2200 CPM."""
    advertiser = fx.register_advertiser(api, **ADVERTISER)
    seller = fx.register_seller(api, **SELLER)
    campaign = fx.open_campaign(api, advertiser["id"], **CAMPAIGN)
    allocation = fx.add_allocation(api, campaign["id"], **LINEAR_ALLOCATION)
    fx.submit_plan(api, campaign["id"])
    fx.approve_plan(api, campaign["id"], advertiser["id"])
    avail = fx.file_avail(api, seller["id"], **AVAIL)
    fx.publish_avail(api, avail["id"], seller["id"])
    negotiation = fx.open_negotiation(
        api, campaign["id"], seller["id"], allocation["id"], **NEGOTIATION
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=COUNTER_CPM_CENTS,
        counter_impressions=COUNTER_IMPRESSIONS,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    units = [
        fx.add_unit(api, buy["id"], avail["id"], **spec)
        for spec in (unit_specs if unit_specs is not None else [NOVEMBER_UNIT])
    ]
    fx.place_buy(api, buy["id"], campaign["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "seller_headers": make_seller_rep_headers(seller["id"]),
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "negotiation_id": negotiation["id"],
        "buy_id": buy["id"],
        "units": units,
        "unit_id": units[0]["id"],
    }


def _read_buy(api, buy_id):
    """A strictly validated fresh copy of the buy."""
    return validate_success(api.get_buy(buy_id, BUYER_HEADERS))


class TestPlannedProjectionClampsToBandCeiling:
    """The absolute ceiling of 12,000 cents wins over the raw adjusted CPM."""

    def test_scatter_prime_cpm_is_lowered_to_the_absolute_ceiling(self, api):
        """A 10,000 cent SCATTER PRIME line whose raw adjusted CPM is 16,200 stores
        an effective CPM of exactly 12,000 and projects 833,333 impressions.

        PRD: "That raw product is then clamped into a band anchored on the
        planner's own number: the band floor is the larger of an absolute floor
        of 200 cents per thousand and 60 percent of `planned_cpm_cents` rounded
        half up to a whole cent, and the band ceiling is the smaller of an
        absolute ceiling of 12,000 cents per thousand and 250 percent of
        `planned_cpm_cents` rounded half up to a whole cent."

        Design: Corner/calculations/planned_projection_clamps_the_cpm_to_the_band_ceiling
        """
        world = _planning_shell(api)

        response = api.create_channel_allocation(
            fa.channel_allocation_payload(
                world["campaign_id"],
                channel="LINEAR_TV",
                allocation_pct=100.00,
                planned_cpm_cents=10000,
                planned_market="SCATTER",
                primary_daypart="PRIME",
            ),
            PLANNER_HEADERS,
        )
        allocation = validate_success(response, 201)

        assert_cents(allocation, "allocated_cents", 10_000_000)
        assert_cents(allocation, "effective_planned_cpm_cents", 12000)
        assert_impressions(allocation, "planned_impressions", 833_333)
        assert_pct2(allocation, "planned_grp", 0.69)
        assert_pct2(allocation, "planned_frequency", 0.01)

        campaign = validate_success(
            api.get_campaign(world["campaign_id"], PLANNER_HEADERS)
        )
        assert_impressions(campaign, "planned_impressions_total", 833_333)
        assert_pct2(campaign, "planned_grp_total", 0.69)


class TestPlannedProjectionLiftsToAbsoluteFloor:
    """The absolute floor of 200 cents beats both the raw product and the
    weaker relative floor."""

    def test_upfront_late_cpm_is_raised_to_the_absolute_floor(self, api):
        """A 250 cent UPFRONT LATE line whose raw adjusted CPM is 175 stores an
        effective CPM of exactly 200 and projects 50,000,000 impressions.

        PRD: "The stored `effective_planned_cpm_cents` is the raw product
        rounded half up to a whole cent, raised to the band floor if it sits
        below it, then lowered to the band ceiling if it sits above it — that
        is, the ceiling has the final word when the two clamps disagree."

        Design: Corner/calculations/planned_projection_lifts_the_cpm_to_the_absolute_floor
        """
        world = _planning_shell(api)

        response = api.create_channel_allocation(
            fa.channel_allocation_payload(
                world["campaign_id"],
                channel="AUDIO",
                allocation_pct=100.00,
                planned_cpm_cents=250,
                planned_market="UPFRONT",
                primary_daypart="LATE",
            ),
            PLANNER_HEADERS,
        )
        allocation = validate_success(response, 201)

        assert_cents(allocation, "effective_planned_cpm_cents", 200)
        assert_impressions(allocation, "planned_impressions", 50_000_000)
        assert_pct2(allocation, "planned_grp", 41.67)
        assert_pct2(allocation, "planned_frequency", 0.69)


class TestAllocationBudgetSplitLeavesResidue:
    """Three independently floored shares of an odd budget leave one cent
    unallocated even though the percentages sum to exactly 100.00."""

    def test_three_floored_shares_leave_exactly_one_cent_unallocated(self, api):
        """33.33, 33.33 and 33.34 percent of 100,000,001 cents floor to
        33,330,000, 33,330,000 and 33,340,000, leaving a residue of 1 cent.

        PRD: "The allocation's own `allocated_cents` is the campaign's
        `total_budget_cents` multiplied by its `allocation_pct`, divided by 100,
        and then floored to a whole number of cents — never rounded up, because
        the agency will not allocate a cent it does not have."

        Design: Corner/calculations/allocation_budget_split_floors_each_share_and_leaves_a_residue
        """
        world = _planning_shell(
            api, name="Residue Split Q4", total_budget_cents=100_000_001
        )

        shares = [
            ("LINEAR_TV", 33.33),
            ("CTV", 33.33),
            ("DIGITAL_VIDEO", 33.34),
        ]
        allocations = []
        for channel, pct in shares:
            response = api.create_channel_allocation(
                fa.channel_allocation_payload(
                    world["campaign_id"],
                    channel=channel,
                    allocation_pct=pct,
                    planned_cpm_cents=1000,
                    planned_market="UPFRONT",
                    primary_daypart="DIGITAL_ANY",
                ),
                PLANNER_HEADERS,
            )
            allocations.append(validate_success(response, 201))

        first, second, third = allocations
        assert_cents(first, "allocated_cents", 33_330_000)
        assert_cents(second, "allocated_cents", 33_330_000)
        assert_cents(third, "allocated_cents", 33_340_000)
        for row in allocations:
            assert_cents(row, "effective_planned_cpm_cents", 1000)
        assert_impressions(first, "planned_impressions", 33_330_000)
        assert_impressions(third, "planned_impressions", 33_340_000)
        assert_pct2(first, "planned_grp", 27.78)
        assert_pct2(third, "planned_grp", 27.78)

        campaign = validate_success(
            api.get_campaign(world["campaign_id"], PLANNER_HEADERS)
        )
        assert_cents(campaign, "allocated_budget_cents", 100_000_000)
        assert_cents(campaign, "unallocated_budget_cents", 1)
        assert_impressions(campaign, "planned_impressions_total", 100_000_000)
        assert_pct2(campaign, "planned_grp_total", 83.34)


class TestFinalDeliveryIndexKeepsFourDecimals:
    """A repeating quotient is stored at four decimals, half up."""

    def test_repeating_quotient_is_stored_as_four_decimals(self, api):
        """Accepting a report of 1,000,000 gross and 666,667 demo impressions
        against a 1,000,000 guarantee leaves a final index of 0.6667 beside a
        provisional index of 1.0000.

        PRD: "The **final** view is the settlement number:
        `credited_impressions_final` is the sum of `delivered_demo_impressions`
        over the buy's reports whose `status` is exactly `ACCEPTED`, and
        `final_delivery_index` is that credit divided by
        `guaranteed_impressions`, likewise rounded half up to four decimal
        places and likewise 0.0000 when the guarantee is 0."

        Design: Corner/calculations/final_delivery_index_keeps_four_decimals_on_a_repeating_quotient
        """
        world = _placed_linear_buy(api)
        fx.move_clock(api, AFTER_NOVEMBER)
        report = fx.file_report(
            api,
            world["buy_id"],
            1_000_000,
            666_667,
            seller_id=world["seller_id"],
            measurement_basis="LINEAR_C3",
            period_start=REPORT_PERIOD_START,
            period_end=REPORT_PERIOD_END,
        )

        accepted = validate_success(
            api.accept_delivery_report(report["id"], None, BUYER_HEADERS), 200
        )
        assert accepted["status"] == "ACCEPTED", accepted["status"]

        buy = _read_buy(api, world["buy_id"])
        assert_impressions(buy, "credited_impressions_final", 666_667)
        assert_pct4(buy, "final_delivery_index", 0.6667)
        assert_impressions(buy, "credited_impressions_provisional", 1_000_000)
        assert_pct4(buy, "provisional_delivery_index", 1.0000)
        assert buy["stewardship_status"] == "ON_TRACK", buy["stewardship_status"]

        _rows, meta = validate_paginated(
            api.list_make_goods(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert meta["total_count"] == 0, meta["total_count"]


class TestProvisionalIndexIsWrittenAtSubmission:
    """Submission moves the provisional pair while the final pair waits for an
    acceptance that has not happened."""

    def test_submission_moves_only_the_provisional_pair(self, api):
        """Filing an unvetted SUBMITTED report of 1,000,000 gross impressions
        lifts the provisional index to 1.0000 while the final index stays at
        0.0000 and stewardship stays NOT_STARTED.

        PRD: "The **provisional** view is the in-flight stewardship number:
        `credited_impressions_provisional` is the sum of `delivered_impressions`
        over the buy's reports whose `status` is `SUBMITTED` or `ACCEPTED`, so
        unvetted seller claims count toward it, and `provisional_delivery_index`
        is that credit divided by the buy's `guaranteed_impressions`, rounded
        half up to four decimal places, reading 0.0000 when
        `guaranteed_impressions` is 0."

        Design: Corner/calculations/provisional_index_is_written_at_submission_while_final_waits_for_acceptance
        """
        world = _placed_linear_buy(api)
        fx.move_clock(api, AFTER_NOVEMBER)

        response = api.create_delivery_report(
            fa.delivery_report_payload(
                world["buy_id"],
                1_000_000,
                600_000,
                period_start=REPORT_PERIOD_START,
                period_end=REPORT_PERIOD_END,
                measurement_basis="LINEAR_C3",
            ),
            world["seller_headers"],
        )
        report = validate_success(response, 201)
        assert report["status"] == "SUBMITTED", report["status"]
        assert report["is_post_buy_final"] is False, report["is_post_buy_final"]

        buy = _read_buy(api, world["buy_id"])
        assert_impressions(buy, "credited_impressions_provisional", 1_000_000)
        assert_pct4(buy, "provisional_delivery_index", 1.0000)
        assert_impressions(buy, "credited_impressions_final", 0)
        assert_pct4(buy, "final_delivery_index", 0.0000)
        assert buy["buy_status"] == "PLACED", buy["buy_status"]
        assert buy["stewardship_status"] == "NOT_STARTED", buy["stewardship_status"]


class TestDisputeDropsReportFromProvisionalSet:
    """Disputing the only report is a recomputation over the filtered set, not
    a decrement of a running total."""

    def test_dispute_returns_the_provisional_credit_to_zero(self, api):
        """Disputing the buy's only SUBMITTED report drives
        credited_impressions_provisional back to 0 and the provisional index to
        0.0000.

        PRD: "Because a disputed report leaves the provisional input set, the
        buy's `credited_impressions_provisional` and `provisional_delivery_index`
        are recomputed downward; the final pair is unaffected, since a disputed
        report was never accepted."

        Design: Corner/calculations/disputing_a_report_drops_it_from_the_provisional_input_set
        """
        world = _placed_linear_buy(api)
        fx.move_clock(api, AFTER_NOVEMBER)
        report = fx.file_report(
            api,
            world["buy_id"],
            1_000_000,
            900_000,
            seller_id=world["seller_id"],
            measurement_basis="LINEAR_C3",
            period_start=REPORT_PERIOD_START,
            period_end=REPORT_PERIOD_END,
        )

        response = api.dispute_delivery_report(
            report["id"],
            fa.dispute_payload(dispute_reason="panel discrepancy on the demo break"),
            BUYER_HEADERS,
        )
        disputed = validate_success(response, 200)
        assert disputed["status"] == "DISPUTED", disputed["status"]

        buy = _read_buy(api, world["buy_id"])
        assert_impressions(buy, "credited_impressions_provisional", 0)
        assert_pct4(buy, "provisional_delivery_index", 0.0000)
        assert_impressions(buy, "credited_impressions_final", 0)
        assert_pct4(buy, "final_delivery_index", 0.0000)
        assert buy["buy_status"] == "PLACED", buy["buy_status"]

        _rows, meta = validate_paginated(
            api.list_delivery_reports(
                BUYER_HEADERS,
                params={"buy_id": world["buy_id"], "status": "SUBMITTED"},
            )
        )
        assert meta["total_count"] == 0, meta["total_count"]


class TestInvoiceBillsOnlyAiredUnitsInPeriod:
    """A still SCHEDULED December line contributes neither net nor commission
    to a November invoice."""

    def test_only_the_aired_november_line_is_billed(self, api):
        """With the November line AIRED and the December line still SCHEDULED,
        the November invoice carries one line of 2,200,000 cents net and
        2,354,000 cents net payable.

        PRD: "The invoice's lines are the buy's unit lines whose `status` is
        `AIRED` or `MAKE_GOOD_AIRED` and whose `air_window_end` falls inside the
        billing period inclusive of both endpoints, taken in order of
        `air_window_start` ascending with ties broken by `created_at` ascending."

        Design: Corner/calculations/invoice_bills_only_aired_units_inside_the_billing_period
        """
        world = _placed_linear_buy(
            api, unit_specs=[NOVEMBER_UNIT, DECEMBER_UNIT]
        )
        november_unit_id, december_unit_id = (
            world["units"][0]["id"],
            world["units"][1]["id"],
        )
        fx.move_clock(api, AFTER_NOVEMBER)
        fx.settle_aired(api, november_unit_id, world["seller_id"], 1_000_000)

        response = api.create_invoice(
            fa.invoice_payload(
                world["buy_id"],
                billing_period_start=REPORT_PERIOD_START,
                billing_period_end=REPORT_PERIOD_END,
            ),
            CONTROLLER_HEADERS,
        )
        invoice = validate_success(response, 201)

        assert invoice["line_count"] == 1, invoice["line_count"]
        assert_cents(invoice, "seller_payable_cents", 2_200_000)
        assert_cents(invoice, "agency_commission_cents", 154_000)
        assert_cents(invoice, "gross_billable_cents", 2_354_000)
        assert_cents(invoice, "make_good_credit_cents", 0)
        assert_cents(invoice, "net_payable_cents", 2_354_000)
        assert_cents(invoice, "max_remittable_cents", 0)
        assert invoice["client_status"] == "DRAFT", invoice["client_status"]
        assert invoice["seller_status"] == "UNREMITTED", invoice["seller_status"]

        december_unit = validate_success(
            api.get_buy_unit(december_unit_id, BUYER_HEADERS)
        )
        assert december_unit["status"] == "SCHEDULED", december_unit["status"]


class TestReconciliationOverOnlySubmittedReports:
    """The run's input set counts only ACCEPTED reports, so a SUBMITTED-only
    campaign short-circuits."""

    def test_run_completes_with_no_data(self, api):
        """A campaign whose single placed buy carries one still SUBMITTED report
        yields included_report_count 0, status COMPLETED_NO_DATA and every reach
        output 0.0000, while the buy's provisional index already reads 1.0000.

        PRD: "When `included_report_count` is 0 the run short-circuits: its
        `status` is `COMPLETED_NO_DATA`, every reach output — each group entry,
        `gross_reach_pct_total` and `unduplicated_reach_pct` — reads 0.0000, and
        `implied_frequency` reads 0.00."

        Design: Corner/calculations/reconciliation_over_only_submitted_reports_returns_completed_no_data
        """
        world = _placed_linear_buy(api)
        fx.move_clock(api, AFTER_NOVEMBER)
        fx.file_report(
            api,
            world["buy_id"],
            1_000_000,
            600_000,
            seller_id=world["seller_id"],
            measurement_basis="LINEAR_C3",
            period_start=REPORT_PERIOD_START,
            period_end=REPORT_PERIOD_END,
        )

        response = api.create_reconciliation_run(
            fa.sequential_dedup_payload(
                world["campaign_id"],
                linear_ctv_duplication_pct=15.00,
                ctv_digital_duplication_pct=20.00,
                linear_digital_duplication_pct=25.00,
            ),
            PLANNER_HEADERS,
        )
        run = validate_success(response, 201)

        assert run["status"] == "COMPLETED_NO_DATA", run["status"]
        assert run["included_report_count"] == 0, run["included_report_count"]
        assert_pct4(run, "gross_reach_pct_total", 0.0000)
        assert_pct4(run, "unduplicated_reach_pct", 0.0000)
        assert_pct2(run, "implied_frequency", 0.00)

        buy = _read_buy(api, world["buy_id"])
        assert_pct4(buy, "provisional_delivery_index", 1.0000)
