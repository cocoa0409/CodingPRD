"""The state-machine surface of the upfront buying domain.

Each test pins one declared machine claim: the initial state a freshly created
negotiation, buy or campaign axis occupies, a valid hop across one axis, the
conditional cascade a plan rejection runs, and the refusals raised by an
undefined hop, a terminal target or a replayed one-shot action.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    ApiErrorId,
    assert_allocation_posture,
    assert_buy_axes,
    assert_campaign_axes,
    assert_instant_field,
    cancel_window_1_close,
    cancel_window_2_close,
    delivery_index,
    factories as fa,
    fixtures as fx,
    get_success_data,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    option_window_close,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# The one calendar every instance in this file is computed against
# --------------------------------------------------------------------------
FLIGHT_START = "2026-11-01T00:00:00Z"
FLIGHT_END = "2026-12-31T23:59:59Z"
AIR_WINDOW_START = "2026-11-02T00:00:00Z"
AIR_WINDOW_END = "2026-11-30T23:59:59Z"

#: An instant after the reported period closes but inside the flight.
AFTER_REPORTED_PERIOD = "2026-12-01T00:00:00Z"

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
    "flight_start": FLIGHT_START,
    "flight_end": FLIGHT_END,
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
    "window_start": FLIGHT_START,
    "window_end": FLIGHT_END,
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
    "air_window_start": AIR_WINDOW_START,
    "air_window_end": AIR_WINDOW_END,
    "exclusive": False,
}

COUNTER_CPM_CENTS = 2200
COUNTER_IMPRESSIONS = 1_000_000
GUARANTEED_IMPRESSIONS = 1_000_000


# --------------------------------------------------------------------------
# Shared setup, layered so each instance names only the tier it needs
# --------------------------------------------------------------------------
def _advertiser_only(api):
    """One brand client on the agency's books."""
    advertiser = fx.register_advertiser(api, **ADVERTISER)
    return {
        "advertiser_id": advertiser["id"],
        "client_headers": make_advertiser_client_headers(advertiser["id"]),
    }


def _drafted_plan(api):
    """One advertiser, one campaign and one DRAFT hundred-per-cent allocation."""
    world = _advertiser_only(api)
    campaign = fx.open_campaign(api, world["advertiser_id"], **CAMPAIGN)
    allocation = fx.add_allocation(api, campaign["id"], **ALLOCATION)
    world["campaign_id"] = campaign["id"]
    world["allocation_id"] = allocation["id"]
    return world


def _submitted_plan(api):
    """That plan submitted and waiting on the client."""
    world = _drafted_plan(api)
    fx.submit_plan(api, world["campaign_id"])
    return world


def _approved_plan(api):
    """That plan approved by the owning client, its allocation locked."""
    world = _submitted_plan(api)
    fx.approve_plan(api, world["campaign_id"], world["advertiser_id"])
    return world


def _seller_with_draft_avail(api):
    """One seller carrying one DRAFT avail of ten million impressions."""
    seller = fx.register_seller(api, **SELLER)
    avail = fx.file_avail(api, seller["id"], **AVAIL)
    return {
        "seller_id": seller["id"],
        "seller_headers": make_seller_rep_headers(seller["id"]),
        "forecast_id": avail["id"],
    }


def _published_avail(api):
    """The same seller and avail, published and buyable."""
    world = _seller_with_draft_avail(api)
    fx.publish_avail(api, world["forecast_id"], world["seller_id"])
    return world


def _open_negotiation(api, world):
    """The agency's opening offer on the table against that plan and seller."""
    negotiation = fx.open_negotiation(
        api,
        world["campaign_id"],
        world["seller_id"],
        world["allocation_id"],
        **NEGOTIATION,
    )
    world["negotiation_id"] = negotiation["id"]
    world["negotiation"] = negotiation
    return world


def _countered_negotiation(api):
    """An APPROVED plan, a published avail and the seller's counter on the table."""
    world = _approved_plan(api)
    world.update(_published_avail(api))
    _open_negotiation(api, world)
    world["negotiation"] = fx.counter(
        api,
        world["negotiation_id"],
        world["seller_id"],
        counter_cpm_cents=COUNTER_CPM_CENTS,
        counter_impressions=COUNTER_IMPRESSIONS,
    )
    return world


