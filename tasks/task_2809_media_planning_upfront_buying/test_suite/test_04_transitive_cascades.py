"""Transitive cascade chains of the upfront buying domain.

One placement walks the four-link overcommitment chain of §3.6 and revokes the
plan's approval, and one delivery acceptance walks the four-link chain of §3.8
across the buy, a brand-new make-good and the seller's exposure counters.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    PLANNER_HEADERS,
    AllocationPosture,
    AllocationStatus,
    ApiErrorId,
    BuyStatus,
    MakeGoodStatus,
    NegotiationStatus,
    PlanPosture,
    PlanStatus,
    ReportStatus,
    StewardshipStatus,
    assert_allocation_posture,
    assert_budget_ledger_balances,
    assert_buy_axes,
    assert_campaign_axes,
    assert_cents,
    assert_impressions,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    get_success_data,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ==========================================================================
# Instance 1 — placement_overcommit_cascades_four_links_and_revokes_plan_approval
# ==========================================================================
#: The gross cost of 30,000,000 impressions at CPM 2200: net 66,000,000 at the
#: lowest commission tier of 0.0400 earns 2,640,000 of commission.
OVERCOMMIT_GROSS_CENTS = 68_640_000

#: The linear allocation's own share of the 100,000,000 cent budget.
OVERCOMMIT_ALLOCATED_CENTS = 60_000_000

#: What the budget has left once that one buy is committed.
OVERCOMMIT_UNCOMMITTED_CENTS = 31_360_000


def _overcommit_world(api):
    """An APPROVED 60/40 plan facing one placement that overshoots its channel.

    The linear leg carries a PENDING_PLACEMENT buy whose gross cost of
    68,640,000 cents exceeds its allocation's 60,000,000 but stays well inside
    the campaign's 100,000,000 budget, and the digital leg carries a second
    negotiation left in SELLER_COUNTER, ready to be accepted.
    """
    advertiser = get_success_data(
        api.create_advertiser(
            fa.advertiser_payload(
                name="Vantage Wireless",
                category_code="TELECOM",
                credit_limit_cents=200_000_000,
                payment_terms_days=30,
                sequential_liability_enabled=True,
            ),
            CONTROLLER_HEADERS,
        )
    )
    seller = get_success_data(
        api.create_seller(
            fa.seller_payload(
                name="Crestview Networks",
                platform_types=["LINEAR", "DIGITAL"],
                make_good_capacity_impressions=10_000_000,
            ),
            CONTROLLER_HEADERS,
        )
    )
    seller_headers = make_seller_rep_headers(seller["id"])
    campaign = get_success_data(
        api.create_campaign(
            fa.campaign_payload(
                advertiser["id"],
                name="Network Upgrade Q4",
                target_demo="A18-49",
                universe_thousands=120_000,
                reach_goal_pct=50.0,
                frequency_goal=4.0,
                total_budget_cents=100_000_000,
                flight_start="2026-11-01T00:00:00Z",
                flight_end="2026-12-31T23:59:59Z",
                fiscal_quarter="2026Q4",
            ),
            PLANNER_HEADERS,
        )
    )
    linear_allocation = get_success_data(
        api.create_channel_allocation(
            fa.channel_allocation_payload(
                campaign["id"],
                channel="LINEAR_TV",
                allocation_pct=60.00,
                planned_cpm_cents=1800,
                planned_market="UPFRONT",
                primary_daypart="PRIME",
            ),
            PLANNER_HEADERS,
        )
    )
    digital_allocation = get_success_data(
        api.create_channel_allocation(
            fa.channel_allocation_payload(
                campaign["id"],
                channel="DIGITAL_VIDEO",
                allocation_pct=40.00,
                planned_cpm_cents=2500,
                planned_market="SCATTER",
                primary_daypart="DIGITAL_ANY",
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
    forecast = get_success_data(
        api.create_inventory_forecast(
            fa.inventory_forecast_payload(
                seller["id"],
                market="UPFRONT",
                fiscal_quarter="2026Q4",
                daypart="PRIME",
                program="Crestview Prime",
                platform="LINEAR",
                window_start="2026-11-01T00:00:00Z",
                window_end="2026-12-31T23:59:59Z",
                total_impressions=40_000_000,
                forecast_cpm_cents=2200,
                exclusivity_mode="SHARED",
            ),
            seller_headers,
        )
    )
    get_success_data(
        api.publish_inventory_forecast(forecast["id"], None, seller_headers)
    )
    linear_negotiation = get_success_data(
        api.create_negotiation(
            fa.negotiation_payload(
                campaign["id"],
                seller["id"],
                linear_allocation["id"],
                market="UPFRONT",
                channel="LINEAR_TV",
                requested_impressions=30_000_000,
                opening_cpm_cents=2000,
                guarantee_pct=100,
                make_good_provision="MAKE_GOOD_UNITS",
                option_pct_ceiling=25,
            ),
            BUYER_HEADERS,
        )
    )
    get_success_data(
        api.counter_negotiation(
            linear_negotiation["id"],
            fa.counter_payload(
                linear_negotiation["version"],
                counter_cpm_cents=2200,
                counter_impressions=30_000_000,
            ),
            seller_headers,
        )
    )
    buy = get_success_data(
        api.accept_negotiation(linear_negotiation["id"], None, BUYER_HEADERS)
    )
    get_success_data(
        api.add_buy_unit(
            buy["id"],
            fa.buy_unit_payload(
                forecast["id"],
                daypart="PRIME",
                program="Crestview Prime",
                platform="LINEAR",
                units=30,
                unit_rate_cents=2_200_000,
                projected_impressions=30_000_000,
                air_window_start="2026-11-02T00:00:00Z",
                air_window_end="2026-11-30T23:59:59Z",
            ),
            BUYER_HEADERS,
        )
    )
    digital_negotiation = get_success_data(
        api.create_negotiation(
            fa.negotiation_payload(
                campaign["id"],
                seller["id"],
                digital_allocation["id"],
                market="SCATTER",
                channel="DIGITAL_VIDEO",
                requested_impressions=5_000_000,
                opening_cpm_cents=2400,
                guarantee_pct=100,
                make_good_provision="CASH_CREDIT",
                option_pct_ceiling=25,
            ),
            BUYER_HEADERS,
        )
    )
    get_success_data(
        api.counter_negotiation(
            digital_negotiation["id"],
            fa.counter_payload(
                digital_negotiation["version"],
                counter_cpm_cents=2500,
                counter_impressions=5_000_000,
            ),
            seller_headers,
        )
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "linear_allocation_id": linear_allocation["id"],
        "digital_allocation_id": digital_allocation["id"],
        "buy_id": buy["id"],
        "digital_negotiation_id": digital_negotiation["id"],
        "campaign_version": fx.campaign_version(api, campaign["id"]),
    }


def _place_the_overcommitting_buy(api, world):
    """Fire the trigger: place the buy against the version just read."""
    return validate_success(
        api.place_buy(
            world["buy_id"],
            fa.place_payload(world["campaign_version"]),
            BUYER_HEADERS,
        ),
        200,
    )


class TestPlacementOvercommitCascade:
    """One place call walks all four links and revokes the plan's approval."""

    def test_link_one_recomputes_the_allocation_committed_total_from_the_placed_buy(
        self, api
    ):
        """Placing a 68,640,000 cent buy carries that whole gross figure into the
        linear allocation's committed_cents, which had been 0.

        PRD: "Because the buy now counts as committed, the `committed_cents` of
        the channel allocation named by the buy's `channel_allocation_id` is
        recomputed as the sum of `gross_cost_cents` over the buys against that
        allocation whose `buy_status` is `PLACED`, `IN_FLIGHT`, `COMPLETED` or
        `CLOSED`."

        Design: Difficulty/transitive_cascade/placement_overcommit_cascades_four_links_and_revokes_plan_approval
        """
        world = _overcommit_world(api)
        placed = _place_the_overcommitting_buy(api, world)
        assert_buy_axes(placed, buy_status=BuyStatus.PLACED.value)
        assert_cents(placed, "gross_cost_cents", OVERCOMMIT_GROSS_CENTS)

        allocation = fx.read_allocation(api, world["linear_allocation_id"])
        assert_cents(allocation, "allocated_cents", OVERCOMMIT_ALLOCATED_CENTS)
        assert_cents(allocation, "committed_cents", OVERCOMMIT_GROSS_CENTS)

    def test_link_two_flips_only_the_overshot_allocation_to_overcommitted(self, api):
        """The linear allocation's posture flips to OVERCOMMITTED while the
        untouched digital allocation stays at 0 committed and WITHIN_PLAN.

        PRD: "Its `posture` reads `OVERCOMMITTED` when `committed_cents` is
        strictly greater than `allocated_cents`, and `WITHIN_PLAN` otherwise — an
        allocation committed to exactly its allocated amount is still within
        plan."

        Design: Difficulty/transitive_cascade/placement_overcommit_cascades_four_links_and_revokes_plan_approval
        """
        world = _overcommit_world(api)
        _place_the_overcommitting_buy(api, world)

        linear = fx.read_allocation(api, world["linear_allocation_id"])
        assert_allocation_posture(
            linear, posture=AllocationPosture.OVERCOMMITTED.value
        )

        digital = fx.read_allocation(api, world["digital_allocation_id"])
        assert_cents(digital, "committed_cents", 0)
        assert_allocation_posture(
            digital, posture=AllocationPosture.WITHIN_PLAN.value
        )

    def test_link_three_recomputes_the_campaign_plan_posture_to_replan_required(
        self, api
    ):
        """One OVERCOMMITTED allocation is enough to move the whole campaign's
        plan_posture to REPLAN_REQUIRED.

        PRD: "The campaign's `plan_posture` reads `REPLAN_REQUIRED` when at least
        one of its allocations sits at `OVERCOMMITTED`, and `WITHIN_PLAN`
        otherwise."

        Design: Difficulty/transitive_cascade/placement_overcommit_cascades_four_links_and_revokes_plan_approval
        """
        world = _overcommit_world(api)
        _place_the_overcommitting_buy(api, world)

        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_campaign_axes(campaign, plan_posture=PlanPosture.REPLAN_REQUIRED.value)

    def test_link_four_revokes_the_approval_and_unlocks_both_allocations(self, api):
        """The approved plan is pushed back to REVISION_REQUIRED and both LOCKED
        allocations return to DRAFT, the untouched one included.

        PRD: "Because `plan_posture` is now `REPLAN_REQUIRED` while `plan_status`
        was `APPROVED`, the campaign is pushed `APPROVED → REVISION_REQUIRED` and
        every `LOCKED` channel allocation of the campaign returns to `DRAFT`, as
        described in §3.3."

        Design: Difficulty/transitive_cascade/placement_overcommit_cascades_four_links_and_revokes_plan_approval
        """
        world = _overcommit_world(api)
        _place_the_overcommitting_buy(api, world)

        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_campaign_axes(campaign, plan_status=PlanStatus.REVISION_REQUIRED.value)

        for allocation_id in (
            world["linear_allocation_id"],
            world["digital_allocation_id"],
        ):
            allocation = fx.read_allocation(api, allocation_id)
            assert_allocation_posture(allocation, status=AllocationStatus.DRAFT.value)

    def test_the_campaign_budget_ledger_carries_the_committed_gross(self, api):
        """The placed buy's 68,640,000 cents becomes the campaign's committed
        gross, leaving 31,360,000 of the 100,000,000 budget uncommitted.

        PRD: "Separately, the campaign's `committed_gross_cents` is the sum of
        `gross_cost_cents` over the campaign's buys whose `buy_status` is
        `PLACED`, `IN_FLIGHT`, `COMPLETED` or `CLOSED` — buys still at
        `PENDING_PLACEMENT` and buys that reached `CANCELLED` are excluded — and
        its `uncommitted_budget_cents` is `total_budget_cents` less that
        committed figure."

        Design: Difficulty/transitive_cascade/placement_overcommit_cascades_four_links_and_revokes_plan_approval
        """
        world = _overcommit_world(api)
        _place_the_overcommitting_buy(api, world)

        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_cents(campaign, "committed_gross_cents", OVERCOMMIT_GROSS_CENTS)
        assert_cents(
            campaign, "uncommitted_budget_cents", OVERCOMMIT_UNCOMMITTED_CENTS
        )
        assert_budget_ledger_balances(campaign)

    def test_link_four_is_observable_downstream_on_the_second_negotiation(self, api):
        """The already-countered digital negotiation can no longer be accepted:
        priority 17 fires with ERR_CAMPAIGN_PLAN_NOT_APPROVED and no buy is made.

        PRD: "The campaign's `plan_status` must be `APPROVED` — a plan still in
        draft, awaiting approval, or pushed back to `REVISION_REQUIRED` by an
        overcommitment cascade is refused with `ERR_CAMPAIGN_PLAN_NOT_APPROVED`."

        Design: Difficulty/transitive_cascade/placement_overcommit_cascades_four_links_and_revokes_plan_approval
        """
        world = _overcommit_world(api)
        _place_the_overcommitting_buy(api, world)

        validate_error(
            api.accept_negotiation(
                world["digital_negotiation_id"], None, BUYER_HEADERS
            ),
            ApiErrorId.CAMPAIGN_PLAN_NOT_APPROVED,
            409,
        )

        negotiation = fx.read_negotiation(api, world["digital_negotiation_id"])
        assert negotiation["status"] == NegotiationStatus.SELLER_COUNTER.value, (
            "the refused acceptance must leave the negotiation at SELLER_COUNTER, "
            f"got {negotiation['status']}"
        )


