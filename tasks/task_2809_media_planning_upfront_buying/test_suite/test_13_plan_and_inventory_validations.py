"""Validation corners of the plan, the inventory hold and the settlement path.

Each test drives one declared rejection — an oversubscribed percentage split, a
locked plan, a replayed submission, a backwards clock, an out-of-flight reported
period, an oversold avail, an under-covering unit mix, an unbillable period, a
replayed airing settlement and an avail belonging to another seller — and then
proves the refused write left no trace behind it.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    MEASUREMENT_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_cents,
    assert_impressions,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ==========================================================================
# The one plan, seller, avail and buy shape every instance in this file shares
# ==========================================================================
#: The brand the design registers, with explicit terms and liability flag.
_ADVERTISER = {
    "name": "Cascadia Beverage",
    "category_code": "BEVERAGE",
    "credit_limit_cents": 500_000_000,
    "payment_terms_days": 30,
    "sequential_liability_enabled": True,
}

#: The seller the design registers, able to deliver on three platforms.
_SELLER = {
    "name": "Harbor Broadcasting",
    "platform_types": ["LINEAR", "CTV", "DIGITAL"],
    "make_good_capacity_impressions": 50_000_000,
}

#: A ten-million-cent November-December campaign against a 120 million universe.
_CAMPAIGN = {
    "name": "Q4 Linear Base",
    "target_demo": "A25-54",
    "universe_thousands": 120_000,
    "reach_goal_pct": 60.00,
    "frequency_goal": 4.00,
    "total_budget_cents": 10_000_000,
    "flight_start": "2026-11-01T00:00:00Z",
    "flight_end": "2026-12-31T23:59:59Z",
    "fiscal_quarter": "2026Q4",
}

#: The single allocation that takes the whole plan in one line.
_WHOLE_PLAN_ALLOCATION = {
    "channel": "LINEAR_TV",
    "allocation_pct": 100.00,
    "planned_cpm_cents": 2000,
    "planned_market": "UPFRONT",
    "primary_daypart": "PRIME",
}

#: The avail the buy is served from: exactly ten million prime linear impressions.
_AVAIL = {
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

#: The agency's opening position on that avail's inventory.
_NEGOTIATION = {
    "market": "UPFRONT",
    "channel": "LINEAR_TV",
    "requested_impressions": 1_000_000,
    "opening_cpm_cents": 2000,
    "guarantee_pct": 100,
    "make_good_provision": "MAKE_GOOD_UNITS",
    "option_pct_ceiling": 25,
}

#: The seller counter the agency accepts, freezing a million impressions at 2200.
_COUNTER_CPM_CENTS = 2200
_COUNTER_IMPRESSIONS = 1_000_000

#: The single unit line, covering the whole guarantee inside November.
_UNIT = {
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

#: The instant the design moves the clock to before any airing is settled.
_AFTER_AIR_WINDOW = "2026-12-01T00:00:00Z"


def _drafted_plan(api):
    """One advertiser and one DRAFT campaign carrying a single 100.00 percent line."""
    advertiser = fx.register_advertiser(api, **_ADVERTISER)
    campaign = fx.open_campaign(api, advertiser["id"], **_CAMPAIGN)
    allocation = fx.add_allocation(api, campaign["id"], **_WHOLE_PLAN_ALLOCATION)
    return {
        "advertiser_id": advertiser["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
    }


def _submitted_plan(api):
    """The same plan, submitted and waiting on the client."""
    world = _drafted_plan(api)
    fx.submit_plan(api, world["campaign_id"])
    return world


def _approved_plan(api):
    """The same plan, approved by the owning client and therefore locked."""
    world = _submitted_plan(api)
    fx.approve_plan(api, world["campaign_id"], world["advertiser_id"])
    return world


def _published_avail(api, seller_id, **overrides):
    """File and publish one avail against the named seller."""
    spec = dict(_AVAIL)
    spec.update(overrides)
    avail = fx.file_avail(api, seller_id, **spec)
    return fx.publish_avail(api, avail["id"], seller_id)


def _accepted_buy(api):
    """An approved plan, a published avail and a buy the agency has just frozen."""
    world = _approved_plan(api)
    seller = fx.register_seller(api, **_SELLER)
    avail = _published_avail(api, seller["id"])
    negotiation = fx.open_negotiation(
        api,
        world["campaign_id"],
        seller["id"],
        world["allocation_id"],
        **_NEGOTIATION,
    )
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=_COUNTER_CPM_CENTS,
        counter_impressions=_COUNTER_IMPRESSIONS,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    world.update(
        {
            "seller_id": seller["id"],
            "forecast_id": avail["id"],
            "negotiation_id": negotiation["id"],
            "buy_id": buy["id"],
        }
    )
    return world


def _add_unit(api, world, **overrides):
    """Add the design's single unit line to the buy, with optional overrides."""
    spec = dict(_UNIT)
    spec.update(overrides)
    return fx.add_unit(api, world["buy_id"], world["forecast_id"], **spec)