def _placed_buy(api):
    """A PLACED buy carrying one SCHEDULED unit line covering its guarantee."""
    world = _countered_negotiation(api)
    buy = fx.accept_negotiation(api, world["negotiation_id"])
    world["buy_id"] = buy["id"]
    unit = fx.add_unit(api, buy["id"], world["forecast_id"], **UNIT)
    world["unit_id"] = unit["id"]
    world["buy"] = fx.place_buy(api, buy["id"], world["campaign_id"])
    return world


class TestNegotiationInitialState:
    """Where the negotiation machine starts, and with what on the table."""

    def test_a_fresh_negotiation_opens_in_agency_offer_at_round_one(self, api):
        """Opening a negotiation answers 201 with AGENCY_OFFER at round_number 1,
        last_offer_actor AGENCY and the opening terms mirrored into the current terms.

        PRD: "A new negotiation starts at `status` `AGENCY_OFFER` with `round_number`
        at 1 and `last_offer_actor` at `AGENCY`, and the terms on the table are seeded
        from the opening position: `current_cpm_cents` takes the value of
        `opening_cpm_cents` and `current_impressions` takes the value of
        `requested_impressions`."

        Design: Corner/state_machines/negotiation_starts_in_agency_offer_at_round_one
        """
        world = _drafted_plan(api)
        world.update(_seller_only(api))

        response = api.create_negotiation(
            fa.negotiation_payload(
                world["campaign_id"],
                world["seller_id"],
                world["allocation_id"],
                **NEGOTIATION,
            ),
            BUYER_HEADERS,
        )

        negotiation = validate_success(response, expected_status=201)
        assert negotiation["status"] == "AGENCY_OFFER"
        assert negotiation["round_number"] == 1
        assert negotiation["last_offer_actor"] == "AGENCY"
        assert negotiation["current_cpm_cents"] == 2000
        assert negotiation["current_impressions"] == 1_000_000
        assert negotiation["version"] == 1


class TestBuyInitialAxes:
    """The three independent axes acceptance mints a buy on."""

    def test_the_three_axes_and_every_cumulative_counter_start_at_zero(self, api):
        """Acceptance answers 201 with a buy at PENDING_PLACEMENT, NOT_STARTED and
        UNBILLED on one row at version 1, every cumulative counter reading zero.

        PRD: "Its three axes start at `buy_status` `PENDING_PLACEMENT`,
        `stewardship_status` `NOT_STARTED` and `settlement_status` `UNBILLED`."

        Design: Corner/state_machines/buy_three_axes_start_in_their_declared_initial_states
        """
        world = _countered_negotiation(api)

        response = api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS)

        buy = validate_success(response, expected_status=201)
        assert_buy_axes(
            buy,
            buy_status="PENDING_PLACEMENT",
            stewardship_status="NOT_STARTED",
            settlement_status="UNBILLED",
        )
        assert buy["placed_impressions"] == 0
        assert buy["credited_impressions_provisional"] == 0
        assert buy["credited_impressions_final"] == 0
        assert buy["made_good_impressions"] == 0
        assert buy["waived_impressions"] == 0
        assert buy["option_pct_cumulative"] == 0
        assert buy["cancelled_pct_cumulative"] == 0
        assert buy["version"] == 1
        assert buy["placed_by_user_id"] is None

    def test_the_flight_window_and_three_rights_deadlines_are_derived_at_acceptance(
        self, api
    ):
        """The buy copies the campaign's 2026-11-01 to 2026-12-31 flight and derives
        option and cancellation deadlines 45, 60 and 30 days before the flight start.

        PRD: "Its `flight_start` and `flight_end` are copied from the campaign's flight
        window, and from that start instant three contractual deadlines are derived:
        `option_window_close` sits 45 days before `flight_start`,
        `cancel_window_1_close` sits 60 days before it, and `cancel_window_2_close`
        sits 30 days before it."

        Design: Corner/state_machines/buy_three_axes_start_in_their_declared_initial_states
        """
        world = _countered_negotiation(api)

        response = api.accept_negotiation(world["negotiation_id"], None, BUYER_HEADERS)

        buy = validate_success(response, expected_status=201)
        assert_instant_field(buy, "flight_start", "2026-11-01T00:00:00Z")
        assert_instant_field(buy, "flight_end", "2026-12-31T23:59:59Z")
        assert_instant_field(buy, "option_window_close", "2026-09-17T00:00:00Z")
        assert_instant_field(buy, "cancel_window_1_close", "2026-09-02T00:00:00Z")
        assert_instant_field(buy, "cancel_window_2_close", "2026-10-02T00:00:00Z")
        # The same three deadlines, restated through the declared day offsets.
        assert_instant_field(
            buy, "option_window_close", option_window_close(FLIGHT_START)
        )
        assert_instant_field(
            buy, "cancel_window_1_close", cancel_window_1_close(FLIGHT_START)
        )
        assert_instant_field(
            buy, "cancel_window_2_close", cancel_window_2_close(FLIGHT_START)
        )