# ==========================================================================
# Instance 2 — delivery_acceptance_cascades_into_seller_make_good_exposure
# ==========================================================================
#: The demo impressions the single accepted report credits to the final view.
DELIVERY_FINAL_CREDIT = 37_200_000

#: 37,200,000 credited against a 40,000,000 guarantee.
DELIVERY_FINAL_INDEX = 0.9300

#: The gross impressions the provisional view keeps reading.
DELIVERY_PROVISIONAL_CREDIT = 39_000_000

#: 39,000,000 credited against the same 40,000,000 guarantee.
DELIVERY_PROVISIONAL_INDEX = 0.9750

#: 40,000,000 guaranteed less 37,200,000 credited on the demo.
DELIVERY_SHORTFALL_IMPRESSIONS = 2_800_000

#: That shortfall valued at the agreed CPM of 2200.
DELIVERY_SHORTFALL_VALUE_CENTS = 6_160_000


def _delivery_shortfall_world(api):
    """A PLACED 40,000,000 impression buy carrying one SUBMITTED final report.

    The report's period ends exactly on the campaign's flight_end, so
    is_post_buy_final computes true.  The logical clock is advanced past that
    period end because §3.8 refuses a report whose period_end lies in the
    future of the clock.
    """
    advertiser = get_success_data(
        api.create_advertiser(
            fa.advertiser_payload(
                name="Lantern Insurance",
                category_code="INSURANCE",
                credit_limit_cents=400_000_000,
                payment_terms_days=30,
                sequential_liability_enabled=True,
            ),
            CONTROLLER_HEADERS,
        )
    )
    seller = get_success_data(
        api.create_seller(
            fa.seller_payload(
                name="Pinnacle Broadcast",
                platform_types=["LINEAR"],
                make_good_capacity_impressions=20_000_000,
            ),
            CONTROLLER_HEADERS,
        )
    )
    seller_headers = make_seller_rep_headers(seller["id"])
    campaign = get_success_data(
        api.create_campaign(
            fa.campaign_payload(
                advertiser["id"],
                name="Peace of Mind Q4",
                target_demo="A25-54",
                universe_thousands=120_000,
                reach_goal_pct=50.0,
                frequency_goal=4.0,
                total_budget_cents=200_000_000,
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
                planned_cpm_cents=1800,
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
    forecast = get_success_data(
        api.create_inventory_forecast(
            fa.inventory_forecast_payload(
                seller["id"],
                market="UPFRONT",
                fiscal_quarter="2026Q4",
                daypart="PRIME",
                program="Pinnacle Primetime",
                platform="LINEAR",
                window_start="2026-11-01T00:00:00Z",
                window_end="2026-12-31T23:59:59Z",
                total_impressions=60_000_000,
                forecast_cpm_cents=2200,
                exclusivity_mode="SHARED",
            ),
            seller_headers,
        )
    )
    get_success_data(
        api.publish_inventory_forecast(forecast["id"], None, seller_headers)
    )
    negotiation = get_success_data(
        api.create_negotiation(
            fa.negotiation_payload(
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
            ),
            BUYER_HEADERS,
        )
    )
    get_success_data(
        api.counter_negotiation(
            negotiation["id"],
            fa.counter_payload(
                negotiation["version"],
                counter_cpm_cents=2200,
                counter_impressions=40_000_000,
            ),
            seller_headers,
        )
    )
    buy = get_success_data(
        api.accept_negotiation(negotiation["id"], None, BUYER_HEADERS)
    )
    get_success_data(
        api.add_buy_unit(
            buy["id"],
            fa.buy_unit_payload(
                forecast["id"],
                daypart="PRIME",
                program="Pinnacle Primetime",
                platform="LINEAR",
                units=40,
                unit_rate_cents=2_200_000,
                projected_impressions=40_000_000,
                air_window_start="2026-11-02T00:00:00Z",
                air_window_end="2026-12-15T23:59:59Z",
            ),
            BUYER_HEADERS,
        )
    )
    get_success_data(
        api.place_buy(
            buy["id"],
            fa.place_payload(fx.campaign_version(api, campaign["id"])),
            BUYER_HEADERS,
        )
    )
    fx.move_clock(api, "2027-01-01T00:00:00Z")
    report = get_success_data(
        api.create_delivery_report(
            fa.delivery_report_payload(
                buy["id"],
                39_000_000,
                37_200_000,
                period_start="2026-12-01T00:00:00Z",
                period_end="2026-12-31T23:59:59Z",
                measurement_basis="LINEAR_C3",
            ),
            seller_headers,
        )
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": forecast["id"],
        "buy_id": buy["id"],
        "report_id": report["id"],
    }


def _accept_the_post_buy_report(api, world):
    """Fire the trigger: the agency accepts the post-buy-final report."""
    return validate_success(
        api.accept_delivery_report(world["report_id"], None, BUYER_HEADERS), 200
    )


class TestDeliveryAcceptanceMakeGoodCascade:
    """Accepting one post-buy-final report walks four links across four entities."""

    def test_the_accepted_report_is_the_post_buy_final_one(self, api):
        """A report whose period ends exactly on the buy's flight_end is flagged
        post-buy-final, and acceptance moves it SUBMITTED to ACCEPTED.

        PRD: "A filed report starts at `status` `SUBMITTED` with `dispute_reason`
        null, and the system computes `is_post_buy_final` for it at that moment:
        the flag reads true exactly when `period_end` is at or after the buy's
        `flight_end`, and it is that flag which makes a later acceptance run the
        post-buy shortfall evaluation."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        accepted = _accept_the_post_buy_report(api, world)

        assert accepted["is_post_buy_final"] is True, (
            "period_end equals flight_end, so is_post_buy_final must read true, "
            f"got {accepted['is_post_buy_final']!r}"
        )
        assert accepted["status"] == ReportStatus.ACCEPTED.value, (
            f"expected the report at ACCEPTED, got {accepted['status']}"
        )

    def test_link_one_credits_only_the_demo_impressions_to_the_final_index(self, api):
        """The final view counts the 37,200,000 demo impressions of the one
        accepted report, giving a final delivery index of 0.9300.

        PRD: "Because an accepted report has entered the final input set,
        `credited_impressions_final` and `final_delivery_index` are recomputed;
        the provisional pair is refreshed in the same pass."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        _accept_the_post_buy_report(api, world)

        buy = fx.read_buy(api, world["buy_id"])
        assert_impressions(buy, "credited_impressions_final", DELIVERY_FINAL_CREDIT)
        assert_pct4(buy, "final_delivery_index", DELIVERY_FINAL_INDEX)

    def test_the_provisional_index_still_reads_the_gross_impressions(self, api):
        """The same single report leaves the provisional view at 39,000,000 gross
        impressions and an index of 0.9750, above the final 0.9300.

        PRD: "The **provisional** view is the in-flight stewardship number:
        `credited_impressions_provisional` is the sum of `delivered_impressions`
        over the buy's reports whose `status` is `SUBMITTED` or `ACCEPTED`, so
        unvetted seller claims count toward it, and `provisional_delivery_index`
        is that credit divided by the buy's `guaranteed_impressions`, rounded
        half up to four decimal places, reading 0.0000 when
        `guaranteed_impressions` is 0."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        _accept_the_post_buy_report(api, world)

        buy = fx.read_buy(api, world["buy_id"])
        assert_impressions(
            buy, "credited_impressions_provisional", DELIVERY_PROVISIONAL_CREDIT
        )
        assert_pct4(buy, "provisional_delivery_index", DELIVERY_PROVISIONAL_INDEX)

    def test_link_two_moves_the_stewardship_axis_to_under_delivered(self, api):
        """A 7.0000 percent demo shortfall is far outside the 2.0000 percent
        tolerance, so stewardship reads UNDER_DELIVERED on a buy now IN_FLIGHT.

        PRD: "If that percentage is at or above the make-good tolerance of 2.0000
        percent — a shortfall of exactly 2.0000 percent does require a make-good —
        the stewardship axis moves to `UNDER_DELIVERED`, arriving from
        `NOT_STARTED`, `ON_TRACK` or `AT_RISK` alike."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        _accept_the_post_buy_report(api, world)

        buy = fx.read_buy(api, world["buy_id"])
        assert_buy_axes(
            buy,
            buy_status=BuyStatus.IN_FLIGHT.value,
            stewardship_status=StewardshipStatus.UNDER_DELIVERED.value,
        )

    def test_the_buy_carries_the_open_shortfall_the_seller_still_owes(self, api):
        """Nothing has been made good or waived, so the whole 2,800,000 impression
        gap sits on the buy as its open shortfall.

        PRD: "The buy's `open_shortfall_impressions` is the live measure of what
        the seller still owes: it is the shortfall computed above, reduced by the
        buy's `made_good_impressions` and by its `waived_impressions`, and floored
        at 0 so it never reads negative."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        _accept_the_post_buy_report(api, world)

        buy = fx.read_buy(api, world["buy_id"])
        assert_impressions(
            buy, "open_shortfall_impressions", DELIVERY_SHORTFALL_IMPRESSIONS
        )

    def test_link_three_opens_one_make_good_the_request_never_mentioned(self, api):
        """The acceptance body names no make-good, yet exactly one OPEN make-good
        is discoverable on the buy, carrying no offer at all.

        PRD: "The new record starts with `offered_forecast_id`,
        `offered_window_start`, `offered_window_end` and `rejection_reason` all
        null, `offered_impressions` at 0, `offer_round` at 0 and
        `waived_credit_cents` at 0."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        _accept_the_post_buy_report(api, world)

        rows, meta = validate_paginated(
            api.list_make_goods(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert meta["total_count"] == 1, (
            f"expected exactly one make-good on the buy, got {meta['total_count']}"
        )
        make_good = rows[0]
        assert make_good["status"] == MakeGoodStatus.OPEN.value, (
            f"expected the make-good at OPEN, got {make_good['status']}"
        )
        assert make_good["offer_round"] == 0, (
            f"a brand-new make-good carries offer_round 0, got {make_good['offer_round']}"
        )
        assert_impressions(make_good, "offered_impressions", 0)

    def test_link_three_freezes_the_shortfall_and_prices_it_at_the_agreed_cpm(
        self, api
    ):
        """The make-good freezes 2,800,000 impressions and values them at the
        agreed CPM of 2200, giving 6,160,000 cents.

        PRD: "Its `shortfall_impressions` is frozen from the buy's
        `open_shortfall_impressions` at that moment, and its
        `shortfall_value_cents` is that frozen shortfall divided by 1000 and
        multiplied by the buy's `agreed_cpm_cents`, rounded half up to a whole
        cent."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        _accept_the_post_buy_report(api, world)

        make_good = fx.only_make_good(api, world["buy_id"])
        assert_impressions(
            make_good, "shortfall_impressions", DELIVERY_SHORTFALL_IMPRESSIONS
        )
        assert_cents(
            make_good, "shortfall_value_cents", DELIVERY_SHORTFALL_VALUE_CENTS
        )

    def test_link_four_moves_the_sellers_open_make_good_exposure(self, api):
        """The seller's open exposure grows 0 to 2,800,000 while its scheduled
        exposure — the counter that consumes capacity — stays at 0.

        PRD: "Because that make-good is now `OPEN`, the seller's
        `open_make_good_impressions` is recomputed and grows by the frozen
        shortfall."

        Design: Difficulty/transitive_cascade/delivery_acceptance_cascades_into_seller_make_good_exposure
        """
        world = _delivery_shortfall_world(api)
        _accept_the_post_buy_report(api, world)

        seller = fx.read_seller(api, world["seller_id"])
        assert_impressions(
            seller, "open_make_good_impressions", DELIVERY_SHORTFALL_IMPRESSIONS
        )
        assert_impressions(seller, "scheduled_make_good_impressions", 0)
