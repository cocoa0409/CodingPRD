"""Writes whose legality is decided entirely by the state of another entity.

Negotiation acceptance is gated on the campaign's plan axis, and a make-good
offer is gated on the publication state of the avail it names: in both cases the
identical call is refused first and accepted afterwards, with nothing about the
target itself changing in between.
"""

from test_helpers import (
    BUYER_HEADERS,
    ApiErrorId,
    AllocationStatus,
    BuyStatus,
    ForecastStatus,
    MakeGoodStatus,
    NegotiationStatus,
    PlanStatus,
    StewardshipStatus,
    UnitStatus,
    assert_allocation_posture,
    assert_buy_axes,
    assert_campaign_axes,
    assert_cents,
    assert_cost_stack,
    assert_impressions,
    fixtures as fx,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ==========================================================================
# Instance A — negotiation_acceptance_gated_by_campaign_plan_state
# ==========================================================================
#: The terms the seller puts on the table and the cost stack they imply.
A_COUNTER_CPM_CENTS = 2100
A_COUNTER_IMPRESSIONS = 3_000_000
A_NET_MEDIA_COST_CENTS = 6_300_000
A_COMMISSION_RATE = 0.0550
A_AGENCY_COMMISSION_CENTS = 346_500
A_GROSS_COST_CENTS = 6_646_500


def _negotiation_awaiting_plan_approval(api):
    """A seller counter on the table while the plan still awaits the client.

    The campaign's plan has been submitted but not approved, so its single
    allocation is still ``DRAFT``; the negotiation itself sits at
    ``SELLER_COUNTER`` on round 2 and is in every respect ready to accept.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Wexford Airlines",
        category_code="TRAVEL",
        credit_limit_cents=90_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Skyline Sports Net",
        platform_types=["LINEAR", "CTV"],
        make_good_capacity_impressions=6_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Fly Q4",
        target_demo="A25-54",
        universe_thousands=100_000,
        reach_goal_pct=40.0,
        frequency_goal=3.0,
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
        planned_cpm_cents=2000,
        planned_market="UPFRONT",
        primary_daypart="PRIME",
    )
    fx.submit_plan(api, campaign["id"])
    negotiation = fx.open_negotiation(
        api,
        campaign["id"],
        seller["id"],
        allocation["id"],
        market="UPFRONT",
        channel="LINEAR_TV",
        requested_impressions=A_COUNTER_IMPRESSIONS,
        opening_cpm_cents=1950,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    countered = fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=A_COUNTER_CPM_CENTS,
        counter_impressions=A_COUNTER_IMPRESSIONS,
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "negotiation_id": negotiation["id"],
        "countered_version": countered["version"],
        "client_headers": make_advertiser_client_headers(advertiser["id"]),
        "seller_headers": make_seller_rep_headers(seller["id"]),
    }


class TestNegotiationAcceptanceGatedByCampaignPlanState:
    """One accept call, refused and then admitted by the campaign's plan axis."""

    def test_accept_refused_while_the_plan_awaits_client_approval(self, api):
        """A negotiation ready to accept is refused with
        ERR_CAMPAIGN_PLAN_NOT_APPROVED while its campaign sits at
        PENDING_CLIENT_APPROVAL, and the refusal leaves the negotiation on
        round 2 at the version its counter minted.

        PRD: "The campaign's `plan_status` must be `APPROVED` — a plan still in
        draft, awaiting approval, or pushed back to `REVISION_REQUIRED` by an
        overcommitment cascade is refused with `ERR_CAMPAIGN_PLAN_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/negotiation_acceptance_gated_by_campaign_plan_state
        """
        world = _negotiation_awaiting_plan_approval(api)
        before = fx.read_campaign(api, world["campaign_id"])
        assert_campaign_axes(before, plan_status=PlanStatus.PENDING_CLIENT_APPROVAL.value)
        assert_allocation_posture(
            fx.read_allocation(api, world["allocation_id"]),
            status=AllocationStatus.DRAFT.value,
        )

        refused = api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS)
        validate_error(refused, ApiErrorId.CAMPAIGN_PLAN_NOT_APPROVED, 409)

        negotiation = fx.read_negotiation(api, world["negotiation_id"])
        assert negotiation["status"] == NegotiationStatus.SELLER_COUNTER.value
        assert negotiation["version"] == world["countered_version"]
        assert negotiation["round_number"] == 2

    def test_the_refused_accept_freezes_no_terms_and_raises_no_buy(self, api):
        """The refused acceptance leaves `accepted_cpm_cents` and
        `accepted_impressions` null and brings no Buy into existence against the
        negotiation.

        PRD: "On the negotiation, `accepted_cpm_cents` takes the value of
        `current_cpm_cents` and `accepted_impressions` takes the value of
        `current_impressions`; both fields are null until this moment."

        Design: Difficulty/cross_entity_state_dependency/negotiation_acceptance_gated_by_campaign_plan_state
        """
        world = _negotiation_awaiting_plan_approval(api)
        validate_error(
            api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS),
            ApiErrorId.CAMPAIGN_PLAN_NOT_APPROVED,
            409,
        )

        negotiation = validate_success(
            api.get_negotiation(world["negotiation_id"], BUYER_HEADERS)
        )
        assert negotiation["accepted_cpm_cents"] is None
        assert negotiation["accepted_impressions"] is None
        assert negotiation["current_cpm_cents"] == A_COUNTER_CPM_CENTS
        assert negotiation["current_impressions"] == A_COUNTER_IMPRESSIONS

        buys, meta = validate_paginated(
            api.list_buys(
                BUYER_HEADERS, params={"negotiation_id": world["negotiation_id"]}
            )
        )
        assert meta["total_count"] == 0, "a refused acceptance must create no buy"
        assert buys == []

    def test_client_approval_locks_the_allocation_and_admits_the_same_accept(self, api):
        """Client approval carries the campaign to APPROVED and its allocation to
        LOCKED, and the identical accept then returns 201 with the seller's terms
        frozen onto the negotiation.

        PRD: "Approval cascades into the plan structure: every channel allocation
        of this campaign whose `status` is `DRAFT` transitions `DRAFT → LOCKED`,
        each such allocation's `version` incrementing by 1, and the campaign's own
        `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/negotiation_acceptance_gated_by_campaign_plan_state
        """
        world = _negotiation_awaiting_plan_approval(api)
        validate_error(
            api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS),
            ApiErrorId.CAMPAIGN_PLAN_NOT_APPROVED,
            409,
        )

        approved = validate_success(
            api.approve_plan(world["campaign_id"], None, world["client_headers"])
        )
        assert_campaign_axes(approved, plan_status=PlanStatus.APPROVED.value)
        assert_allocation_posture(
            fx.read_allocation(api, world["allocation_id"]),
            status=AllocationStatus.LOCKED.value,
        )

        accepted = validate_success(
            api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS), 201
        )
        assert accepted["negotiation_id"] == world["negotiation_id"]

        negotiation = fx.read_negotiation(api, world["negotiation_id"])
        assert negotiation["status"] == NegotiationStatus.ACCEPTED.value
        assert negotiation["accepted_cpm_cents"] == A_COUNTER_CPM_CENTS
        assert negotiation["accepted_impressions"] == A_COUNTER_IMPRESSIONS

    def test_the_admitted_accept_prices_the_buy_on_the_middle_commission_tier(self, api):
        """The buy the unblocked acceptance creates carries a net media cost of
        6,300,000 cents, a commission rate of 0.0550, 346,500 cents of commission
        and a gross cost of 6,646,500 cents.

        PRD: "From that pre-commission net figure — and never from any figure that
        already includes commission — the agency's `commission_rate` is selected
        on a three-tier schedule: 0.0700 while the net media cost is below
        5,000,000 cents (that is, below fifty thousand dollars); 0.0550 while it is
        at or above 5,000,000 cents and below 25,000,000 cents; and 0.0400 once it
        reaches 25,000,000 cents (two hundred and fifty thousand dollars) or more."

        Design: Difficulty/cross_entity_state_dependency/negotiation_acceptance_gated_by_campaign_plan_state
        """
        world = _negotiation_awaiting_plan_approval(api)
        validate_error(
            api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS),
            ApiErrorId.CAMPAIGN_PLAN_NOT_APPROVED,
            409,
        )
        fx.approve_plan(api, world["campaign_id"], world["advertiser_id"])

        buy = validate_success(
            api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS), 201
        )
        assert_impressions(buy, "guaranteed_impressions", A_COUNTER_IMPRESSIONS)
        assert buy["agreed_cpm_cents"] == A_COUNTER_CPM_CENTS
        assert_cost_stack(
            buy,
            {
                "net_media_cost_cents": A_NET_MEDIA_COST_CENTS,
                "commission_rate": A_COMMISSION_RATE,
                "agency_commission_cents": A_AGENCY_COMMISSION_CENTS,
                "gross_cost_cents": A_GROSS_COST_CENTS,
            },
        )

    def test_the_admitted_accept_commits_none_of_the_campaign_budget(self, api):
        """The buy lands at PENDING_PLACEMENT and the campaign's
        `committed_gross_cents` still reads 0 after the acceptance.

        PRD: "Nothing on the campaign changes at acceptance: a
        `PENDING_PLACEMENT` buy consumes no budget, and budget is only committed
        at placement."

        Design: Difficulty/cross_entity_state_dependency/negotiation_acceptance_gated_by_campaign_plan_state
        """
        world = _negotiation_awaiting_plan_approval(api)
        validate_error(
            api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS),
            ApiErrorId.CAMPAIGN_PLAN_NOT_APPROVED,
            409,
        )
        fx.approve_plan(api, world["campaign_id"], world["advertiser_id"])

        buy = validate_success(
            api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS), 201
        )
        assert_buy_axes(buy, buy_status=BuyStatus.PENDING_PLACEMENT.value)

        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_cents(campaign, "committed_gross_cents", 0)
        assert_cents(campaign, "uncommitted_budget_cents", 30_000_000)
        assert_campaign_axes(campaign, plan_status=PlanStatus.APPROVED.value)


