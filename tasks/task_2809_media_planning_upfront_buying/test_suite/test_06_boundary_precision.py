"""Boundary and precision edges of the upfront buying domain.

Two edges are pinned here: the post-buy make-good tolerance, where a shortfall of
exactly 2.0000 percent opens a make-good while 1.9000 percent does not, and the
sequential-liability release ceiling, where the pro-rata share is floored to a
whole cent so a single cent separates an accepted remittance from a refused one.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_ALT_USER_ID,
    ApiErrorId,
    assert_buy_axes,
    assert_cents,
    assert_impressions,
    assert_instant_field,
    assert_invoice_axes,
    assert_pagination_meta,
    assert_pct4,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

# ==========================================================================
# Instance 1 — shortfall_of_exactly_two_percent_requires_a_make_good
# ==========================================================================
#: The guarantee both buys of the tolerance-edge world carry.
GUARANTEED_IMPRESSIONS = 1_000_000

#: The price both buys settle on.
AGREED_CPM_CENTS = 2200


def _tolerance_edge_world(api):
    """Two identical million-impression buys reported 1,000 impressions apart.

    Both buys guarantee 1,000,000 impressions at CPM 2200 against the same
    seller and the same published avail.  The first carries a post-buy-final
    report of 980,000 demo impressions — a shortfall of exactly 2.0000 percent —
    and the second one of 981,000, which is 1.9000 percent.  Both reports are
    still ``SUBMITTED`` when the helper returns.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Sable Cosmetics",
        category_code="BEAUTY",
        credit_limit_cents=50_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Lakeshore Networks",
        platform_types=["LINEAR"],
        make_good_capacity_impressions=1_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Tolerance Edge Q4",
        target_demo="W18-49",
        universe_thousands=100_000,
        reach_goal_pct=30.0,
        frequency_goal=2.0,
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
    avail = fx.file_avail(
        api,
        seller["id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Lakeshore Eight",
        platform="LINEAR",
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-12-31T23:59:59Z",
        total_impressions=5_000_000,
        forecast_cpm_cents=2200,
        exclusivity_mode="SHARED",
    )
    fx.publish_avail(api, avail["id"], seller["id"])

    buy_ids = []
    for _ in range(2):
        negotiation = fx.open_negotiation(
            api,
            campaign["id"],
            seller["id"],
            allocation["id"],
            market="UPFRONT",
            channel="LINEAR_TV",
            requested_impressions=GUARANTEED_IMPRESSIONS,
            opening_cpm_cents=2100,
            guarantee_pct=100,
            make_good_provision="MAKE_GOOD_UNITS",
            option_pct_ceiling=25,
        )
        fx.counter(
            api,
            negotiation["id"],
            seller["id"],
            counter_cpm_cents=AGREED_CPM_CENTS,
            counter_impressions=GUARANTEED_IMPRESSIONS,
        )
        buy = fx.accept_negotiation(api, negotiation["id"])
        fx.add_unit(
            api,
            buy["id"],
            avail["id"],
            daypart="PRIME",
            program="Lakeshore Eight",
            platform="LINEAR",
            units=1,
            unit_rate_cents=2_200_000,
            projected_impressions=GUARANTEED_IMPRESSIONS,
            air_window_start="2026-11-02T00:00:00Z",
            air_window_end="2026-11-30T23:59:59Z",
        )
        fx.place_buy(api, buy["id"], campaign["id"])
        buy_ids.append(buy["id"])

    # The reported period ends at the flight end, so the clock has to have
    # reached it before either report may be filed.
    fx.move_clock(api, "2027-01-01T00:00:00Z")
    reports = [
        fx.file_report(
            api,
            buy_ids[index],
            1_000_000,
            demo_impressions,
            seller_id=seller["id"],
            measurement_basis="LINEAR_C3",
            period_start="2026-12-01T00:00:00Z",
            period_end="2026-12-31T23:59:59Z",
        )
        for index, demo_impressions in enumerate((980_000, 981_000))
    ]
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "forecast_id": avail["id"],
        "edge_buy_id": buy_ids[0],
        "tolerant_buy_id": buy_ids[1],
        "edge_report_id": reports[0]["id"],
        "tolerant_report_id": reports[1]["id"],
    }


def _accept_both_reports(api, world):
    """The trigger: the agency accepts each post-buy-final report in turn."""
    for report_id in (world["edge_report_id"], world["tolerant_report_id"]):
        validate_success(api.accept_delivery_report(report_id, None, BUYER_HEADERS), 200)