class TestForecastPublication:
    """The avail's only valid hop out of DRAFT."""

    def test_publishing_moves_the_avail_from_draft_to_published(self, api):
        """Publishing takes the avail DRAFT -> PUBLISHED at version 2 with its ten
        million available impressions untouched, and only then does it answer a
        status=PUBLISHED marketplace search.

        PRD: "Publication is the seller's decision to make the avail buyable, moving
        it `DRAFT → PUBLISHED`."

        Design: Corner/state_machines/forecast_publish_moves_draft_to_published
        """
        world = _seller_with_draft_avail(api)

        response = api.publish_inventory_forecast(
            world["forecast_id"], None, world["seller_headers"]
        )

        avail = validate_success(response, expected_status=200)
        assert avail["status"] == "PUBLISHED"
        assert avail["version"] == 2
        assert avail["available_impressions"] == 10_000_000
        assert avail["total_impressions"] == 10_000_000

        published, meta = validate_paginated(
            api.list_inventory_forecasts(
                BUYER_HEADERS,
                params={"seller_id": world["seller_id"], "status": "PUBLISHED"},
            )
        )
        assert meta["total_count"] == 1
        assert published[0]["id"] == world["forecast_id"]

        drafts, draft_meta = validate_paginated(
            api.list_inventory_forecasts(
                BUYER_HEADERS,
                params={"seller_id": world["seller_id"], "status": "DRAFT"},
            )
        )
        assert draft_meta["total_count"] == 0
        assert drafts == []


def _campaign_without_allocations(api):
    """One advertiser and one DRAFT campaign with a ten-million-cent budget."""
    world = _advertiser_only(api)
    campaign = fx.open_campaign(api, world["advertiser_id"], **CAMPAIGN)
    world["campaign_id"] = campaign["id"]
    return world


class TestCampaignFundingAxis:
    """The funding axis climbs on its own, without the planning axis moving."""

    def test_two_deposits_take_the_axis_unfunded_to_partially_funded_to_funded(
        self, api
    ):
        """A 4,000,000 cent deposit lands the axis on PARTIALLY_FUNDED and a further
        6,000,000 cent deposit takes it to FUNDED at the full 10,000,000 cents.

        PRD: "The resulting state depends on a single comparison against the authorised
        budget: if `funded_cents` after the deposit remains strictly below
        `total_budget_cents`, the axis lands on `PARTIALLY_FUNDED` — arriving there from
        `UNFUNDED` on the first such deposit and remaining there, as a self-transition,
        on each subsequent one; if `funded_cents` after the deposit reaches or exceeds
        `total_budget_cents`, the axis lands on `FUNDED`, whether it came from
        `UNFUNDED` in a single deposit or from `PARTIALLY_FUNDED` after several."

        Design: Corner/state_machines/campaign_funding_axis_advances_while_the_plan_axis_stays_draft
        """
        world = _campaign_without_allocations(api)

        first = validate_success(
            api.fund_campaign(
                world["campaign_id"], {"amount_cents": 4_000_000}, world["client_headers"]
            ),
            expected_status=200,
        )
        assert_campaign_axes(first, funding_status="PARTIALLY_FUNDED")
        assert first["funded_cents"] == 4_000_000

        second = validate_success(
            api.fund_campaign(
                world["campaign_id"], {"amount_cents": 6_000_000}, world["client_headers"]
            ),
            expected_status=200,
        )
        assert_campaign_axes(second, funding_status="FUNDED")
        assert second["funded_cents"] == 10_000_000

    def test_the_plan_axis_is_left_in_draft_while_the_version_counts_both_deposits(
        self, api
    ):
        """After both deposits the campaign is FUNDED yet still plan_status DRAFT and
        plan_posture WITHIN_PLAN, its version having reached 3 on the two deposits.

        PRD: "Crucially, the funding axis is independent of the planning axis in both
        directions — funding a campaign whose plan has never been submitted is entirely
        legitimate, and approving a plan that carries no funding at all is equally
        legitimate."

        Design: Corner/state_machines/campaign_funding_axis_advances_while_the_plan_axis_stays_draft
        """
        world = _campaign_without_allocations(api)
        fx.fund_campaign(api, world["campaign_id"], world["advertiser_id"], 4_000_000)
        fx.fund_campaign(api, world["campaign_id"], world["advertiser_id"], 6_000_000)

        campaign = validate_success(
            api.get_campaign(world["campaign_id"], CONTROLLER_HEADERS),
            expected_status=200,
        )
        assert_campaign_axes(
            campaign,
            plan_status="DRAFT",
            funding_status="FUNDED",
            plan_posture="WITHIN_PLAN",
        )
        assert campaign["version"] == 3


