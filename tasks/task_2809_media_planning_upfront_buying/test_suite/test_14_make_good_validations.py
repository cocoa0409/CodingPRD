"""Make-good remedy validations, plus the two adjacent guards of the same design slice.

The file pins the six corner instances that turn on an offered make-good — the frozen
shortfall, the offered window, the seller's capacity ceiling, the three-offer cap,
acceptance with no offer on the table, and a buy whose remedy is ``NONE`` — together
with the allocation-to-campaign guard on negotiation creation and the terminal funding
axis of a fully funded campaign.
"""

from test_helpers import (
    BUYER_HEADERS,
    ApiErrorId,
    assert_buy_axes,
    assert_campaign_axes,
    assert_cents,
    assert_impressions,
    factories as fa,
    fixtures as fx,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ==========================================================================
# The calendar the design's base fixture runs on
# ==========================================================================
_FLIGHT_START = "2026-11-01T00:00:00Z"
_FLIGHT_END = "2026-12-31T23:59:59Z"

#: The seller's avail fills the whole flight, so a unit line fits inside it.
_AVAIL_WINDOW_START = "2026-11-01T00:00:00Z"
_AVAIL_WINDOW_END = "2026-12-31T23:59:59Z"

_AIR_WINDOW_START = "2026-11-02T00:00:00Z"
_AIR_WINDOW_END = "2026-11-30T23:59:59Z"

#: The measured period runs to the flight end, which is what makes the report final.
_PERIOD_START = "2026-12-01T00:00:00Z"
_PERIOD_END = "2026-12-31T23:59:59Z"

#: A make-good may not air in the past, so replacement inventory is offered from a
#: second avail whose window opens after the reporting clock.
_REPLACEMENT_WINDOW_START = "2027-01-01T00:00:00Z"
_REPLACEMENT_WINDOW_END = "2027-02-28T00:00:00Z"
_OFFER_WINDOW_START = "2027-01-05T00:00:00Z"
_OFFER_WINDOW_END = "2027-01-10T23:59:59Z"

# ==========================================================================
# The figures the base fixture freezes
# ==========================================================================
_CAMPAIGN_BUDGET_CENTS = 10_000_000
_GUARANTEED_IMPRESSIONS = 1_000_000
_AGREED_CPM_CENTS = 2200
_DELIVERED_IMPRESSIONS = 1_000_000
_DELIVERED_DEMO_IMPRESSIONS = 900_000

#: The gap the acceptance cascade freezes on the make-good, and its contract value.
_SHORTFALL_IMPRESSIONS = 100_000
_SHORTFALL_VALUE_CENTS = 220_000

#: The seller's make-good ceiling, none of it yet scheduled.
_SELLER_CAPACITY_IMPRESSIONS = 50_000_000

#: The avail's stock, and what one 1,000,000 impression line leaves of it.
_AVAIL_TOTAL_IMPRESSIONS = 10_000_000
_AVAIL_REMAINING_IMPRESSIONS = 9_000_000

_REJECTION_REASON = "daypart does not match the original schedule"


def _advertiser(api):
    """The brand the whole slice is bought for."""
    return fx.register_advertiser(
        api,
        name="Cascadia Beverage",
        category_code="BEVERAGE",
        credit_limit_cents=500_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )


def _seller(api):
    """The media seller carrying a 50,000,000 impression make-good ceiling."""
    return fx.register_seller(
        api,
        name="Harbor Broadcasting",
        platform_types=["LINEAR", "CTV", "DIGITAL"],
        make_good_capacity_impressions=_SELLER_CAPACITY_IMPRESSIONS,
    )


def _base_campaign(api, advertiser_id):
    """The Q4 linear campaign shell, budgeted at 10,000,000 cents."""
    return fx.open_campaign(
        api,
        advertiser_id,
        name="Q4 Linear Base",
        target_demo="A25-54",
        universe_thousands=120_000,
        reach_goal_pct=60.0,
        frequency_goal=4.0,
        total_budget_cents=_CAMPAIGN_BUDGET_CENTS,
        flight_start=_FLIGHT_START,
        flight_end=_FLIGHT_END,
        fiscal_quarter="2026Q4",
    )


def _linear_allocation(api, campaign_id):
    """The single prime linear allocation claiming the whole budget."""
    return fx.add_allocation(
        api,
        campaign_id,
        channel="LINEAR_TV",
        allocation_pct=100.00,
        planned_cpm_cents=2000,
        planned_market="UPFRONT",
        primary_daypart="PRIME",
    )


def _shortfall_world(api, make_good_provision="MAKE_GOOD_UNITS"):
    """A PLACED buy guaranteeing 1,000,000 impressions whose accepted post-buy-final
    report of 900,000 demo impressions left one OPEN make-good.

    The make-good's frozen shortfall is 100,000 impressions worth 220,000 cents, the
    seller has none of its 50,000,000 impression ceiling scheduled, and the avail is
    left with 9,000,000 of its 10,000,000 impressions.  The logical clock is moved to
    the reported period end, because no one reports the future.
    """
    advertiser = _advertiser(api)
    seller = _seller(api)
    campaign = _base_campaign(api, advertiser["id"])
    allocation = _linear_allocation(api, campaign["id"])
    fx.submit_plan(api, campaign["id"])
    fx.approve_plan(api, campaign["id"], advertiser["id"])
    avail = fx.file_avail(
        api,
        seller["id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Harbor Nightly",
        platform="LINEAR",
        window_start=_AVAIL_WINDOW_START,
        window_end=_AVAIL_WINDOW_END,
        total_impressions=_AVAIL_TOTAL_IMPRESSIONS,
        forecast_cpm_cents=_AGREED_CPM_CENTS,
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
        requested_impressions=_GUARANTEED_IMPRESSIONS,
        opening_cpm_cents=2000,
        guarantee_pct=100,
        make_good_provision=make_good_provision,
        option_pct_ceiling=25,
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=_AGREED_CPM_CENTS,
        counter_impressions=_GUARANTEED_IMPRESSIONS,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    unit = fx.add_unit(
        api,
        buy["id"],
        avail["id"],
        daypart="PRIME",
        program="Harbor Nightly",
        platform="LINEAR",
        units=1,
        unit_rate_cents=2_200_000,
        projected_impressions=_GUARANTEED_IMPRESSIONS,
        air_window_start=_AIR_WINDOW_START,
        air_window_end=_AIR_WINDOW_END,
        exclusive=False,
    )
    fx.place_buy(api, buy["id"], campaign["id"])
    fx.move_clock(api, _PERIOD_END)
    report = fx.file_report(
        api,
        buy["id"],
        _DELIVERED_IMPRESSIONS,
        _DELIVERED_DEMO_IMPRESSIONS,
        seller_id=seller["id"],
        measurement_basis="LINEAR_C3",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    fx.accept_report(api, report["id"])
    make_good = fx.only_make_good(api, buy["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "seller_headers": make_seller_rep_headers(seller["id"]),
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "buy_id": buy["id"],
        "unit_id": unit["id"],
        "report_id": report["id"],
        "make_good_id": make_good["id"],
        "make_good": make_good,
    }


def _replacement_avail(api, seller_id, total_impressions=30_000_000):
    """A second published avail of the same seller, running after the reporting clock."""
    return fx.published_avail(
        api,
        seller_id,
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Harbor Late Edition",
        platform="LINEAR",
        window_start=_REPLACEMENT_WINDOW_START,
        window_end=_REPLACEMENT_WINDOW_END,
        total_impressions=total_impressions,
        forecast_cpm_cents=_AGREED_CPM_CENTS,
        exclusivity_mode="SHARED",
    )


def _offer(api, world, forecast_id, offered_impressions, **overrides):
    """The seller's raw offer of replacement inventory, returned unvalidated."""
    payload = fa.make_good_offer_payload(
        forecast_id,
        offered_impressions,
        offered_window_start=overrides.pop("offered_window_start", _OFFER_WINDOW_START),
        offered_window_end=overrides.pop("offered_window_end", _OFFER_WINDOW_END),
        **overrides,
    )
    return api.offer_make_good(world["make_good_id"], payload, world["seller_headers"])


def _read_make_good(api, world):
    return validate_success(api.get_make_good(world["make_good_id"], BUYER_HEADERS))


def _read_seller(api, world):
    return validate_success(api.get_seller(world["seller_id"], BUYER_HEADERS))


def _read_avail(api, world):
    return validate_success(
        api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
    )


def _read_buy(api, world):
    return validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))


# ==========================================================================
# Instance — a_negotiation_citing_another_campaigns_allocation_is_rejected
# ==========================================================================
def _two_campaign_world(api):
    """Two campaigns of the same brand, each carrying its own LINEAR_TV allocation."""
    advertiser = _advertiser(api)
    seller = _seller(api)
    first = _base_campaign(api, advertiser["id"])
    first_allocation = _linear_allocation(api, first["id"])
    second = fx.open_campaign(
        api,
        advertiser["id"],
        name="Q4 Digital Companion",
        target_demo="A18-34",
        universe_thousands=120_000,
        reach_goal_pct=50.0,
        frequency_goal=3.0,
        total_budget_cents=8_000_000,
        flight_start=_FLIGHT_START,
        flight_end=_FLIGHT_END,
        fiscal_quarter="2026Q4",
    )
    second_allocation = _linear_allocation(api, second["id"])
    return {
        "seller_id": seller["id"],
        "first_campaign_id": first["id"],
        "first_allocation_id": first_allocation["id"],
        "second_campaign_id": second["id"],
        "second_allocation_id": second_allocation["id"],
    }


class TestNegotiationAllocationBelongsToTheCampaign:
    """The referential guard on negotiation creation."""

    def test_an_allocation_of_another_campaign_is_refused(self, api):
        """Both identifiers resolve and the channels agree, yet the negotiation is
        refused because the cited allocation hangs off the other campaign, and neither
        the campaign nor the allocation ends up carrying a negotiation.

        PRD: "An allocation from another campaign, or one carrying a different
        channel, is rejected with `ERR_ALLOCATION_CAMPAIGN_MISMATCH`."

        Design: Corner/validations/a_negotiation_citing_another_campaigns_allocation_is_rejected
        """
        world = _two_campaign_world(api)
        response = api.create_negotiation(
            fa.negotiation_payload(
                world["first_campaign_id"],
                world["seller_id"],
                world["second_allocation_id"],
                market="UPFRONT",
                channel="LINEAR_TV",
                requested_impressions=1_000_000,
                opening_cpm_cents=2000,
            ),
            BUYER_HEADERS,
        )
        validate_error(response, ApiErrorId.ALLOCATION_CAMPAIGN_MISMATCH, 422)

        _, by_campaign = validate_paginated(
            api.list_negotiations(
                BUYER_HEADERS, params={"campaign_id": world["first_campaign_id"]}
            )
        )
        assert by_campaign["total_count"] == 0, (
            "the refused negotiation must not be recorded against the campaign"
        )
        _, by_allocation = validate_paginated(
            api.list_negotiations(
                BUYER_HEADERS,
                params={"channel_allocation_id": world["second_allocation_id"]},
            )
        )
        assert by_allocation["total_count"] == 0, (
            "the refused negotiation must not be recorded against the allocation"
        )


# ==========================================================================
# Instance — a_make_good_offer_below_the_frozen_shortfall_is_rejected
# ==========================================================================
class TestOfferBelowTheFrozenShortfall:
    """The coverage comparison is inclusive, so one impression short is short."""

    def test_an_offer_one_impression_below_the_shortfall_is_refused(self, api):
        """An offer of 99,999 impressions against a shortfall frozen at 100,000 is
        refused, the make-good stays OPEN at offer round 0 and version 1, and the
        seller's open exposure still reads the whole 100,000 gap.

        PRD: "The offer must fully cover what is owed — `offered_impressions` must be
        at least the make-good's frozen `shortfall_impressions`, and an offer exactly
        equal to it is acceptable while anything less is refused with
        `ERR_MAKE_GOOD_OFFER_INSUFFICIENT`."

        Design: Corner/validations/a_make_good_offer_below_the_frozen_shortfall_is_rejected
        """
        world = _shortfall_world(api)
        replacement = _replacement_avail(api, world["seller_id"])

        response = _offer(api, world, replacement["id"], _SHORTFALL_IMPRESSIONS - 1)
        validate_error(response, ApiErrorId.MAKE_GOOD_OFFER_INSUFFICIENT, 422)

        make_good = _read_make_good(api, world)
        assert make_good["status"] == "OPEN"
        assert make_good["offer_round"] == 0
        assert make_good["version"] == 1
        assert_impressions(make_good, "shortfall_impressions", _SHORTFALL_IMPRESSIONS)
        assert_cents(make_good, "shortfall_value_cents", _SHORTFALL_VALUE_CENTS)

        seller = _read_seller(api, world)
        assert_impressions(
            seller, "open_make_good_impressions", _SHORTFALL_IMPRESSIONS
        )
        assert_impressions(seller, "scheduled_make_good_impressions", 0)


# ==========================================================================
# Instance — a_make_good_window_outside_the_offered_avail_is_rejected
# ==========================================================================
class TestOfferWindowOutsideTheOfferedAvail:
    """The temporal rule is reached before either volume rule."""

    def test_a_january_window_on_a_december_avail_is_refused(self, api):
        """A replacement window running 2027-01-05 to 2027-01-10 cannot be carried by
        an avail whose own window closes on 2026-12-31, so the offer is refused even
        though its 100,000 impressions exactly cover the shortfall, and nothing about
        the offer is recorded on the make-good.

        PRD: "The offered window must lie inside the offered avail's own window from
        `window_start` to `window_end`, and `offered_window_start` must be at or after
        the logical clock, since a make-good cannot air in the past; a violation is
        refused with `ERR_MAKE_GOOD_WINDOW_INVALID`."

        Design: Corner/validations/a_make_good_window_outside_the_offered_avail_is_rejected
        """
        world = _shortfall_world(api)

        response = _offer(
            api,
            world,
            world["forecast_id"],
            _SHORTFALL_IMPRESSIONS,
            offered_window_start=_OFFER_WINDOW_START,
            offered_window_end=_OFFER_WINDOW_END,
        )
        validate_error(response, ApiErrorId.MAKE_GOOD_WINDOW_INVALID, 422)

        make_good = _read_make_good(api, world)
        assert make_good["status"] == "OPEN"
        assert make_good["offer_round"] == 0
        assert make_good["offered_forecast_id"] is None
        assert make_good["offered_window_start"] is None
        assert make_good["offered_window_end"] is None
        assert_impressions(make_good, "offered_impressions", 0)


# ==========================================================================
# Instance — a_make_good_offer_above_the_sellers_capacity_is_rejected
# ==========================================================================
class TestOfferAboveTheSellersCapacity:
    """Capacity is the ceiling less what is already scheduled, and nothing else."""

    def test_an_offer_beyond_the_unscheduled_ceiling_is_refused(self, api):
        """An offer of 60,000,000 impressions against a 50,000,000 impression ceiling
        with nothing yet scheduled is refused, the make-good stays OPEN at offer round
        0, and neither the seller's scheduled exposure nor the original avail moves.

        PRD: "Finally the seller must have the headroom: `offered_impressions` must be
        no greater than its `make_good_capacity_impressions` less its
        `scheduled_make_good_impressions`, and exceeding that headroom is refused with
        `ERR_MAKE_GOOD_CAPACITY_EXCEEDED`."

        Design: Corner/validations/a_make_good_offer_above_the_sellers_capacity_is_rejected
        """
        world = _shortfall_world(api)
        replacement = _replacement_avail(
            api, world["seller_id"], total_impressions=60_000_000
        )

        response = _offer(api, world, replacement["id"], 60_000_000)
        validate_error(response, ApiErrorId.MAKE_GOOD_CAPACITY_EXCEEDED, 409)

        make_good = _read_make_good(api, world)
        assert make_good["status"] == "OPEN"
        assert make_good["offer_round"] == 0

        seller = _read_seller(api, world)
        assert_impressions(seller, "scheduled_make_good_impressions", 0)

        avail = _read_avail(api, world)
        assert_impressions(
            avail, "available_impressions", _AVAIL_REMAINING_IMPRESSIONS
        )


# ==========================================================================
# Instance — a_fourth_make_good_offer_is_rejected_at_the_offer_cap
# ==========================================================================
class TestFourthOfferAtTheOfferCap:
    """The OPEN / OFFERED loop is bounded at three offers."""

    def test_a_fourth_offer_after_three_rejected_cycles_is_refused(self, api):
        """Three complete offer and rejection cycles leave the make-good OPEN at offer
        round 3 and version 7 carrying the last rejection reason, and a fourth
        otherwise valid offer of 100,000 impressions is refused, so the buy is still
        owed its whole 100,000 impression shortfall and no replacement line exists.

        PRD: "No more than three offers may be made on a single make-good: an offer
        whose effect would take `offer_round` past 3 is refused with
        `ERR_MAKE_GOOD_OFFER_CAP_REACHED`."

        Design: Corner/validations/a_fourth_make_good_offer_is_rejected_at_the_offer_cap
        """
        world = _shortfall_world(api)
        replacement = _replacement_avail(api, world["seller_id"])
        for _ in range(3):
            fx.offer_make_good(
                api,
                world["make_good_id"],
                world["seller_id"],
                replacement["id"],
                _SHORTFALL_IMPRESSIONS,
                offered_window_start=_OFFER_WINDOW_START,
                offered_window_end=_OFFER_WINDOW_END,
            )
            fx.reject_make_good(
                api, world["make_good_id"], rejection_reason=_REJECTION_REASON
            )

        response = _offer(api, world, replacement["id"], _SHORTFALL_IMPRESSIONS)
        validate_error(response, ApiErrorId.MAKE_GOOD_OFFER_CAP_REACHED, 409)

        make_good = _read_make_good(api, world)
        assert make_good["status"] == "OPEN"
        assert make_good["offer_round"] == 3
        assert make_good["version"] == 7
        assert make_good["rejection_reason"] == _REJECTION_REASON

        buy = _read_buy(api, world)
        assert_buy_axes(buy, stewardship_status="UNDER_DELIVERED")
        assert_impressions(
            buy, "open_shortfall_impressions", _SHORTFALL_IMPRESSIONS
        )

        _, meta = validate_paginated(
            api.list_buy_units(
                BUYER_HEADERS, params={"make_good_id": world["make_good_id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "a make-good that never reached SCHEDULED books no replacement line"
        )


# ==========================================================================
# Instance — accepting_a_make_good_that_has_no_offer_on_the_table_is_rejected
# ==========================================================================
class TestAcceptingAMakeGoodWithNoOffer:
    """Acceptance is defined only from OFFERED."""

    def test_accepting_an_open_make_good_is_refused(self, api):
        """A make-good the seller has never answered is still OPEN at version 1, so the
        agency's acceptance is refused before any avail check runs: the avail keeps its
        9,000,000 remaining impressions, the buy still carries only its one ordered
        line, and nothing has been made good.

        PRD: "Both `SCHEDULED` and `WAIVED` are terminal for a make-good, so any
        further offer, acceptance, rejection or waiver on it is refused with
        `ERR_ALREADY_TERMINAL`; offering against a make-good that is not `OPEN`, or
        accepting or rejecting one that is not `OFFERED`, is refused with
        `ERR_MAKE_GOOD_NOT_IN_EXPECTED_STATE`."

        Design: Corner/validations/accepting_a_make_good_that_has_no_offer_on_the_table_is_rejected
        """
        world = _shortfall_world(api)

        response = api.accept_make_good(world["make_good_id"], None, BUYER_HEADERS)
        validate_error(response, ApiErrorId.MAKE_GOOD_NOT_IN_EXPECTED_STATE, 409)

        make_good = _read_make_good(api, world)
        assert make_good["status"] == "OPEN"
        assert make_good["version"] == 1

        avail = _read_avail(api, world)
        assert_impressions(
            avail, "available_impressions", _AVAIL_REMAINING_IMPRESSIONS
        )

        _, meta = validate_paginated(
            api.list_buy_units(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert meta["total_count"] == 1, (
            "the refused acceptance must not add a replacement unit line"
        )

        buy = _read_buy(api, world)
        assert_impressions(buy, "made_good_impressions", 0)
        assert_buy_axes(buy, stewardship_status="UNDER_DELIVERED")


# ==========================================================================
# Instance — offering_a_make_good_on_a_no_remedy_buy_is_rejected
# ==========================================================================
class TestOfferOnANoRemedyBuy:
    """A remedy of NONE records the shortfall but bars the make-good."""

    def test_a_seller_offer_against_a_none_provision_buy_is_refused(self, api):
        """The negotiation froze the remedy at NONE, so the acceptance cascade still
        drives the buy to UNDER_DELIVERED and still opens a make-good for the 100,000
        impression gap, but the seller's otherwise valid 100,000 impression offer is
        refused and the offer round stays at 0.

        PRD: "The buy's `make_good_provision` must not be `NONE`, or the offer is
        refused with `ERR_MAKE_GOOD_NOT_PERMITTED`."

        Design: Corner/validations/offering_a_make_good_on_a_no_remedy_buy_is_rejected
        """
        world = _shortfall_world(api, make_good_provision="NONE")
        replacement = _replacement_avail(api, world["seller_id"])

        response = _offer(api, world, replacement["id"], _SHORTFALL_IMPRESSIONS)
        validate_error(response, ApiErrorId.MAKE_GOOD_NOT_PERMITTED, 409)

        buy = _read_buy(api, world)
        assert buy["make_good_provision"] == "NONE"
        assert_buy_axes(buy, stewardship_status="UNDER_DELIVERED")

        make_good = _read_make_good(api, world)
        assert make_good["status"] == "OPEN"
        assert make_good["offer_round"] == 0
        assert_impressions(make_good, "shortfall_impressions", _SHORTFALL_IMPRESSIONS)


# ==========================================================================
# Instance — funding_a_fully_funded_campaign_is_rejected
# ==========================================================================
class TestFundingAFullyFundedCampaign:
    """FUNDED is terminal on the funding axis, under its own error identifier."""

    def test_a_further_one_cent_deposit_is_refused(self, api):
        """A campaign whose 10,000,000 cent budget is already covered in full takes no
        further deposit: a one cent top-up is refused, and the campaign is left with
        exactly 10,000,000 funded cents, a FUNDED axis and the version its single
        accepted deposit produced.

        PRD: "`FUNDED` is terminal on this axis: a fully funded campaign takes no
        further deposits, and an attempt to fund one is rejected with
        `ERR_CAMPAIGN_ALREADY_FUNDED` rather than with the generic terminal-state
        error."

        Design: Corner/validations/funding_a_fully_funded_campaign_is_rejected
        """
        advertiser = _advertiser(api)
        campaign = _base_campaign(api, advertiser["id"])
        client_headers = make_advertiser_client_headers(advertiser["id"])
        fx.fund_campaign(
            api, campaign["id"], advertiser["id"], _CAMPAIGN_BUDGET_CENTS
        )

        response = api.fund_campaign(campaign["id"], fa.fund_payload(1), client_headers)
        validate_error(response, ApiErrorId.CAMPAIGN_ALREADY_FUNDED, 409)

        funded = validate_success(api.get_campaign(campaign["id"], client_headers))
        assert_cents(funded, "funded_cents", _CAMPAIGN_BUDGET_CENTS)
        assert_campaign_axes(funded, funding_status="FUNDED")
        assert funded["version"] == 2