def _make_goods_of(api, buy_id):
    """The make-good page raised on one buy, with its pagination meta."""
    return validate_paginated(
        api.list_make_goods(BUYER_HEADERS, params={"buy_id": buy_id})
    )


class TestShortfallOfExactlyTwoPercentRequiresAMakeGood:
    """The make-good tolerance is a >= comparison at exactly 2.0000 percent."""

    def test_the_final_index_credits_only_the_accepted_demo_impressions(self, api):
        """Accepting 980,000 and 981,000 demo impressions against identical
        1,000,000 impression guarantees leaves final indices of 0.9800 and 0.9810.

        PRD: "The **final** view is the settlement number: `credited_impressions_final`
        is the sum of `delivered_demo_impressions` over the buy's reports whose
        `status` is exactly `ACCEPTED`, and `final_delivery_index` is that credit
        divided by `guaranteed_impressions`, likewise rounded half up to four decimal
        places and likewise 0.0000 when the guarantee is 0."

        Design: Difficulty/boundary_precision_check/shortfall_of_exactly_two_percent_requires_a_make_good
        """
        world = _tolerance_edge_world(api)
        _accept_both_reports(api, world)

        edge_buy = fx.read_buy(api, world["edge_buy_id"])
        tolerant_buy = fx.read_buy(api, world["tolerant_buy_id"])

        assert_impressions(edge_buy, "credited_impressions_final", 980_000)
        assert_pct4(edge_buy, "final_delivery_index", 0.9800)
        assert_impressions(tolerant_buy, "credited_impressions_final", 981_000)
        assert_pct4(tolerant_buy, "final_delivery_index", 0.9810)

    def test_a_shortfall_of_exactly_two_percent_opens_one_make_good(self, api):
        """A 20,000 impression shortfall on a 1,000,000 impression guarantee is
        exactly 2.0000 percent, so the buy under-delivers and one make-good opens.

        PRD: "If that percentage is at or above the make-good tolerance of 2.0000
        percent — a shortfall of exactly 2.0000 percent does require a make-good — the
        stewardship axis moves to `UNDER_DELIVERED`, arriving from `NOT_STARTED`,
        `ON_TRACK` or `AT_RISK` alike."

        Design: Difficulty/boundary_precision_check/shortfall_of_exactly_two_percent_requires_a_make_good
        """
        world = _tolerance_edge_world(api)
        _accept_both_reports(api, world)

        edge_buy = fx.read_buy(api, world["edge_buy_id"])
        assert_buy_axes(edge_buy, stewardship_status="UNDER_DELIVERED")

        rows, meta = _make_goods_of(api, world["edge_buy_id"])
        assert_pagination_meta(meta, expected_total=1)
        assert len(rows) == 1, f"expected one make-good row, got {len(rows)}"

    def test_a_shortfall_of_one_point_nine_percent_stays_within_tolerance(self, api):
        """A 19,000 impression shortfall is 1.9000 percent, so the buy lands on
        WITHIN_TOLERANCE with no make-good even though 19,000 impressions are owed.

        PRD: "If the percentage is strictly below the tolerance, the axis moves to
        `WITHIN_TOLERANCE` instead, again from any of those three origins, no make-good
        is created and the chain stops here."

        Design: Difficulty/boundary_precision_check/shortfall_of_exactly_two_percent_requires_a_make_good
        """
        world = _tolerance_edge_world(api)
        _accept_both_reports(api, world)

        tolerant_buy = fx.read_buy(api, world["tolerant_buy_id"])
        assert_buy_axes(tolerant_buy, stewardship_status="WITHIN_TOLERANCE")
        assert_impressions(tolerant_buy, "open_shortfall_impressions", 19_000)

        rows, meta = _make_goods_of(api, world["tolerant_buy_id"])
        assert_pagination_meta(meta, expected_total=0)
        assert rows == [], f"the tolerant buy must carry no make-good, got {rows}"

    def test_the_opened_make_good_freezes_and_values_the_shortfall(self, api):
        """The make-good freezes the buy's 20,000 open shortfall and values it at
        44,000 cents against the agreed CPM of 2200, starting at OPEN.

        PRD: "Its `shortfall_impressions` is frozen from the buy's
        `open_shortfall_impressions` at that moment, and its `shortfall_value_cents` is
        that frozen shortfall divided by 1000 and multiplied by the buy's
        `agreed_cpm_cents`, rounded half up to a whole cent."

        Design: Difficulty/boundary_precision_check/shortfall_of_exactly_two_percent_requires_a_make_good
        """
        world = _tolerance_edge_world(api)
        _accept_both_reports(api, world)

        edge_buy = fx.read_buy(api, world["edge_buy_id"])
        assert_impressions(edge_buy, "open_shortfall_impressions", 20_000)

        make_good = fx.only_make_good(api, world["edge_buy_id"])
        assert_impressions(make_good, "shortfall_impressions", 20_000)
        assert_cents(make_good, "shortfall_value_cents", 44_000)
        assert make_good["status"] == "OPEN", (
            f"a freshly created make-good is OPEN, got {make_good['status']}"
        )

    def test_only_the_under_delivered_buy_adds_to_the_seller_exposure(self, api):
        """The seller's open make-good exposure is 20,000 impressions: the tolerant
        buy owes 19,000 but opened no make-good, so it contributes nothing.

        PRD: "`open_make_good_impressions` is the sum of `shortfall_impressions` over
        make-goods on this seller's buys whose `status` is `OPEN` or `OFFERED`."

        Design: Difficulty/boundary_precision_check/shortfall_of_exactly_two_percent_requires_a_make_good
        """
        world = _tolerance_edge_world(api)
        _accept_both_reports(api, world)

        seller = fx.read_seller(api, world["seller_id"])
        assert_impressions(seller, "open_make_good_impressions", 20_000)
        assert_impressions(seller, "scheduled_make_good_impressions", 0)