class TestPlanRejectionCascade:
    """Rejection's allocation cascade is conditional on the allocation being locked."""

    def test_rejecting_a_pending_plan_leaves_an_already_draft_allocation_untouched(
        self, api
    ):
        """The plan returns PENDING_CLIENT_APPROVAL -> DRAFT at campaign version 4 while
        the allocation that was already DRAFT keeps version 1 and its whole ledger.

        PRD: "The cascade here is **conditional**: every allocation of the campaign
        whose `status` is `LOCKED` returns `LOCKED → DRAFT` with its `version`
        incremented, while allocations already sitting at `DRAFT` are left completely
        untouched — no state write, no `version` bump, no `updated_at` refresh."

        Design: Corner/state_machines/reject_plan_returns_a_pending_plan_to_draft_without_touching_draft_allocations
        """
        world = _submitted_plan(api)

        response = api.reject_plan(
            world["campaign_id"],
            {"revision_note": "shift weight out of prime"},
            world["client_headers"],
        )

        campaign = validate_success(response, expected_status=200)
        assert_campaign_axes(campaign, plan_status="DRAFT")
        assert campaign["version"] == 4

        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], CONTROLLER_HEADERS),
            expected_status=200,
        )
        assert_allocation_posture(allocation, status="DRAFT")
        assert allocation["version"] == 1

        assert campaign["allocated_budget_cents"] == 10_000_000
        assert campaign["unallocated_budget_cents"] == 0


class TestAiringSettlementPrecondition:
    """SCHEDULED -> AIRED carries a temporal precondition on the logical clock."""

    def test_settling_before_the_air_window_has_elapsed_is_refused(self, api):
        """With the clock never moved off 2026-08-01 and the air window closing
        2026-11-30T23:59:59Z, the settlement is refused 422 and the line stays SCHEDULED
        with no measured audience recorded.

        PRD: "Settlement is also strictly retrospective: the logical clock must have
        reached the line's `air_window_end`, with an instant exactly equal to it
        accepted, and an attempt made earlier is refused with
        `ERR_AIR_WINDOW_NOT_ELAPSED`."

        Design: Corner/state_machines/settling_an_airing_before_the_air_window_end_is_rejected
        """
        world = _placed_buy(api)

        response = api.settle_airing(
            world["unit_id"],
            fa.settle_aired_payload(1_000_000),
            world["seller_headers"],
        )

        validate_error(
            response, ApiErrorId.AIR_WINDOW_NOT_ELAPSED, expected_status=422
        )

        unit = validate_success(
            api.get_buy_unit(world["unit_id"], BUYER_HEADERS), expected_status=200
        )
        assert unit["status"] == "SCHEDULED"
        assert unit["version"] == 1
        # The line was created with actual_impressions at 0 and the refused settlement
        # never recorded the 1,000,000 it claimed.
        assert unit["actual_impressions"] == 0

        buy = validate_success(
            api.get_buy(world["buy_id"], BUYER_HEADERS), expected_status=200
        )
        assert_buy_axes(buy, buy_status="PLACED", stewardship_status="NOT_STARTED")


def _seller_only(api):
    """One media seller with no inventory on file yet."""
    seller = fx.register_seller(api, **SELLER)
    return {
        "seller_id": seller["id"],
        "seller_headers": make_seller_rep_headers(seller["id"]),
    }