def _placed_buy(api, **unit_overrides):
    """A PLACED buy carrying one unit line that covers the whole guarantee."""
    world = _accepted_buy(api)
    world["unit_id"] = _add_unit(api, world, **unit_overrides)["id"]
    fx.place_buy(api, world["buy_id"], world["campaign_id"])
    return world


def _allocation_count(api, campaign_id):
    """How many channel allocations the campaign currently carries."""
    _, meta = validate_paginated(
        api.list_channel_allocations(PLANNER_HEADERS, params={"campaign_id": campaign_id})
    )
    return meta["total_count"]


def _unit_count(api, buy_id):
    """How many unit lines the buy currently carries."""
    _, meta = validate_paginated(
        api.list_buy_units(BUYER_HEADERS, params={"buy_id": buy_id})
    )
    return meta["total_count"]


# ==========================================================================
# Corner/validations/an_allocation_that_pushes_the_plan_above_one_hundred_percent_is_rejected
# ==========================================================================
class TestAllocationAboveOneHundredPercent:
    """A plan already summing to 100.00 admits not even a hundredth of a point."""

    def test_a_hundredth_of_a_point_over_the_ceiling_is_refused(self, api):
        """A second 0.01 percent CTV line on a plan that already sums to 100.00 is
        refused and the campaign keeps its single allocation and its full
        allocated_budget_cents of 10,000,000.

        PRD: "The percentage split may never be oversubscribed: if adding this
        allocation's `allocation_pct` to the sum already carried by the campaign's
        `DRAFT` and `LOCKED` allocations would take that sum above 100.00, the
        request is rejected with `ERR_ALLOCATION_PCT_SUM_INVALID`."

        Design: Corner/validations/an_allocation_that_pushes_the_plan_above_one_hundred_percent_is_rejected
        """
        world = _drafted_plan(api)

        response = api.create_channel_allocation(
            fa.channel_allocation_payload(
                world["campaign_id"],
                channel="CTV",
                allocation_pct=0.01,
                planned_cpm_cents=1500,
                planned_market="UPFRONT",
                primary_daypart="DIGITAL_ANY",
            ),
            PLANNER_HEADERS,
        )

        validate_error(response, ApiErrorId.ALLOCATION_PCT_SUM_INVALID, 422)
        assert _allocation_count(api, world["campaign_id"]) == 1
        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_cents(campaign, "allocated_budget_cents", 10_000_000)
        assert campaign["version"] == 2


# ==========================================================================
# Corner/validations/a_new_allocation_on_an_approved_plan_is_rejected_as_locked
# ==========================================================================
class TestAllocationOnApprovedPlanIsLocked:
    """The lock check outranks the percentage-sum check on the same request."""

    def test_the_lock_is_reported_rather_than_the_percentage_sum(self, api):
        """A 5.00 percent addition that would also break the 100.00 percent sum
        reports the lock, leaves the approved plan's single allocation LOCKED and
        adds nothing to the campaign.

        PRD: "And an approved plan is not editable through the back door: if any
        allocation of the campaign currently sits at `LOCKED`, a new allocation is
        rejected with `ERR_ALLOCATION_LOCKED`."

        Design: Corner/validations/a_new_allocation_on_an_approved_plan_is_rejected_as_locked
        """
        world = _approved_plan(api)

        response = api.create_channel_allocation(
            fa.channel_allocation_payload(
                world["campaign_id"],
                channel="CTV",
                allocation_pct=5.00,
                planned_cpm_cents=1500,
                planned_market="UPFRONT",
                primary_daypart="DIGITAL_ANY",
            ),
            PLANNER_HEADERS,
        )

        validate_error(response, ApiErrorId.ALLOCATION_LOCKED, 409)
        assert fx.read_allocation(api, world["allocation_id"])["status"] == "LOCKED"
        assert _allocation_count(api, world["campaign_id"]) == 1
        campaign = fx.read_campaign(api, world["campaign_id"])
        assert campaign["plan_status"] == "APPROVED"
        assert campaign["version"] == 4