# ==========================================================================
# Instance B — make_good_offer_gated_by_avail_publication_state
# ==========================================================================
#: The guarantee, the price and the measured demo delivery of the placed buy.
B_GUARANTEED_IMPRESSIONS = 40_000_000
B_AGREED_CPM_CENTS = 2200
B_DELIVERED_IMPRESSIONS = 39_000_000
B_DELIVERED_DEMO_IMPRESSIONS = 37_200_000

#: The shortfall that leaves an OPEN make-good, and the offer that covers it.
B_SHORTFALL_IMPRESSIONS = 2_800_000
B_OFFERED_IMPRESSIONS = 2_800_000
B_OFFERED_WINDOW_START = "2027-02-01T00:00:00Z"
B_OFFERED_WINDOW_END = "2027-02-28T23:59:59Z"

#: The replacement avail: filed for 10,000,000 impressions and left in DRAFT.
B_REPLACEMENT_TOTAL_IMPRESSIONS = 10_000_000
B_REPLACEMENT_AFTER_ACCEPT = 7_200_000

#: The seller's make-good headroom, and the instant the offer is made from.
B_MAKE_GOOD_CAPACITY = 20_000_000
B_OFFER_CLOCK = "2027-01-05T00:00:00Z"


def _open_make_good_with_draft_replacement_avail(api):
    """An OPEN make-good facing a replacement avail that is still DRAFT.

    A placed buy of 40,000,000 impressions at CPM 2200 was reported delivering
    37,200,000 demo impressions, so accepting that post-buy-final report left a
    make-good open for 2,800,000 impressions.  The 2027Q1 avail the seller means
    to offer from has been filed for 10,000,000 impressions but never published,
    and the logical clock stands at 2027-01-05, before the offered window.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Cobalt Software",
        category_code="TECHNOLOGY",
        credit_limit_cents=400_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Meridian Media",
        platform_types=["LINEAR"],
        make_good_capacity_impressions=B_MAKE_GOOD_CAPACITY,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Cobalt Q4 Linear",
        target_demo="A25-54",
        universe_thousands=120_000,
        reach_goal_pct=50.0,
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

    ordered_avail = fx.file_avail(
        api,
        seller["id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Meridian Prime",
        platform="LINEAR",
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-12-31T23:59:59Z",
        total_impressions=60_000_000,
        forecast_cpm_cents=B_AGREED_CPM_CENTS,
        exclusivity_mode="SHARED",
    )
    fx.publish_avail(api, ordered_avail["id"], seller["id"])

    replacement_avail = fx.file_avail(
        api,
        seller["id"],
        market="SCATTER",
        fiscal_quarter="2027Q1",
        daypart="PRIME",
        program="Meridian Prime",
        platform="LINEAR",
        window_start="2027-01-15T00:00:00Z",
        window_end="2027-03-31T23:59:59Z",
        total_impressions=B_REPLACEMENT_TOTAL_IMPRESSIONS,
        forecast_cpm_cents=2100,
        exclusivity_mode="SHARED",
    )

    negotiation = fx.open_negotiation(
        api,
        campaign["id"],
        seller["id"],
        allocation["id"],
        market="UPFRONT",
        channel="LINEAR_TV",
        requested_impressions=B_GUARANTEED_IMPRESSIONS,
        opening_cpm_cents=2000,
        guarantee_pct=100,
        make_good_provision="MAKE_GOOD_UNITS",
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=B_AGREED_CPM_CENTS,
        counter_impressions=B_GUARANTEED_IMPRESSIONS,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    fx.add_unit(
        api,
        buy["id"],
        ordered_avail["id"],
        daypart="PRIME",
        program="Meridian Prime",
        platform="LINEAR",
        units=40,
        unit_rate_cents=2_200_000,
        projected_impressions=B_GUARANTEED_IMPRESSIONS,
        air_window_start="2026-11-02T00:00:00Z",
        air_window_end="2026-12-15T23:59:59Z",
    )
    fx.place_buy(api, buy["id"], campaign["id"])

    # The clock has to stand past the reported period before delivery may be
    # filed, since no one reports the future; it lands on the same instant the
    # offer is later made from.
    fx.move_clock(api, B_OFFER_CLOCK)

    report = fx.file_report(
        api,
        buy["id"],
        B_DELIVERED_IMPRESSIONS,
        B_DELIVERED_DEMO_IMPRESSIONS,
        seller_id=seller["id"],
        measurement_basis="LINEAR_C3",
        period_start="2026-12-01T00:00:00Z",
        period_end="2026-12-31T23:59:59Z",
    )
    fx.accept_report(api, report["id"])
    make_good = fx.only_make_good(api, buy["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "buy_id": buy["id"],
        "forecast_id": ordered_avail["id"],
        "replacement_id": replacement_avail["id"],
        "make_good_id": make_good["id"],
        "make_good": make_good,
        "seller_headers": make_seller_rep_headers(seller["id"]),
    }


def _offer_payload(world):
    """The identical make-good offer the two triggers both send."""
    return {
        "offered_forecast_id": world["replacement_id"],
        "offered_impressions": B_OFFERED_IMPRESSIONS,
        "offered_window_start": B_OFFERED_WINDOW_START,
        "offered_window_end": B_OFFERED_WINDOW_END,
    }


def _refuse_then_publish_and_offer(api, world):
    """Send the offer against the DRAFT avail, publish it, then offer again."""
    validate_error(
        api.offer_make_good(
            world["make_good_id"], _offer_payload(world), world["seller_headers"]
        ),
        ApiErrorId.FORECAST_NOT_PUBLISHED,
        409,
    )
    fx.publish_avail(api, world["replacement_id"], world["seller_id"])
    return validate_success(
        api.offer_make_good(
            world["make_good_id"], _offer_payload(world), world["seller_headers"]
        )
    )


class TestMakeGoodOfferGatedByAvailPublicationState:
    """One make-good offer, refused and then admitted by the avail's own state."""

    def test_offer_refused_while_the_replacement_avail_is_still_draft(self, api):
        """An offer of 2,800,000 impressions naming an unpublished 2027Q1 avail is
        refused with ERR_FORECAST_NOT_PUBLISHED, leaving the make-good OPEN at
        offer_round 0 with no offered figures recorded.

        PRD: "The offered avail must be `PUBLISHED`, or the offer is refused with
        `ERR_FORECAST_NOT_PUBLISHED`, and it must belong to the buy's own seller,
        or the offer is refused with `ERR_NOT_RESOURCE_OWNER`."

        Design: Difficulty/cross_entity_state_dependency/make_good_offer_gated_by_avail_publication_state
        """
        world = _open_make_good_with_draft_replacement_avail(api)
        assert world["make_good"]["status"] == MakeGoodStatus.OPEN.value
        assert_impressions(
            world["make_good"], "shortfall_impressions", B_SHORTFALL_IMPRESSIONS
        )

        refused = api.offer_make_good(
            world["make_good_id"], _offer_payload(world), world["seller_headers"]
        )
        validate_error(refused, ApiErrorId.FORECAST_NOT_PUBLISHED, 409)

        make_good = fx.read_make_good(api, world["make_good_id"])
        assert make_good["status"] == MakeGoodStatus.OPEN.value
        assert make_good["offer_round"] == 0
        assert_impressions(make_good, "offered_impressions", 0)
        assert make_good["offered_forecast_id"] is None

    def test_the_refused_offer_takes_no_hold_on_the_draft_avail(self, api):
        """The refused offer leaves the 2027Q1 avail at DRAFT with all 10,000,000
        of its impressions still available.

        PRD: "The remaining-availability figure is a live subtraction rather than a
        counter that only ever decreases: at any moment `available_impressions` is
        `total_impressions` less the sum of `projected_impressions` over the unit
        lines occupying this avail whose `status` is `SCHEDULED`, `AIRED`,
        `MAKE_GOOD_SCHEDULED` or `MAKE_GOOD_AIRED`."

        Design: Difficulty/cross_entity_state_dependency/make_good_offer_gated_by_avail_publication_state
        """
        world = _open_make_good_with_draft_replacement_avail(api)
        validate_error(
            api.offer_make_good(
                world["make_good_id"], _offer_payload(world), world["seller_headers"]
            ),
            ApiErrorId.FORECAST_NOT_PUBLISHED,
            409,
        )

        avail = validate_success(
            api.get_inventory_forecast(world["replacement_id"], BUYER_HEADERS)
        )
        assert_impressions(
            avail, "available_impressions", B_REPLACEMENT_TOTAL_IMPRESSIONS
        )
        assert avail["status"] == ForecastStatus.DRAFT.value

    def test_publishing_the_avail_admits_the_identical_offer(self, api):
        """Publishing the 2027Q1 avail makes it offerable, and the byte-identical
        offer then returns 200 with the make-good OFFERED at offer_round 1.

        PRD: "Publication increments the avail's `version` by 1 and makes it
        eligible both for unit-line placement and for use as make-good replacement
        inventory."

        Design: Difficulty/cross_entity_state_dependency/make_good_offer_gated_by_avail_publication_state
        """
        world = _open_make_good_with_draft_replacement_avail(api)
        offered = _refuse_then_publish_and_offer(api, world)

        assert offered["status"] == MakeGoodStatus.OFFERED.value
        assert offered["offer_round"] == 1
        assert_impressions(offered, "offered_impressions", B_OFFERED_IMPRESSIONS)
        assert offered["offered_forecast_id"] == world["replacement_id"]

    def test_accepting_the_offer_makes_the_buy_good(self, api):
        """Accepting the offer carries the make-good to SCHEDULED and closes the
        buy's shortfall: 2,800,000 made-good impressions, no open shortfall and a
        stewardship axis reading MADE_GOOD.

        PRD: "The buy's `made_good_impressions` grows by `offered_impressions` and
        its `open_shortfall_impressions` is recomputed; because that figure has
        reached 0, the buy's `stewardship_status` moves
        `UNDER_DELIVERED → MADE_GOOD` and the buy's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/make_good_offer_gated_by_avail_publication_state
        """
        world = _open_make_good_with_draft_replacement_avail(api)
        _refuse_then_publish_and_offer(api, world)

        scheduled = validate_success(
            api.accept_make_good(world["make_good_id"], None, BUYER_HEADERS)
        )
        assert scheduled["status"] == MakeGoodStatus.SCHEDULED.value

        buy = fx.read_buy(api, world["buy_id"])
        assert_impressions(buy, "made_good_impressions", B_OFFERED_IMPRESSIONS)
        assert_impressions(buy, "open_shortfall_impressions", 0)
        assert_buy_axes(buy, stewardship_status=StewardshipStatus.MADE_GOOD.value)

    def test_accepting_the_offer_drains_the_replacement_avail(self, api):
        """The accepted make-good holds 2,800,000 impressions on the 2027Q1 avail,
        taking it to 7,200,000 available while it stays PUBLISHED.

        PRD: "The avail's `available_impressions` decreases by `offered_impressions`
        and it moves `PUBLISHED → EXHAUSTED` if that reaches 0."

        Design: Difficulty/cross_entity_state_dependency/make_good_offer_gated_by_avail_publication_state
        """
        world = _open_make_good_with_draft_replacement_avail(api)
        _refuse_then_publish_and_offer(api, world)
        validate_success(api.accept_make_good(world["make_good_id"], None, BUYER_HEADERS))

        avail = validate_success(
            api.get_inventory_forecast(world["replacement_id"], BUYER_HEADERS)
        )
        assert_impressions(avail, "available_impressions", B_REPLACEMENT_AFTER_ACCEPT)
        assert avail["status"] == ForecastStatus.PUBLISHED.value

    def test_accepting_the_offer_moves_the_seller_exposure_from_open_to_scheduled(
        self, api
    ):
        """The seller's open make-good exposure falls to 0 while its scheduled
        exposure — the figure that consumes its 20,000,000 impression capacity —
        rises to 2,800,000.

        PRD: "The seller's `open_make_good_impressions` and
        `scheduled_make_good_impressions` are both recomputed — the exposure moves
        from open to scheduled, which is what consumes the seller's capacity."

        Design: Difficulty/cross_entity_state_dependency/make_good_offer_gated_by_avail_publication_state
        """
        world = _open_make_good_with_draft_replacement_avail(api)
        before = fx.read_seller(api, world["seller_id"])
        assert_impressions(
            before, "open_make_good_impressions", B_SHORTFALL_IMPRESSIONS
        )
        assert_impressions(before, "scheduled_make_good_impressions", 0)

        _refuse_then_publish_and_offer(api, world)
        validate_success(api.accept_make_good(world["make_good_id"], None, BUYER_HEADERS))

        seller = fx.read_seller(api, world["seller_id"])
        assert_impressions(seller, "open_make_good_impressions", 0)
        assert_impressions(
            seller, "scheduled_make_good_impressions", B_OFFERED_IMPRESSIONS
        )

    def test_the_replacement_unit_line_is_discoverable_by_make_good_id(self, api):
        """The acceptance books exactly one replacement unit line against the
        make-good, carrying status MAKE_GOOD_SCHEDULED and the offered avail,
        impressions and window.

        PRD: "On success a replacement unit line is created for the buy with
        `status` `MAKE_GOOD_SCHEDULED`, its `make_good_id` pointing back at this
        make-good, its `forecast_id` taken from `offered_forecast_id`, its
        `projected_impressions` set to `offered_impressions`, its `units` set to 1,
        its `unit_rate_cents` set to 0, its `air_window_start` and `air_window_end`
        copied from the offered window, and its `daypart`, `program` and `platform`
        copied from the avail."

        Design: Difficulty/cross_entity_state_dependency/make_good_offer_gated_by_avail_publication_state
        """
        world = _open_make_good_with_draft_replacement_avail(api)
        _refuse_then_publish_and_offer(api, world)
        validate_success(api.accept_make_good(world["make_good_id"], None, BUYER_HEADERS))

        rows, meta = validate_paginated(
            api.list_buy_units(
                BUYER_HEADERS, params={"make_good_id": world["make_good_id"]}
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        line = rows[0]
        assert line["status"] == UnitStatus.MAKE_GOOD_SCHEDULED.value
        assert line["make_good_id"] == world["make_good_id"]
        assert line["forecast_id"] == world["replacement_id"]
        assert_impressions(line, "projected_impressions", B_OFFERED_IMPRESSIONS)
        assert line["units"] == 1
        assert_cents(line, "unit_rate_cents", 0)