def _agency_offer_on_the_table(api):
    """An open negotiation sitting at AGENCY_OFFER round 1, no seller counter yet."""
    world = _drafted_plan(api)
    world.update(_seller_only(api))
    return _open_negotiation(api, world)


class TestUndefinedNegotiationHop:
    """revise is defined only from SELLER_COUNTER."""

    def test_revising_a_standing_agency_offer_is_refused(self, api):
        """The agency cannot revise its own standing offer: the request is refused 409
        and neither the round counter nor the terms on the table move.

        PRD: "Countering a negotiation that is not sitting at `AGENCY_OFFER`, or
        revising one that is not sitting at `SELLER_COUNTER`, is rejected with
        `ERR_NEGOTIATION_NOT_IN_EXPECTED_STATE`; a negotiation that has already reached
        `ACCEPTED` or `WITHDRAWN` is refused earlier with `ERR_ALREADY_TERMINAL`,
        because both are terminal states of this machine."

        Design: Corner/state_machines/revising_an_offer_that_is_still_agency_offer_is_rejected
        """
        world = _agency_offer_on_the_table(api)

        response = api.revise_negotiation(
            world["negotiation_id"],
            {"offer_cpm_cents": 2100, "offer_impressions": 1_000_000},
            BUYER_HEADERS,
        )

        validate_error(
            response,
            ApiErrorId.NEGOTIATION_NOT_IN_EXPECTED_STATE,
            expected_status=409,
        )

        negotiation = validate_success(
            api.get_negotiation(world["negotiation_id"], BUYER_HEADERS),
            expected_status=200,
        )
        assert negotiation["status"] == "AGENCY_OFFER"
        assert negotiation["round_number"] == 1
        assert negotiation["current_cpm_cents"] == 2000
        assert negotiation["version"] == 1


class TestWithdrawnNegotiationLockdown:
    """WITHDRAWN is terminal, and terminality outranks the from-state rule."""

    def test_a_withdrawn_negotiation_refuses_a_correctly_versioned_counter(self, api):
        """The seller's counter quotes the correct post-withdrawal version 2 and is still
        refused, with ERR_ALREADY_TERMINAL rather than the from-state error, and no buy
        is brought into existence.

        PRD: "Countering a negotiation that is not sitting at `AGENCY_OFFER`, or
        revising one that is not sitting at `SELLER_COUNTER`, is rejected with
        `ERR_NEGOTIATION_NOT_IN_EXPECTED_STATE`; a negotiation that has already reached
        `ACCEPTED` or `WITHDRAWN` is refused earlier with `ERR_ALREADY_TERMINAL`,
        because both are terminal states of this machine."

        Design: Corner/state_machines/a_withdrawn_negotiation_cannot_be_countered
        """
        world = _agency_offer_on_the_table(api)

        withdrawn = validate_success(
            api.withdraw_negotiation(
                world["negotiation_id"],
                {"withdraw_reason": "budget pulled"},
                BUYER_HEADERS,
            ),
            expected_status=200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["version"] == 2

        response = api.counter_negotiation(
            world["negotiation_id"],
            fa.counter_payload(
                withdrawn["version"],
                counter_cpm_cents=COUNTER_CPM_CENTS,
                counter_impressions=COUNTER_IMPRESSIONS,
            ),
            world["seller_headers"],
        )
        validate_error(response, ApiErrorId.ALREADY_TERMINAL, expected_status=409)

        negotiation = validate_success(
            api.get_negotiation(world["negotiation_id"], BUYER_HEADERS),
            expected_status=200,
        )
        assert negotiation["status"] == "WITHDRAWN"
        assert negotiation["round_number"] == 1
        assert negotiation["version"] == 2

        _, meta = validate_paginated(
            api.list_buys(
                BUYER_HEADERS, params={"negotiation_id": world["negotiation_id"]}
            )
        )
        assert meta["total_count"] == 0


class TestRepeatedPublication:
    """publish is a one-shot hop out of DRAFT, not an idempotent setter."""

    def test_a_second_publish_of_the_same_avail_is_refused(self, api):
        """Replaying publish on an already PUBLISHED avail answers 409 and leaves the
        avail at version 2 rather than silently returning 200 and reaching version 3.

        PRD: "Publishing an avail that is not currently `DRAFT` — a second publication
        of the same avail, for instance — is rejected with
        `ERR_FORECAST_NOT_IN_EXPECTED_STATE`."

        Design: Corner/state_machines/a_second_publish_of_the_same_forecast_is_rejected
        """
        world = _published_avail(api)

        response = api.publish_inventory_forecast(
            world["forecast_id"], None, world["seller_headers"]
        )

        validate_error(
            response, ApiErrorId.FORECAST_NOT_IN_EXPECTED_STATE, expected_status=409
        )

        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS),
            expected_status=200,
        )
        assert avail["status"] == "PUBLISHED"
        assert avail["version"] == 2