# ==========================================================================
# Corner/validations/resubmitting_a_plan_that_is_already_pending_approval_is_rejected
# ==========================================================================
class TestResubmittingAPendingPlan:
    """Submission is defined only from DRAFT and REVISION_REQUIRED."""

    def test_a_second_submission_does_not_restamp_the_plan(self, api):
        """A second submission while the plan sits in PENDING_CLIENT_APPROVAL is
        refused and the campaign's version stays at 3.

        PRD: "Submitting a plan that is already `PENDING_CLIENT_APPROVAL` or
        already `APPROVED` is rejected with
        `ERR_CAMPAIGN_PLAN_NOT_IN_EXPECTED_STATE`."

        Design: Corner/validations/resubmitting_a_plan_that_is_already_pending_approval_is_rejected
        """
        world = _submitted_plan(api)

        response = api.submit_plan(world["campaign_id"], None, PLANNER_HEADERS)

        validate_error(
            response, ApiErrorId.CAMPAIGN_PLAN_NOT_IN_EXPECTED_STATE, 409
        )
        campaign = fx.read_campaign(api, world["campaign_id"])
        assert campaign["plan_status"] == "PENDING_CLIENT_APPROVAL"
        assert campaign["version"] == 3


# ==========================================================================
# Corner/validations/moving_the_logical_clock_backwards_is_rejected
# ==========================================================================
class TestClockMovesForwardOnly:
    """A backwards clock request is refused and leaves the reading where it was."""

    def test_the_refused_rewind_leaves_the_air_window_elapsed(self, api):
        """After the clock has been moved to 2026-12-01T00:00:00Z a request for
        2026-11-01T00:00:00Z is refused, and the unit whose air window ended
        2026-11-30T23:59:59Z still settles AIRED at 1,000,000 impressions.

        PRD: "An `AgencyController` may advance it by supplying a `current_utc`
        instant to the clock-setting capability; the clock only ever moves forward,
        and a request naming an instant earlier than the current reading is rejected
        with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

        Design: Corner/validations/moving_the_logical_clock_backwards_is_rejected
        """
        world = _placed_buy(api)
        fx.move_clock(api, _AFTER_AIR_WINDOW)

        rewind = api.move_clock_to("2026-11-01T00:00:00Z", CONTROLLER_HEADERS)
        validate_error(rewind, ApiErrorId.CLOCK_NOT_MONOTONIC, 422)

        settled = validate_success(
            api.settle_airing(
                world["unit_id"],
                fa.settle_aired_payload(1_000_000),
                make_seller_rep_headers(world["seller_id"]),
            ),
            200,
        )
        assert settled["status"] == "AIRED"
        assert_impressions(settled, "actual_impressions", 1_000_000)
        assert_impressions(
            fx.read_unit(api, world["unit_id"]), "actual_impressions", 1_000_000
        )


