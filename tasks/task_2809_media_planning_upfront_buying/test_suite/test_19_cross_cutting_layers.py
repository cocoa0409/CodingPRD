"""The two version guards, the version-increment discipline they rest on, and
the advertiser receivable that has to reconcile across issue and payment."""

from test_helpers import (
    ApiErrorId,
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    NegotiationStatus,
    assert_cents,
    assert_instant_field,
    factories as fa,
    fixtures as fx,
    make_seller_rep_headers,
    validate_error,
    validate_success,
)

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

ALLOCATION = {
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

UNIT = {
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


def _open_negotiation(api):
    """One approved single-channel plan, one published avail and the agency's
    opening offer of 1,000,000 impressions at 2000 cents."""
    advertiser = fx.register_advertiser(api, **ADVERTISER)
    seller = fx.register_seller(api, **SELLER)
    campaign = fx.open_campaign(api, advertiser["id"], **CAMPAIGN)
    allocation = fx.add_allocation(api, campaign["id"], **ALLOCATION)
    fx.submit_plan(api, campaign["id"])
    fx.approve_plan(api, campaign["id"], advertiser["id"])
    avail = fx.published_avail(api, seller["id"], **AVAIL)
    negotiation = fx.open_negotiation(
        api, campaign["id"], seller["id"], allocation["id"], **NEGOTIATION
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "seller_headers": make_seller_rep_headers(seller["id"]),
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "negotiation": negotiation,
        "negotiation_id": negotiation["id"],
    }


def _cycled_to_round_three(api):
    """The negotiation above, countered by the seller and then revised by the
    agency, so the terms on the table are the agency's 2100 CPM at version 3."""
    world = _open_negotiation(api)
    first_version = world["negotiation"]["version"]
    fx.counter(
        api,
        world["negotiation_id"],
        world["seller_id"],
        counter_cpm_cents=2200,
        counter_impressions=1_000_000,
    )
    fx.revise(
        api, world["negotiation_id"], offer_cpm_cents=2100, offer_impressions=1_000_000
    )
    world["superseded_version"] = first_version
    return world


class TestStaleNegotiationVersion:
    def test_a_counter_quoting_the_superseded_version_is_refused_as_stale(self, api):
        """A negotiation that has moved twice since the seller read version 1
        refuses a counter still quoting that version, and refuses it as a
        precondition failure rather than a conflict.

        PRD: "If `expected_negotiation_version` does not equal the negotiation's
        current `version`, the request is rejected with
        `ERR_STALE_NEGOTIATION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_counter_carrying_the_superseded_negotiation_version_is_rejected
        """
        world = _cycled_to_round_three(api)

        response = api.counter_negotiation(
            world["negotiation_id"],
            fa.counter_payload(
                world["superseded_version"],
                counter_cpm_cents=2300,
                counter_impressions=1_000_000,
            ),
            world["seller_headers"],
        )

        validate_error(response, ApiErrorId.STALE_NEGOTIATION_VERSION, 412)

        after = fx.read_negotiation(api, world["negotiation_id"])
        assert after["version"] == 3
        assert after["round_number"] == 3
        assert after["status"] == NegotiationStatus.AGENCY_OFFER.value
        assert_cents(after, "current_cpm_cents", 2100)
        assert after["last_offer_actor"] == "AGENCY"

    def test_the_same_counter_is_accepted_once_it_quotes_the_current_version(self, api):
        """The rejected body is legal in every other respect: resubmitted with
        the negotiation's current version it lands as round four at 2300 cents.

        PRD: "A seller counter — `POST
        /upfront/negotiations/{negotiationId}/counter` — must carry
        `expected_negotiation_version` holding the client's last observed
        `version` of the target `Negotiation`."

        Design: Corner/cross_cutting_complexity_layers/a_counter_carrying_the_superseded_negotiation_version_is_rejected
        """
        world = _cycled_to_round_three(api)
        api.counter_negotiation(
            world["negotiation_id"],
            fa.counter_payload(
                world["superseded_version"],
                counter_cpm_cents=2300,
                counter_impressions=1_000_000,
            ),
            world["seller_headers"],
        )

        response = api.counter_negotiation(
            world["negotiation_id"],
            fa.counter_payload(
                3, counter_cpm_cents=2300, counter_impressions=1_000_000
            ),
            world["seller_headers"],
        )

        accepted = validate_success(response, 200)
        assert accepted["status"] == NegotiationStatus.SELLER_COUNTER.value
        assert accepted["round_number"] == 4
        assert accepted["version"] == 4
        assert_cents(accepted, "current_cpm_cents", 2300)


def _covered_buy_ready_to_place(api):
    """A buy whose unit line covers its whole guarantee, with the campaign
    version the buyer read captured before anything else touches the campaign."""
    world = _open_negotiation(api)
    fx.counter(
        api,
        world["negotiation_id"],
        world["seller_id"],
        counter_cpm_cents=2200,
        counter_impressions=1_000_000,
    )
    buy = fx.accept_negotiation(api, world["negotiation_id"])
    unit = fx.add_unit(api, buy["id"], world["forecast_id"], **UNIT)
    world["buy_id"] = buy["id"]
    world["unit_id"] = unit["id"]
    world["observed_campaign_version"] = fx.campaign_version(api, world["campaign_id"])
    return world


class TestStaleCampaignVersion:
    def test_a_placement_quoting_the_pre_funding_campaign_version_is_refused(self, api):
        """A funding deposit landing between the buyer's read and the placement
        makes the quoted campaign version stale, and the placement is refused
        with none of its cascades run.

        PRD: "If `expected_campaign_version` does not equal the campaign's
        current `version`, the request is rejected with
        `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/placing_a_buy_against_a_superseded_campaign_version_is_rejected
        """
        world = _covered_buy_ready_to_place(api)
        fx.fund_campaign(api, world["campaign_id"], world["advertiser_id"], 1_000_000)

        response = api.place_buy(
            world["buy_id"],
            fa.place_payload(world["observed_campaign_version"]),
            BUYER_HEADERS,
        )

        validate_error(response, ApiErrorId.STALE_CAMPAIGN_VERSION, 412)

        buy = fx.read_buy(api, world["buy_id"])
        assert buy["buy_status"] == "PENDING_PLACEMENT"
        assert buy["placed_by_user_id"] is None

        campaign = fx.read_campaign(api, world["campaign_id"])
        assert campaign["version"] == 5
        assert_cents(campaign, "funded_cents", 1_000_000)
        assert campaign["funding_status"] == "PARTIALLY_FUNDED"
        assert_cents(campaign, "committed_gross_cents", 0)
        assert_cents(campaign, "uncommitted_budget_cents", 10_000_000)

        allocation = fx.read_allocation(api, world["allocation_id"])
        assert_cents(allocation, "committed_cents", 0)
        assert allocation["posture"] == "WITHIN_PLAN"
        assert allocation["status"] == "LOCKED"

    def test_the_same_placement_lands_once_it_quotes_the_current_version(self, api):
        """Every other placement precondition already held, so requoting the
        campaign's current version places the buy and moves the campaign on
        again.

        PRD: "A buy placement — `POST /upfront/buys/{buyId}/place` — must carry
        `expected_campaign_version` holding the client's last observed `version`
        of the `Campaign` the buy belongs to."

        Design: Corner/cross_cutting_complexity_layers/placing_a_buy_against_a_superseded_campaign_version_is_rejected
        """
        world = _covered_buy_ready_to_place(api)
        fx.fund_campaign(api, world["campaign_id"], world["advertiser_id"], 1_000_000)
        api.place_buy(
            world["buy_id"],
            fa.place_payload(world["observed_campaign_version"]),
            BUYER_HEADERS,
        )

        response = api.place_buy(world["buy_id"], fa.place_payload(5), BUYER_HEADERS)

        placed = validate_success(response, 200)
        assert placed["buy_status"] == "PLACED"
        assert fx.read_campaign(api, world["campaign_id"])["version"] == 6


class TestNegotiationVersionDiscipline:
    def test_each_accepted_write_advances_the_version_by_exactly_one(self, api):
        """Creation leaves the negotiation at version 1 and the counter, the
        revision and the withdrawal each move it on by exactly one, to 4.

        PRD: "Most resources additionally carry `updated_at`, refreshed on every
        mutation of the resource, and `version`, an integer that starts at 1 on
        creation and increments by exactly 1 on every mutation of that
        resource."

        Design: Corner/cross_cutting_complexity_layers/every_write_on_the_negotiation_increments_its_version_by_exactly_one
        """
        world = _open_negotiation(api)
        assert world["negotiation"]["version"] == 1

        countered = validate_success(
            api.counter_negotiation(
                world["negotiation_id"],
                fa.counter_payload(1, counter_cpm_cents=2200, counter_impressions=1_000_000),
                world["seller_headers"],
            ),
            200,
        )
        assert countered["version"] == 2

        revised = validate_success(
            api.revise_negotiation(
                world["negotiation_id"],
                fa.revise_payload(offer_cpm_cents=2100, offer_impressions=1_000_000),
                BUYER_HEADERS,
            ),
            200,
        )
        assert revised["version"] == 3

        withdrawn = validate_success(
            api.withdraw_negotiation(
                world["negotiation_id"],
                fa.withdraw_payload(withdraw_reason="budget pulled"),
                BUYER_HEADERS,
            ),
            200,
        )
        assert withdrawn["version"] == 4
        assert withdrawn["status"] == NegotiationStatus.WITHDRAWN.value

    def test_reads_never_advance_the_version(self, api):
        """Two reads taken between the counter and the revision leave the
        negotiation exactly where the counter left it, and a final read leaves
        the withdrawn negotiation at 4.

        PRD: "Most resources additionally carry `updated_at`, refreshed on every
        mutation of the resource, and `version`, an integer that starts at 1 on
        creation and increments by exactly 1 on every mutation of that
        resource."

        Design: Corner/cross_cutting_complexity_layers/every_write_on_the_negotiation_increments_its_version_by_exactly_one
        """
        world = _open_negotiation(api)
        api.counter_negotiation(
            world["negotiation_id"],
            fa.counter_payload(1, counter_cpm_cents=2200, counter_impressions=1_000_000),
            world["seller_headers"],
        )

        first_read = validate_success(
            api.get_negotiation(world["negotiation_id"], BUYER_HEADERS), 200
        )
        second_read = validate_success(
            api.get_negotiation(world["negotiation_id"], BUYER_HEADERS), 200
        )
        assert first_read["version"] == 2
        assert second_read["version"] == 2

        fx.revise(
            api, world["negotiation_id"], offer_cpm_cents=2100, offer_impressions=1_000_000
        )
        fx.withdraw_negotiation(api, world["negotiation_id"])
        assert fx.read_negotiation(api, world["negotiation_id"])["version"] == 4


def _aired_and_drafted(api):
    """A buy aired for its whole guarantee and billed as one draft invoice of
    2,354,000 cents, with the campaign funded for exactly that amount."""
    world = _covered_buy_ready_to_place(api)
    fx.place_buy(
        api,
        world["buy_id"],
        world["campaign_id"],
        expected_campaign_version=world["observed_campaign_version"],
    )
    fx.move_clock(api, "2026-12-01T00:00:00Z")
    fx.settle_aired(api, world["unit_id"], world["seller_id"], 1_000_000)
    fx.fund_campaign(api, world["campaign_id"], world["advertiser_id"], 2_354_000)
    invoice = fx.draft_invoice(
        api,
        world["buy_id"],
        billing_period_start="2026-11-01T00:00:00Z",
        billing_period_end="2026-11-30T23:59:59Z",
    )
    world["invoice"] = invoice
    world["invoice_id"] = invoice["id"]
    return world


class TestOutstandingReceivable:
    def test_a_draft_invoice_contributes_nothing_and_issuing_it_contributes_the_whole_bill(
        self, api
    ):
        """The receivable on the advertiser reads 0 while the invoice is still a
        draft and jumps to the invoice's whole net payable the moment it issues.

        PRD: "The buy's `settlement_status` cascades `UNBILLED → INVOICED`, the
        advertiser's `outstanding_receivable_cents` is recomputed, and the
        invoice's `version` increments by 1."

        Design: Corner/cross_cutting_complexity_layers/outstanding_receivable_reconciles_across_issue_and_full_payment
        """
        world = _aired_and_drafted(api)
        assert_cents(world["invoice"], "net_payable_cents", 2_354_000)

        while_draft = validate_success(
            api.get_advertiser(world["advertiser_id"], CONTROLLER_HEADERS), 200
        )
        assert_cents(while_draft, "outstanding_receivable_cents", 0)

        issued = validate_success(
            api.issue_invoice(world["invoice_id"], None, CONTROLLER_HEADERS), 200
        )
        assert issued["client_status"] == "ISSUED"

        after_issue = validate_success(
            api.get_advertiser(world["advertiser_id"], CONTROLLER_HEADERS), 200
        )
        assert_cents(after_issue, "outstanding_receivable_cents", 2_354_000)
        assert fx.read_buy(api, world["buy_id"])["settlement_status"] == "INVOICED"

    def test_the_due_date_is_the_issue_instant_advanced_by_the_payment_terms(self, api):
        """Issued on the first of December against thirty-day terms, the bill
        falls due on the last day of the month.

        PRD: "On success `issued_at` is stamped from the logical clock and
        `due_date` is set to `issued_at` advanced by the advertiser's
        `payment_terms_days` days — thirty days by default, which is why a client
        that never changed its terms sees a bill fall due one month after
        issue."

        Design: Corner/cross_cutting_complexity_layers/outstanding_receivable_reconciles_across_issue_and_full_payment
        """
        world = _aired_and_drafted(api)

        issued = validate_success(
            api.issue_invoice(world["invoice_id"], None, CONTROLLER_HEADERS), 200
        )

        assert_instant_field(issued, "issued_at", "2026-12-01T00:00:00Z")
        assert_instant_field(issued, "due_date", "2026-12-31T00:00:00Z")

    def test_full_payment_returns_the_receivable_to_zero_without_drifting(self, api):
        """Paying the bill in full puts the advertiser's receivable back to
        exactly 0 while the invoice keeps the payment on its own face — the two
        views are different numbers.

        PRD: "Each accepted payment increases `client_paid_cents` by
        `amount_cents`, recomputes `max_remittable_cents`, recomputes the
        advertiser's `outstanding_receivable_cents` and increments the invoice's
        `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/outstanding_receivable_reconciles_across_issue_and_full_payment
        """
        world = _aired_and_drafted(api)
        fx.issue_invoice(api, world["invoice_id"])

        paid = validate_success(
            api.record_client_payment(
                world["invoice_id"],
                fa.client_payment_payload(2_354_000),
                fx.make_advertiser_client_headers(world["advertiser_id"]),
            ),
            200,
        )

        assert_cents(paid, "client_paid_cents", 2_354_000)
        assert paid["client_status"] == "PAID"
        assert paid["late_payment_flag"] is False
        assert_cents(paid, "max_remittable_cents", 2_200_000)

        advertiser = validate_success(
            api.get_advertiser(world["advertiser_id"], CONTROLLER_HEADERS), 200
        )
        assert_cents(advertiser, "outstanding_receivable_cents", 0)
        assert advertiser["credit_status"] == "ACTIVE"
        assert advertiser["late_payment_count"] == 0

        assert fx.read_buy(api, world["buy_id"])["settlement_status"] == "CLIENT_PAID"