def _accepted_mid_flight_report(api):
    """A PLACED buy carrying one accepted mid-flight report of 1,000,000 impressions.

    The report's period closes inside the flight, so the clock is moved past
    ``period_end`` before the report is filed and ``is_post_buy_final`` reads false.
    """
    world = _placed_buy(api)
    fx.move_clock(api, AFTER_REPORTED_PERIOD)
    report = fx.file_report(
        api,
        world["buy_id"],
        1_000_000,
        1_000_000,
        seller_id=world["seller_id"],
        measurement_basis="LINEAR_C3",
        period_start=FLIGHT_START,
        period_end=AIR_WINDOW_END,
    )
    world["report_id"] = report["id"]
    world["report"] = get_success_data(
        api.accept_delivery_report(report["id"], None, BUYER_HEADERS)
    )
    return world


class TestRepeatedReportAcceptance:
    """Acceptance is a one-shot hop out of SUBMITTED, and its credit lands once."""

    def test_a_second_accept_of_the_same_report_is_refused_as_not_submitted(self, api):
        """The replay answers 409 ERR_REPORT_NOT_SUBMITTED - not ERR_ALREADY_TERMINAL,
        which the ladder reserves for four other machines - and the report stays ACCEPTED
        with is_post_buy_final still false.

        PRD: "Both `ACCEPTED` and `DISPUTED` are terminal for a report, and a second
        attempt to accept or dispute is refused with `ERR_REPORT_NOT_SUBMITTED`."

        Design: Corner/state_machines/a_second_accept_of_the_same_delivery_report_is_rejected
        """
        world = _accepted_mid_flight_report(api)

        response = api.accept_delivery_report(
            world["report_id"], None, BUYER_HEADERS
        )

        validate_error(
            response, ApiErrorId.REPORT_NOT_SUBMITTED, expected_status=409
        )

        report = validate_success(
            api.get_delivery_report(world["report_id"], BUYER_HEADERS),
            expected_status=200,
        )
        assert report["status"] == "ACCEPTED"
        assert report["is_post_buy_final"] is False

    def test_the_refused_replay_does_not_credit_the_delivery_twice(self, api):
        """The buy still carries exactly 1,000,000 credited demo impressions at a final
        index of 1.0000, sits at IN_FLIGHT and ON_TRACK, and has no make-good.

        PRD: "The **final** view is the settlement number: `credited_impressions_final`
        is the sum of `delivered_demo_impressions` over the buy's reports whose `status`
        is exactly `ACCEPTED`, and `final_delivery_index` is that credit divided by
        `guaranteed_impressions`, likewise rounded half up to four decimal places and
        likewise 0.0000 when the guarantee is 0."

        Design: Corner/state_machines/a_second_accept_of_the_same_delivery_report_is_rejected
        """
        world = _accepted_mid_flight_report(api)

        validate_error(
            api.accept_delivery_report(world["report_id"], None, BUYER_HEADERS),
            ApiErrorId.REPORT_NOT_SUBMITTED,
            expected_status=409,
        )

        buy = validate_success(
            api.get_buy(world["buy_id"], BUYER_HEADERS), expected_status=200
        )
        assert buy["credited_impressions_final"] == 1_000_000
        assert buy["final_delivery_index"] == 1.0000
        assert buy["final_delivery_index"] == delivery_index(
            1_000_000, GUARANTEED_IMPRESSIONS
        )
        assert_buy_axes(buy, buy_status="IN_FLIGHT", stewardship_status="ON_TRACK")

        _, meta = validate_paginated(
            api.list_make_goods(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert meta["total_count"] == 0