# ==========================================================================
# Corner/validations/a_delivery_report_period_before_the_flight_start_is_rejected
# ==========================================================================
class TestReportPeriodBeforeTheFlight:
    """An October period against a November-December flight files nothing."""

    def test_an_october_period_leaves_the_provisional_view_empty(self, api):
        """A measurement vendor's report covering October is refused, no report row
        is created and the buy's provisional credit stays 0 at an index of 0.0000.

        PRD: "Temporally, `period_start` must not fall after `period_end`, the whole
        period must lie inside the buy's flight window from `flight_start` to
        `flight_end`, and `period_end` must be at or before the logical clock — no
        one reports the future."

        Design: Corner/validations/a_delivery_report_period_before_the_flight_start_is_rejected
        """
        world = _placed_buy(api)

        response = api.create_delivery_report(
            fa.delivery_report_payload(
                world["buy_id"],
                500_000,
                400_000,
                period_start="2026-10-01T00:00:00Z",
                period_end="2026-10-31T23:59:59Z",
                measurement_basis="LINEAR_C3",
            ),
            MEASUREMENT_HEADERS,
        )

        validate_error(response, ApiErrorId.REPORT_PERIOD_OUTSIDE_FLIGHT, 422)
        _, meta = validate_paginated(
            api.list_delivery_reports(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert meta["total_count"] == 0
        buy = fx.read_buy(api, world["buy_id"])
        assert_impressions(buy, "credited_impressions_provisional", 0)
        assert_pct4(buy, "provisional_delivery_index", 0.0000)


# ==========================================================================
# Corner/validations/a_unit_larger_than_the_remaining_avail_is_rejected
# ==========================================================================
class TestUnitLargerThanTheAvail:
    """One impression more than the avail holds is one impression too many."""

    def test_the_oversized_line_leaves_the_avail_whole(self, api):
        """A line projecting 10,000,001 impressions against a 10,000,000 impression
        avail is refused, the avail keeps its full availability at PUBLISHED version
        2 and the buy carries no line at all.

        PRD: "A request for exactly the remaining availability succeeds; a request
        for one impression more is refused with `ERR_FORECAST_AVAIL_EXCEEDED`."

        Design: Corner/validations/a_unit_larger_than_the_remaining_avail_is_rejected
        """
        world = _accepted_buy(api)

        spec = dict(_UNIT)
        spec.update({"units": 5, "projected_impressions": 10_000_001})
        response = api.add_buy_unit(
            world["buy_id"],
            fa.buy_unit_payload(world["forecast_id"], **spec),
            BUYER_HEADERS,
        )

        validate_error(response, ApiErrorId.FORECAST_AVAIL_EXCEEDED, 409)
        avail = fx.read_avail(api, world["forecast_id"])
        assert_impressions(avail, "available_impressions", 10_000_000)
        assert avail["status"] == "PUBLISHED"
        assert avail["version"] == 2
        assert _unit_count(api, world["buy_id"]) == 0
        assert_impressions(fx.read_buy(api, world["buy_id"]), "placed_impressions", 0)


# ==========================================================================
# Corner/validations/placing_a_buy_whose_units_undercover_the_guarantee_is_rejected
# ==========================================================================
class TestPlacementWithShortCoverage:
    """Coverage is compared with >=, so one impression short blocks the placement."""

    def test_one_impression_short_commits_nothing(self, api):
        """A placement whose single line projects 999,999 against a 1,000,000
        impression guarantee is refused, the buy stays PENDING_PLACEMENT and neither
        the allocation nor the campaign commits a cent.

        PRD: "Coverage exactly equal to the guarantee is sufficient; anything less
        is refused with `ERR_UNIT_COVERAGE_SHORT`."

        Design: Corner/validations/placing_a_buy_whose_units_undercover_the_guarantee_is_rejected
        """
        world = _accepted_buy(api)
        _add_unit(api, world, projected_impressions=999_999)
        campaign_version = fx.campaign_version(api, world["campaign_id"])

        response = api.place_buy(
            world["buy_id"], fa.place_payload(campaign_version), BUYER_HEADERS
        )

        validate_error(response, ApiErrorId.UNIT_COVERAGE_SHORT, 409)
        buy = fx.read_buy(api, world["buy_id"])
        assert buy["buy_status"] == "PENDING_PLACEMENT"
        assert_impressions(buy, "placed_impressions", 999_999)
        allocation = fx.read_allocation(api, world["allocation_id"])
        assert_cents(allocation, "committed_cents", 0)
        assert allocation["posture"] == "WITHIN_PLAN"
        campaign = fx.read_campaign(api, world["campaign_id"])
        assert_cents(campaign, "committed_gross_cents", 0)
        assert campaign["version"] == 4


# ==========================================================================
# Corner/validations/invoicing_a_period_with_no_aired_unit_is_rejected
# ==========================================================================
class TestInvoicingAPeriodWithNoAiredUnit:
    """A period whose lines have not aired yet is not a billable period."""

    def test_a_november_draft_over_a_scheduled_line_creates_no_invoice(self, api):
        """With the buy's only line still SCHEDULED, a November billing period is
        refused, no invoice row exists for the buy and the buy stays UNBILLED.

        PRD: "If the period captures no such line at all, the draft is refused with
        `ERR_NO_BILLABLE_LINES`."

        Design: Corner/validations/invoicing_a_period_with_no_aired_unit_is_rejected
        """
        world = _placed_buy(api)

        response = api.create_invoice(
            fa.invoice_payload(
                world["buy_id"],
                billing_period_start="2026-11-01T00:00:00Z",
                billing_period_end="2026-11-30T23:59:59Z",
            ),
            CONTROLLER_HEADERS,
        )

        validate_error(response, ApiErrorId.NO_BILLABLE_LINES, 422)
        _, meta = validate_paginated(
            api.list_invoices(CONTROLLER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert meta["total_count"] == 0
        buy = fx.read_buy(api, world["buy_id"])
        assert buy["settlement_status"] == "UNBILLED"


# ==========================================================================
# Corner/validations/settling_the_same_airing_twice_is_rejected
# ==========================================================================
class TestSettlingTheSameAiringTwice:
    """An AIRED line has left the settleable set, so the replay is refused."""

    def test_the_replayed_settlement_does_not_overwrite_the_actuals(self, api):
        """A second settlement naming 10 impressions against an already AIRED line
        is refused and the line keeps its 1,000,000 actual impressions at version 2.

        PRD: "Only a line whose `status` is `SCHEDULED` or `MAKE_GOOD_SCHEDULED` can
        be settled; any other line is refused with `ERR_UNIT_NOT_SCHEDULED`."

        Design: Corner/validations/settling_the_same_airing_twice_is_rejected
        """
        world = _placed_buy(api)
        fx.move_clock(api, _AFTER_AIR_WINDOW)
        seller_headers = make_seller_rep_headers(world["seller_id"])
        fx.settle_aired(api, world["unit_id"], world["seller_id"], 1_000_000)

        response = api.settle_airing(
            world["unit_id"], fa.settle_aired_payload(10), seller_headers
        )

        validate_error(response, ApiErrorId.UNIT_NOT_SCHEDULED, 409)
        unit = fx.read_unit(api, world["unit_id"])
        assert unit["status"] == "AIRED"
        assert_impressions(unit, "actual_impressions", 1_000_000)
        assert unit["version"] == 2


# ==========================================================================
# Corner/validations/a_unit_on_another_sellers_avail_is_rejected
# ==========================================================================
#: The rival seller whose inventory the buy has no claim on.
_RIVAL_SELLER = {
    "name": "Ridgeline Media",
    "platform_types": ["LINEAR"],
    "make_good_capacity_impressions": 4_000_000,
}

#: The rival's own published prime avail, cheaper and smaller than Harbor's.
_RIVAL_AVAIL = {
    "program": "Ridgeline Prime",
    "total_impressions": 8_000_000,
    "forecast_cpm_cents": 2100,
}


class TestUnitOnAnotherSellersAvail:
    """The avail a line draws on must belong to the buy's own seller."""

    def test_the_rivals_avail_is_refused_and_left_untouched(self, api):
        """A line on a second seller's identically-shaped prime avail is refused,
        that avail keeps its whole 8,000,000 impressions at PUBLISHED and the buy
        carries no line.

        PRD: "Then the avail must be compatible with the buy in four respects — it
        must belong to the buy's `seller_id`, its `market` must equal the buy's
        `market`, its `platform` must be compatible with the buy's `channel`, and
        its own window must lie inside the buy's flight window running from
        `flight_start` to `flight_end`."

        Design: Corner/validations/a_unit_on_another_sellers_avail_is_rejected
        """
        world = _accepted_buy(api)
        rival = fx.register_seller(api, **_RIVAL_SELLER)
        rival_avail = _published_avail(api, rival["id"], **_RIVAL_AVAIL)

        spec = dict(_UNIT)
        spec.update(
            {
                "program": "Ridgeline Prime",
                "unit_rate_cents": 2_100_000,
                "projected_impressions": 1_000_000,
            }
        )
        response = api.add_buy_unit(
            world["buy_id"],
            fa.buy_unit_payload(rival_avail["id"], **spec),
            BUYER_HEADERS,
        )

        validate_error(response, ApiErrorId.UNIT_FORECAST_MISMATCH, 422)
        refreshed = fx.read_avail(api, rival_avail["id"])
        assert_impressions(refreshed, "available_impressions", 8_000_000)
        assert refreshed["status"] == "PUBLISHED"
        assert _unit_count(api, world["buy_id"]) == 0
