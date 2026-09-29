"""Non-linear state machines of the upfront buying domain.

The file covers a negotiation that revisits `AGENCY_OFFER` and `SELLER_COUNTER`
three times each until the round cap gates the cycle edges while the exit hop to
`ACCEPTED` still fires, and one buy whose placement, stewardship and settlement
axes end at three different positions with closeout gated by the axis the
delivery side never advanced.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    BuyStatus,
    InvoiceClientStatus,
    NegotiationStatus,
    OfferActor,
    ReportStatus,
    SettlementStatus,
    StewardshipStatus,
    assert_buy_axes,
    assert_cents,
    assert_impressions,
    assert_instant_field,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    get_success_data,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    validate_error,
    validate_success,
)

# ==========================================================================
# Instance 1 — negotiation_cycles_five_times_then_hits_round_cap
# ==========================================================================
#: The seller counter left on the table once the sixth round has been consumed.
_CAPPED_CPM_CENTS = 2025
_CAPPED_IMPRESSIONS = 2_900_000

#: The declared maximum number of rounds one negotiation may accumulate.
_ROUND_CAP = 6

#: The cost stack those frozen terms imply: a pre-commission net media cost of
#: 5,872,500 cents sits in the middle commission tier at 0.0550.
_CAPPED_NET_MEDIA_COST_CENTS = 5_872_500
_CAPPED_COMMISSION_RATE = 0.0550
_CAPPED_COMMISSION_CENTS = 322_988
_CAPPED_GROSS_COST_CENTS = 6_195_488


def _negotiation_at_the_round_cap(api):
    """An APPROVED plan carrying a negotiation that has used all six rounds.

    The agency opens at 3,000,000 impressions and CPM 2000 against a single
    LOCKED linear allocation, and the parties then cycle counter, revise,
    counter, revise, counter.  Both `AGENCY_OFFER` and `SELLER_COUNTER` have been
    occupied three times each, `round_number` has reached 6, and the seller's
    2,900,000 impressions at CPM 2025 are the terms on the table.
    """
    advertiser = get_success_data(
        api.create_advertiser(
            fa.advertiser_payload(
                name="Solstice Retail",
                category_code="RETAIL",
                credit_limit_cents=80_000_000,
                payment_terms_days=30,
                sequential_liability_enabled=True,
            ),
            CONTROLLER_HEADERS,
        )
    )
    seller = get_success_data(
        api.create_seller(
            fa.seller_payload(
                name="Ridgeline Media",
                platform_types=["LINEAR"],
                make_good_capacity_impressions=4_000_000,
            ),
            CONTROLLER_HEADERS,
        )
    )
    seller_headers = make_seller_rep_headers(seller["id"])
    campaign = get_success_data(
        api.create_campaign(
            fa.campaign_payload(
                advertiser["id"],
                name="Holiday Cycle Test",
                target_demo="A18-49",
                universe_thousands=100_000,
                reach_goal_pct=45.0,
                frequency_goal=3.0,
                total_budget_cents=30_000_000,
                flight_start="2026-11-01T00:00:00Z",
                flight_end="2026-12-31T23:59:59Z",
                fiscal_quarter="2026Q4",
            ),
            PLANNER_HEADERS,
        )
    )
    allocation = get_success_data(
        api.create_channel_allocation(
            fa.channel_allocation_payload(
                campaign["id"],
                channel="LINEAR_TV",
                allocation_pct=100.00,
                planned_cpm_cents=2000,
                planned_market="UPFRONT",
                primary_daypart="PRIME",
            ),
            PLANNER_HEADERS,
        )
    )
    get_success_data(api.submit_plan(campaign["id"], None, PLANNER_HEADERS))
    get_success_data(
        api.approve_plan(
            campaign["id"], None, make_advertiser_client_headers(advertiser["id"])
        )
    )
    negotiation = get_success_data(
        api.create_negotiation(
            fa.negotiation_payload(
                campaign["id"],
                seller["id"],
                allocation["id"],
                market="UPFRONT",
                channel="LINEAR_TV",
                requested_impressions=3_000_000,
                opening_cpm_cents=2000,
                guarantee_pct=100,
                make_good_provision="MAKE_GOOD_UNITS",
                option_pct_ceiling=25,
            ),
            BUYER_HEADERS,
        )
    )
    current = get_success_data(
        api.counter_negotiation(
            negotiation["id"],
            fa.counter_payload(
                negotiation["version"],
                counter_cpm_cents=2100,
                counter_impressions=3_000_000,
            ),
            seller_headers,
        )
    )
    current = get_success_data(
        api.revise_negotiation(
            negotiation["id"],
            fa.revise_payload(offer_cpm_cents=1950, offer_impressions=3_000_000),
            BUYER_HEADERS,
        )
    )
    current = get_success_data(
        api.counter_negotiation(
            negotiation["id"],
            fa.counter_payload(
                current["version"],
                counter_cpm_cents=2050,
                counter_impressions=3_000_000,
            ),
            seller_headers,
        )
    )
    current = get_success_data(
        api.revise_negotiation(
            negotiation["id"],
            fa.revise_payload(offer_cpm_cents=2000, offer_impressions=2_900_000),
            BUYER_HEADERS,
        )
    )
    current = get_success_data(
        api.counter_negotiation(
            negotiation["id"],
            fa.counter_payload(
                current["version"],
                counter_cpm_cents=_CAPPED_CPM_CENTS,
                counter_impressions=_CAPPED_IMPRESSIONS,
            ),
            seller_headers,
        )
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "negotiation_id": negotiation["id"],
        "version_at_cap": current["version"],
    }


def _revise_past_the_cap(api, world):
    """The seventh move: the agency tries to revise once more."""
    return api.revise_negotiation(
        world["negotiation_id"],
        fa.revise_payload(offer_cpm_cents=1990, offer_impressions=_CAPPED_IMPRESSIONS),
        BUYER_HEADERS,
    )


def _accept_at_the_cap(api, world):
    """The exit hop, taken from the very same SELLER_COUNTER the cap refused."""
    validate_error(
        _revise_past_the_cap(api, world),
        ApiErrorId.NEGOTIATION_ROUND_CAP_REACHED,
        409,
    )
    return validate_success(
        api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS), 201
    )


class TestNegotiationCyclesFiveTimesThenHitsRoundCap:
    """The cyclic negotiation machine at the boundary where its cycle stops."""

    def test_seventh_move_is_refused_and_leaves_the_negotiation_untouched(self, api):
        """A sixth revision offered after five completed cycles is refused with
        ERR_NEGOTIATION_ROUND_CAP_REACHED, and the negotiation still shows round 6,
        an unchanged version, the seller's CPM 2025 at 2,900,000 impressions, and
        SELLER as the last offer actor.

        PRD: "No more than six rounds may accumulate on a negotiation: a counter or
        a revision whose effect would take `round_number` past 6 is refused with
        `ERR_NEGOTIATION_ROUND_CAP_REACHED`, so the sixth round can be reached but
        the seventh cannot."

        Design: Difficulty/non_linear_state_machine/negotiation_cycles_five_times_then_hits_round_cap
        """
        world = _negotiation_at_the_round_cap(api)

        validate_error(
            _revise_past_the_cap(api, world),
            ApiErrorId.NEGOTIATION_ROUND_CAP_REACHED,
            409,
        )

        negotiation = fx.read_negotiation(api, world["negotiation_id"])
        assert negotiation["round_number"] == _ROUND_CAP
        assert negotiation["version"] == world["version_at_cap"]
        assert negotiation["status"] == NegotiationStatus.SELLER_COUNTER
        assert negotiation["last_offer_actor"] == OfferActor.SELLER
        assert_cents(negotiation, "current_cpm_cents", _CAPPED_CPM_CENTS)
        assert_impressions(negotiation, "current_impressions", _CAPPED_IMPRESSIONS)

    def test_acceptance_still_fires_from_the_capped_seller_counter(self, api):
        """The exit hop out of the cycle is not gated by the round cap: acceptance
        of the refused-to-be-revised negotiation returns 201 and freezes the
        accepted terms at CPM 2025 on 2,900,000 impressions.

        PRD: "On the negotiation, `accepted_cpm_cents` takes the value of
        `current_cpm_cents` and `accepted_impressions` takes the value of
        `current_impressions`; both fields are null until this moment."

        Design: Difficulty/non_linear_state_machine/negotiation_cycles_five_times_then_hits_round_cap
        """
        world = _negotiation_at_the_round_cap(api)

        _accept_at_the_cap(api, world)

        negotiation = fx.read_negotiation(api, world["negotiation_id"])
        assert negotiation["status"] == NegotiationStatus.ACCEPTED
        assert_cents(negotiation, "accepted_cpm_cents", _CAPPED_CPM_CENTS)
        assert_impressions(negotiation, "accepted_impressions", _CAPPED_IMPRESSIONS)
        assert negotiation["round_number"] == _ROUND_CAP

    def test_capped_terms_drive_the_middle_commission_tier_on_the_buy(self, api):
        """The buy minted from the capped terms carries a pre-commission net media
        cost of 5,872,500 cents, which selects commission rate 0.0550, giving
        commission 322,988 cents and a gross cost of 6,195,488 cents.

        PRD: "From that pre-commission net figure — and never from any figure that
        already includes commission — the agency's `commission_rate` is selected on
        a three-tier schedule: 0.0700 while the net media cost is below 5,000,000
        cents (that is, below fifty thousand dollars); 0.0550 while it is at or
        above 5,000,000 cents and below 25,000,000 cents; and 0.0400 once it
        reaches 25,000,000 cents (two hundred and fifty thousand dollars) or more."

        Design: Difficulty/non_linear_state_machine/negotiation_cycles_five_times_then_hits_round_cap
        """
        world = _negotiation_at_the_round_cap(api)

        buy = _accept_at_the_cap(api, world)

        assert_cents(buy, "net_media_cost_cents", _CAPPED_NET_MEDIA_COST_CENTS)
        assert_pct4(buy, "commission_rate", _CAPPED_COMMISSION_RATE)
        assert_cents(buy, "agency_commission_cents", _CAPPED_COMMISSION_CENTS)
        assert_cents(buy, "gross_cost_cents", _CAPPED_GROSS_COST_CENTS)

    def test_new_buy_opens_all_three_axes_at_their_first_position(self, api):
        """However long the negotiation cycled, the buy it mints starts with
        placement PENDING_PLACEMENT, stewardship NOT_STARTED and settlement
        UNBILLED.

        PRD: "Its three axes start at `buy_status` `PENDING_PLACEMENT`,
        `stewardship_status` `NOT_STARTED` and `settlement_status` `UNBILLED`."

        Design: Difficulty/non_linear_state_machine/negotiation_cycles_five_times_then_hits_round_cap
        """
        world = _negotiation_at_the_round_cap(api)

        buy = _accept_at_the_cap(api, world)

        assert_buy_axes(
            buy,
            buy_status=BuyStatus.PENDING_PLACEMENT,
            stewardship_status=StewardshipStatus.NOT_STARTED,
            settlement_status=SettlementStatus.UNBILLED,
        )
        assert_cents(buy, "agreed_cpm_cents", _CAPPED_CPM_CENTS)
        assert_impressions(buy, "guaranteed_impressions", _CAPPED_IMPRESSIONS)


# ==========================================================================
# Instance 2 — buy_three_axes_advance_independently_and_gate_close
# ==========================================================================
#: The agreed terms of the placed buy.
_AXES_IMPRESSIONS = 40_000_000
_AXES_CPM_CENTS = 2200

#: Measured November delivery: gross above guarantee, target demo below it.
_AXES_DELIVERED_IMPRESSIONS = 41_000_000
_AXES_DEMO_IMPRESSIONS = 39_000_000
_AXES_PROVISIONAL_INDEX = 1.0250
_AXES_FINAL_INDEX = 0.9750

#: The one settled unit line and the invoice it rolls up into.
_AXES_LINE_NET_CENTS = 88_000_000
_AXES_LINE_COMMISSION_CENTS = 3_520_000
_AXES_LINE_GROSS_CENTS = 91_520_000

#: The instant the clock is standing at when the invoice is issued, and the day
#: it falls due on Beacon Foods' forty-five day terms.
_AXES_ISSUED_AT = "2026-12-01T00:00:00Z"
_AXES_DUE_DATE = "2027-01-15T00:00:00Z"


def _buy_with_three_axes_advanced(api):
    """A buy whose three axes have been moved by three unrelated triggers.

    Placement moved the placement axis, acceptance of one interim November report
    moved it again to `IN_FLIGHT` and moved stewardship to `ON_TRACK`, and the
    invoice raised afterwards moves settlement to `INVOICED`.  Nothing in the
    scenario ever advances stewardship past `ON_TRACK`.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Beacon Foods",
        category_code="GROCERY",
        credit_limit_cents=400_000_000,
        payment_terms_days=45,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Northgate Television",
        platform_types=["LINEAR"],
        make_good_capacity_impressions=20_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Pantry Push Q4",
        target_demo="A25-54",
        universe_thousands=120_000,
        reach_goal_pct=55.0,
        frequency_goal=4.0,
        total_budget_cents=200_000_000,
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
    # The design's call list omits funding, but the invoice cannot be issued
    # against an unfunded campaign, so the client deposits the whole budget.
    fx.fund_campaign(api, campaign["id"], advertiser["id"], 200_000_000)
    avail = fx.published_avail(
        api,
        seller["id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Northgate Nine",
        platform="LINEAR",
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-12-31T23:59:59Z",
        total_impressions=60_000_000,
        forecast_cpm_cents=2200,
        exclusivity_mode="SHARED",
    )
    negotiation = fx.open_negotiation(
        api,
        campaign["id"],
        seller["id"],
        allocation["id"],
        market="UPFRONT",
        channel="LINEAR_TV",
        requested_impressions=_AXES_IMPRESSIONS,
        opening_cpm_cents=2000,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=_AXES_CPM_CENTS,
        counter_impressions=_AXES_IMPRESSIONS,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    unit = fx.add_unit(
        api,
        buy["id"],
        avail["id"],
        daypart="PRIME",
        program="Northgate Nine",
        platform="LINEAR",
        units=40,
        unit_rate_cents=2_200_000,
        projected_impressions=_AXES_IMPRESSIONS,
        air_window_start="2026-11-02T00:00:00Z",
        air_window_end="2026-11-30T23:59:59Z",
    )
    fx.place_buy(api, buy["id"], campaign["id"])
    # The design advances the clock after report acceptance, but a report whose
    # period_end is in November cannot be filed while the clock still stands at
    # its startup instant, so the one clock move happens before the filing.
    fx.move_clock(api, _AXES_ISSUED_AT)
    report = fx.file_report(
        api,
        buy["id"],
        _AXES_DELIVERED_IMPRESSIONS,
        _AXES_DEMO_IMPRESSIONS,
        seller_id=seller["id"],
        measurement_basis="LINEAR_C3",
        period_start="2026-11-01T00:00:00Z",
        period_end="2026-11-30T23:59:59Z",
    )
    fx.accept_report(api, report["id"])
    fx.settle_aired(api, unit["id"], seller["id"], _AXES_DELIVERED_IMPRESSIONS)
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "buy_id": buy["id"],
        "unit_id": unit["id"],
        "report_id": report["id"],
    }


def _issue_invoice_for_november(api, world):
    """Draft and issue the November invoice, which moves the settlement axis."""
    invoice = fx.draft_invoice(
        api,
        world["buy_id"],
        billing_period_start="2026-11-01T00:00:00Z",
        billing_period_end="2026-11-30T23:59:59Z",
    )
    fx.issue_invoice(api, invoice["id"])
    return fx.read_invoice(api, invoice["id"])


def _attempt_close(api, world):
    """The segregated controller tries to close the buy out."""
    return api.close_buy(world["buy_id"], None, CONTROLLER_ALT_HEADERS)


class TestBuyThreeAxesAdvanceIndependentlyAndGateClose:
    """One buy carrying three axes at three positions, and the close it blocks."""

    def test_november_report_is_interim_and_accepted(self, api):
        """A report whose period ends a month before the flight does closes as an
        interim one: `is_post_buy_final` reads false and the report sits at
        ACCEPTED.

        PRD: "A filed report starts at `status` `SUBMITTED` with `dispute_reason`
        null, and the system computes `is_post_buy_final` for it at that moment:
        the flag reads true exactly when `period_end` is at or after the buy's
        `flight_end`, and it is that flag which makes a later acceptance run the
        post-buy shortfall evaluation."

        Design: Difficulty/non_linear_state_machine/buy_three_axes_advance_independently_and_gate_close
        """
        world = _buy_with_three_axes_advanced(api)

        report = fx.read_report(api, world["report_id"])
        assert report["is_post_buy_final"] is False
        assert report["status"] == ReportStatus.ACCEPTED

    def test_three_axes_settle_at_three_different_positions(self, api):
        """Placement, one accepted interim report and one issued invoice leave the
        buy at buy_status IN_FLIGHT, stewardship_status ON_TRACK and
        settlement_status INVOICED at the same time.

        PRD: "Three resources in this system carry more than one state field, and
        the axes advance independently of one another."

        Design: Difficulty/non_linear_state_machine/buy_three_axes_advance_independently_and_gate_close
        """
        world = _buy_with_three_axes_advanced(api)

        _issue_invoice_for_november(api, world)

        buy = fx.read_buy(api, world["buy_id"])
        assert_buy_axes(
            buy,
            buy_status=BuyStatus.IN_FLIGHT,
            stewardship_status=StewardshipStatus.ON_TRACK,
            settlement_status=SettlementStatus.INVOICED,
        )

    def test_the_two_delivery_indices_straddle_the_guarantee(self, api):
        """The one accepted report leaves the buy carrying a provisional index of
        1.0250 on its 41,000,000 gross impressions against a final index of 0.9750
        on the 39,000,000 that landed on the target demo.

        PRD: "Because the final view counts only accepted reports and only
        target-demo impressions, the same body of reports always yields a final
        index no higher than the provisional one — and it is the final view alone
        that drives stewardship state and make-good creation."

        Design: Difficulty/non_linear_state_machine/buy_three_axes_advance_independently_and_gate_close
        """
        world = _buy_with_three_axes_advanced(api)

        buy = fx.read_buy(api, world["buy_id"])
        assert_pct4(buy, "provisional_delivery_index", _AXES_PROVISIONAL_INDEX)
        assert_pct4(buy, "final_delivery_index", _AXES_FINAL_INDEX)
        assert_impressions(
            buy, "credited_impressions_provisional", _AXES_DELIVERED_IMPRESSIONS
        )
        assert_impressions(buy, "credited_impressions_final", _AXES_DEMO_IMPRESSIONS)

    def test_invoice_rolls_up_the_single_settled_line(self, api):
        """The November invoice covers one line only: seller payable 88,000,000
        cents, agency commission 3,520,000 cents and gross billable 91,520,000
        cents, with nothing credited so net payable equals the gross.

        PRD: "The invoice then rolls those already-rounded line figures up:
        `line_count` is the number of lines; `seller_payable_cents` is the sum of
        the lines' `line_net_cents` and is the net media the agency owes the
        seller; `agency_commission_cents` is the sum of the lines'
        `line_commission_cents`; and `gross_billable_cents` is the sum of the
        lines' `line_gross_cents`."

        Design: Difficulty/non_linear_state_machine/buy_three_axes_advance_independently_and_gate_close
        """
        world = _buy_with_three_axes_advanced(api)

        invoice = _issue_invoice_for_november(api, world)

        assert invoice["line_count"] == 1
        assert_cents(invoice, "seller_payable_cents", _AXES_LINE_NET_CENTS)
        assert_cents(invoice, "agency_commission_cents", _AXES_LINE_COMMISSION_CENTS)
        assert_cents(invoice, "gross_billable_cents", _AXES_LINE_GROSS_CENTS)
        assert_cents(invoice, "net_payable_cents", _AXES_LINE_GROSS_CENTS)

    def test_issue_stamps_the_clock_and_forty_five_day_terms(self, api):
        """Issuing the invoice moves it to ISSUED, stamps `issued_at` at the
        logical clock's 2026-12-01T00:00:00Z and sets `due_date` forty-five days
        later at 2027-01-15T00:00:00Z.

        PRD: "On success `issued_at` is stamped from the logical clock and
        `due_date` is set to `issued_at` advanced by the advertiser's
        `payment_terms_days` days — thirty days by default, which is why a client
        that never changed its terms sees a bill fall due one month after issue."

        Design: Difficulty/non_linear_state_machine/buy_three_axes_advance_independently_and_gate_close
        """
        world = _buy_with_three_axes_advanced(api)

        invoice = _issue_invoice_for_november(api, world)

        assert invoice["client_status"] == InvoiceClientStatus.ISSUED
        assert_instant_field(invoice, "issued_at", _AXES_ISSUED_AT)
        assert_instant_field(invoice, "due_date", _AXES_DUE_DATE)

    def test_close_is_refused_because_stewardship_never_left_on_track(self, api):
        """Closeout from the declared IN_FLIGHT from-state is still refused with
        ERR_BUY_NOT_IN_EXPECTED_STATE because stewardship stands at ON_TRACK, and
        the buy is left at IN_FLIGHT.

        PRD: "Two conditions must hold: the buy's `stewardship_status` must be
        `WITHIN_TOLERANCE` or `MADE_GOOD` — a buy still `NOT_STARTED`, `ON_TRACK`,
        `AT_RISK` or `UNDER_DELIVERED` is not settled — and no delivery report of
        the buy may still be sitting at `SUBMITTED`, since an unadjudicated report
        could still move the numbers."

        Design: Difficulty/non_linear_state_machine/buy_three_axes_advance_independently_and_gate_close
        """
        world = _buy_with_three_axes_advanced(api)
        _issue_invoice_for_november(api, world)

        validate_error(
            _attempt_close(api, world),
            ApiErrorId.BUY_NOT_IN_EXPECTED_STATE,
            409,
        )

        buy = fx.read_buy(api, world["buy_id"])
        assert buy["buy_status"] == BuyStatus.IN_FLIGHT
        assert buy["stewardship_status"] == StewardshipStatus.ON_TRACK