# ==========================================================================
# Instance 2 — sequential_liability_cap_floors_the_pro_rata_share
# ==========================================================================
#: The three aired lines' net figures, and the rollups they sum to.
SELLER_PAYABLE_CENTS = 2_200_450
INVOICE_COMMISSION_CENTS = 154_033
GROSS_BILLABLE_CENTS = 2_354_483

#: No make-good was waived, so the client's bill is the whole gross billable.
NET_PAYABLE_CENTS = GROSS_BILLABLE_CENTS

#: The client cash that has actually arrived against that bill.
CLIENT_PAID_CENTS = 1_000_000

#: The pro-rata release share, 934,578.8438... cents, floored to a whole cent.
MAX_REMITTABLE_CENTS = 934_578


def _sequential_liability_world(api):
    """A part-paid invoice whose pro-rata release ceiling lands on a fraction.

    Three aired unit lines bill nets of 1,100,150 / 660,050 / 440,250 cents, so
    the invoice owes the seller 2,200,450 cents and bills the client 2,354,483.
    The client has paid 1,000,000 cents on time against 45-day terms, which puts
    the sequential-liability share at 934,578.8438... cents.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Torrent Fitness",
        category_code="FITNESS",
        credit_limit_cents=100_000_000,
        payment_terms_days=45,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Belmont Cable",
        platform_types=["LINEAR"],
        make_good_capacity_impressions=1_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="New Year Cut",
        target_demo="A18-49",
        universe_thousands=100_000,
        reach_goal_pct=35.0,
        frequency_goal=3.0,
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
    # Issuing the invoice requires the campaign to hold the cash it bills for.
    fx.fund_campaign(api, campaign["id"], advertiser["id"], 10_000_000)
    avail = fx.file_avail(
        api,
        seller["id"],
        market="SCATTER",
        fiscal_quarter="2026Q4",
        daypart="LATE",
        program="Belmont After Hours",
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

    line_specs = (
        (2, 550_075, 500_000, "2026-11-02T00:00:00Z", "2026-11-15T23:59:59Z"),
        (5, 132_010, 300_000, "2026-11-16T00:00:00Z", "2026-11-29T23:59:59Z"),
        (3, 146_750, 200_000, "2026-12-01T00:00:00Z", "2026-12-15T23:59:59Z"),
    )
    units = [
        fx.add_unit(
            api,
            buy["id"],
            avail["id"],
            daypart="LATE",
            program="Belmont After Hours",
            platform="LINEAR",
            units=count,
            unit_rate_cents=rate,
            projected_impressions=projected,
            air_window_start=window_start,
            air_window_end=window_end,
        )
        for count, rate, projected, window_start, window_end in line_specs
    ]
    fx.place_buy(api, buy["id"], campaign["id"])

    fx.move_clock(api, "2026-12-16T00:00:00Z")
    for unit, (_, _, projected, _, _) in zip(units, line_specs):
        fx.settle_aired(api, unit["id"], seller["id"], projected)

    invoice = fx.draft_invoice(
        api,
        buy["id"],
        billing_period_start="2026-11-01T00:00:00Z",
        billing_period_end="2026-12-31T23:59:59Z",
    )
    fx.issue_invoice(api, invoice["id"])
    fx.pay_invoice(api, invoice["id"], advertiser["id"], CLIENT_PAID_CENTS)
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "buy_id": buy["id"],
        "invoice_id": invoice["id"],
        "unit_ids": [unit["id"] for unit in units],
    }


class TestSequentialLiabilityCapFloorsTheProRataShare:
    """The release ceiling is floored, so one cent separates 200 from 422."""

    def test_the_pro_rata_release_ceiling_is_floored_to_a_whole_cent(self, api):
        """A 1,000,000 cent payment against a 2,354,483 cent bill with a 2,200,450
        cent payable puts the ceiling at 934,578, not the half-up 934,579.

        PRD: "**Sequential liability** means the agency never advances money the client
        has not paid, and it is expressed as a ceiling: when the advertiser's
        `sequential_liability_enabled` flag is true, `max_remittable_cents` is the
        smaller of the invoice's `seller_payable_cents` and the pro-rata share of the
        payable that the client's cash has funded — that is, `client_paid_cents`
        multiplied by `seller_payable_cents`, divided by `net_payable_cents`, and
        floored to a whole cent, because the agency will not advance even a fraction of
        a cent of its own money."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        invoice = fx.read_invoice(api, world["invoice_id"])
        assert_cents(invoice, "seller_payable_cents", SELLER_PAYABLE_CENTS)
        assert_cents(invoice, "net_payable_cents", NET_PAYABLE_CENTS)
        assert_cents(invoice, "client_paid_cents", CLIENT_PAID_CENTS)
        assert_cents(invoice, "max_remittable_cents", MAX_REMITTABLE_CENTS)

    def test_remitting_one_cent_above_the_ceiling_is_refused(self, api):
        """A release of 934,579 cents breaches the floored ceiling by a single cent
        and is refused, leaving the payable axis untouched.

        PRD: "And the release must respect both money ceilings: `seller_remitted_cents`
        plus `amount_cents` must be no greater than `max_remittable_cents` and no
        greater than `seller_payable_cents`, with a breach of either refused as
        `ERR_SEQUENTIAL_LIABILITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        response = api.remit_seller(
            world["invoice_id"],
            {"amount_cents": MAX_REMITTABLE_CENTS + 1},
            CONTROLLER_ALT_HEADERS,
        )
        validate_error(response, ApiErrorId.SEQUENTIAL_LIABILITY_EXCEEDED, 422)

        invoice = fx.read_invoice(api, world["invoice_id"])
        assert_cents(invoice, "seller_remitted_cents", 0)
        assert_invoice_axes(invoice, seller_status="UNREMITTED")

    def test_remitting_exactly_the_ceiling_records_the_release_and_its_approver(
        self, api
    ):
        """A release of exactly 934,578 cents succeeds and stamps the second
        controller as the approver of the payout.

        PRD: "Each accepted release increases `seller_remitted_cents` by `amount_cents`,
        records the acting `X-User-ID` as `approver_user_id`, and increments the
        invoice's `version` by 1."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        data = validate_success(
            api.remit_seller(
                world["invoice_id"],
                {"amount_cents": MAX_REMITTABLE_CENTS},
                CONTROLLER_ALT_HEADERS,
            ),
            200,
        )
        assert_cents(data, "seller_remitted_cents", MAX_REMITTABLE_CENTS)
        assert data["approver_user_id"] == CONTROLLER_ALT_USER_ID, (
            f"approver_user_id: expected {CONTROLLER_ALT_USER_ID}, "
            f"got {data['approver_user_id']!r}"
        )

    def test_the_accepted_release_leaves_the_payable_partially_remitted(self, api):
        """934,578 cents released against a 2,200,450 cent payable leaves the payable
        axis at PARTIALLY_REMITTED.

        PRD: "If `seller_remitted_cents` after the release remains strictly below
        `seller_payable_cents`, the payable axis sits at `PARTIALLY_REMITTED`, arriving
        from `UNREMITTED` on the first partial release and remaining there as a
        self-transition on subsequent ones."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        validate_success(
            api.remit_seller(
                world["invoice_id"],
                {"amount_cents": MAX_REMITTABLE_CENTS},
                CONTROLLER_ALT_HEADERS,
            ),
            200,
        )
        invoice = fx.read_invoice(api, world["invoice_id"])
        assert_invoice_axes(invoice, seller_status="PARTIALLY_REMITTED")
        assert_cents(invoice, "seller_payable_cents", SELLER_PAYABLE_CENTS)

    def test_the_invoice_falls_due_forty_five_days_after_issue(self, api):
        """Issued at 2026-12-16 against 45-day terms, the bill falls due on
        2027-01-30.

        PRD: "On success `issued_at` is stamped from the logical clock and `due_date` is
        set to `issued_at` advanced by the advertiser's `payment_terms_days` days —
        thirty days by default, which is why a client that never changed its terms sees
        a bill fall due one month after issue."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        invoice = fx.read_invoice(api, world["invoice_id"])
        assert_instant_field(invoice, "issued_at", "2026-12-16T00:00:00Z")
        assert_instant_field(invoice, "due_date", "2027-01-30T00:00:00Z")

    def test_a_payment_before_the_due_date_is_not_flagged_late(self, api):
        """The 1,000,000 cent payment lands at 2026-12-16, well inside the terms, so
        the invoice carries no late-payment flag and the client stays ACTIVE.

        PRD: "When the logical clock at the moment of payment reads strictly later than
        the invoice's `due_date`, the invoice's `late_payment_flag` is set to true, the
        advertiser's `late_payment_count` increases by 1, and the credit machine of
        §3.1 advances — `ACTIVE → WATCH` on the first such lateness, `WATCH → HOLD` on
        the second or any subsequent one."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        invoice = fx.read_invoice(api, world["invoice_id"])
        assert invoice["late_payment_flag"] is False, (
            f"late_payment_flag: expected False, got {invoice['late_payment_flag']!r}"
        )
        advertiser = fx.read_advertiser(api, world["advertiser_id"])
        assert advertiser["late_payment_count"] == 0, (
            f"late_payment_count: expected 0, got {advertiser['late_payment_count']}"
        )
        assert advertiser["credit_status"] == "ACTIVE", (
            f"credit_status: expected ACTIVE, got {advertiser['credit_status']}"
        )

    def test_the_part_payment_does_not_advance_the_billing_axis(self, api):
        """1,000,000 cents against a 2,354,483 cent bill leaves the receivable at
        PARTIALLY_PAID and the buy's billing axis still at INVOICED.

        PRD: "Where the receivable axis lands depends on one comparison: if
        `client_paid_cents` after the payment remains strictly below `net_payable_cents`,
        the axis sits at `PARTIALLY_PAID`, arriving there from `ISSUED` on the first part
        payment and remaining there as a self-transition on subsequent ones; if it
        reaches or exceeds `net_payable_cents`, the axis moves to `PAID` — from `ISSUED`
        when a single payment settles the bill, or from `PARTIALLY_PAID` after several —
        `max_remittable_cents` is recomputed to the full `seller_payable_cents`, and the
        buy's `settlement_status` cascades `INVOICED → CLIENT_PAID`."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        invoice = fx.read_invoice(api, world["invoice_id"])
        assert_invoice_axes(invoice, client_status="PARTIALLY_PAID")
        assert_buy_axes(fx.read_buy(api, world["buy_id"]), settlement_status="INVOICED")

    def test_the_period_bills_the_three_aired_lines_line_by_line(self, api):
        """The three aired lines roll up to a 2,200,450 cent payable and a 154,033
        cent commission, each line's commission having been rounded on the line.

        PRD: "The invoice then rolls those already-rounded line figures up: `line_count`
        is the number of lines; `seller_payable_cents` is the sum of the lines'
        `line_net_cents` and is the net media the agency owes the seller;
        `agency_commission_cents` is the sum of the lines' `line_commission_cents`; and
        `gross_billable_cents` is the sum of the lines' `line_gross_cents`."

        Design: Difficulty/boundary_precision_check/sequential_liability_cap_floors_the_pro_rata_share
        """
        world = _sequential_liability_world(api)

        invoice = fx.read_invoice(api, world["invoice_id"])
        assert invoice["line_count"] == 3, (
            f"line_count: expected 3, got {invoice['line_count']}"
        )
        assert_cents(invoice, "seller_payable_cents", SELLER_PAYABLE_CENTS)
        assert_cents(invoice, "agency_commission_cents", INVOICE_COMMISSION_CENTS)
        assert_cents(invoice, "gross_billable_cents", GROSS_BILLABLE_CENTS)
