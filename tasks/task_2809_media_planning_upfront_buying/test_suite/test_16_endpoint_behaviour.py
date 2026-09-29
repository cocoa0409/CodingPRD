"""Endpoint-level behaviour of the upfront buying surface.

Closeout of a buy that delivered inside tolerance, the make-good filter on the
unit collection, the campaign read's planning and commitment rollups, the avail
create/read/filtered-list round trip and the default credit a waiver applies.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    PLANNER_HEADERS,
    assert_budget_ledger_balances,
    assert_buy_axes,
    assert_campaign_axes,
    assert_cents,
    assert_ids_equal,
    assert_impressions,
    assert_instant_field,
    assert_pagination_meta,
    assert_pct2,
    assert_pct4,
    assert_version_advanced,
    factories as fa,
    fixtures as fx,
    get_success_data,
    make_seller_rep_headers,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# The calendar and the figures every instance in this file is priced from
# --------------------------------------------------------------------------
FLIGHT_START = "2026-11-01T00:00:00Z"
FLIGHT_END = "2026-12-31T23:59:59Z"
AIR_WINDOW_START = "2026-11-02T00:00:00Z"
AIR_WINDOW_END = "2026-11-30T23:59:59Z"

#: An instant past the whole flight, so a post-buy-final report may be filed.
AFTER_FLIGHT = "2027-01-01T00:00:00Z"

#: The replacement avail's own window, and the window a make-good is offered in.
MAKE_GOOD_AVAIL_START = "2027-01-01T00:00:00Z"
MAKE_GOOD_AVAIL_END = "2027-02-28T00:00:00Z"
MAKE_GOOD_WINDOW_START = "2027-01-05T00:00:00Z"
MAKE_GOOD_WINDOW_END = "2027-01-25T00:00:00Z"

GUARANTEED_IMPRESSIONS = 1_000_000
AGREED_CPM_CENTS = 2200
#: 1,000,000 impressions at 2200 cents per thousand plus seven percent commission.
GROSS_COST_CENTS = 2_354_000
TOTAL_BUDGET_CENTS = 10_000_000
AVAIL_IMPRESSIONS = 10_000_000
REPLACEMENT_AVAIL_IMPRESSIONS = 5_000_000
SHORTFALL_IMPRESSIONS = 100_000
SHORTFALL_VALUE_CENTS = 220_000


def _placed_buy(api):
    """One approved single-allocation campaign carrying one placed buy.

    The advertiser, the seller, the plan, the avail, the negotiation, the unit
    line and the placement all use the payload literals the design pins, so the
    buy guarantees 1,000,000 impressions at an agreed CPM of 2200 and costs
    2,354,000 cents gross.
    """
    advertiser = fx.register_advertiser(
        api,
        name="Cascadia Beverage",
        category_code="BEVERAGE",
        credit_limit_cents=500_000_000,
        payment_terms_days=30,
        sequential_liability_enabled=True,
    )
    seller = fx.register_seller(
        api,
        name="Harbor Broadcasting",
        platform_types=["LINEAR", "CTV", "DIGITAL"],
        make_good_capacity_impressions=50_000_000,
    )
    campaign = fx.open_campaign(
        api,
        advertiser["id"],
        name="Q4 Linear Base",
        target_demo="A25-54",
        universe_thousands=120_000,
        reach_goal_pct=60.0,
        frequency_goal=4.0,
        total_budget_cents=TOTAL_BUDGET_CENTS,
        flight_start=FLIGHT_START,
        flight_end=FLIGHT_END,
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
    fx.approve_plan(api, campaign["id"], advertiser["id"])
    avail = fx.file_avail(
        api,
        seller["id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Harbor Nightly",
        platform="LINEAR",
        window_start=FLIGHT_START,
        window_end=FLIGHT_END,
        total_impressions=AVAIL_IMPRESSIONS,
        forecast_cpm_cents=AGREED_CPM_CENTS,
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
        requested_impressions=GUARANTEED_IMPRESSIONS,
        opening_cpm_cents=2000,
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
    unit = fx.add_unit(
        api,
        buy["id"],
        avail["id"],
        daypart="PRIME",
        program="Harbor Nightly",
        platform="LINEAR",
        units=1,
        unit_rate_cents=2_200_000,
        projected_impressions=GUARANTEED_IMPRESSIONS,
        air_window_start=AIR_WINDOW_START,
        air_window_end=AIR_WINDOW_END,
        exclusive=False,
    )
    buy = fx.place_buy(api, buy["id"], campaign["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "negotiation_id": negotiation["id"],
        "buy_id": buy["id"],
        "unit_id": unit["id"],
        "buy": buy,
    }


def _adjudicated_buy(api, delivered_demo_impressions):
    """A placed buy carrying one accepted post-buy-final delivery report.

    The report covers the whole flight, so it is post-buy final and its
    acceptance runs the shortfall evaluation.
    """
    world = _placed_buy(api)
    fx.move_clock(api, AFTER_FLIGHT)
    report = fx.file_report(
        api,
        world["buy_id"],
        GUARANTEED_IMPRESSIONS,
        delivered_demo_impressions,
        seller_id=world["seller_id"],
        measurement_basis="LINEAR_C3",
        period_start=FLIGHT_START,
        period_end=FLIGHT_END,
    )
    fx.accept_report(api, report["id"])
    world["report_id"] = report["id"]
    world["buy"] = fx.read_buy(api, world["buy_id"])
    return world


class TestCloseEndpointCompletesABuyWithinTolerance:
    """Closeout of a buy the post-buy analysis left inside tolerance."""

    def test_close_moves_the_in_flight_buy_to_completed(self, api):
        """A controller closing a buy that delivered 990,000 demo impressions
        against a 1,000,000 guarantee carries it IN_FLIGHT -> COMPLETED, leaves
        the stewardship axis at WITHIN_TOLERANCE and advances the buy one version.

        PRD: "Stewardship ends with closeout, an `AgencyController` action that
        moves the buy `IN_FLIGHT → COMPLETED`."

        Design: Corner/endpoints/close_endpoint_completes_a_buy_within_tolerance
        """
        world = _adjudicated_buy(api, 990_000)
        before = fx.read_buy(api, world["buy_id"])
        assert_buy_axes(before, buy_status="IN_FLIGHT", stewardship_status="WITHIN_TOLERANCE")

        data = validate_success(api.close_buy(world["buy_id"], None, CONTROLLER_HEADERS), 200)

        assert_buy_axes(
            data, buy_status="COMPLETED", stewardship_status="WITHIN_TOLERANCE"
        )
        assert_version_advanced(before, data)

    def test_close_is_reachable_because_no_make_good_was_ever_raised(self, api):
        """The 1.0000 percent shortfall sits below the 2.0000 tolerance, so the
        closed buy carries a final delivery index of 0.9900 and its make-good
        collection is empty.

        PRD: "If the percentage is strictly below the tolerance, the axis moves
        to `WITHIN_TOLERANCE` instead, again from any of those three origins, no
        make-good is created and the chain stops here."

        Design: Corner/endpoints/close_endpoint_completes_a_buy_within_tolerance
        """
        world = _adjudicated_buy(api, 990_000)

        data = validate_success(api.close_buy(world["buy_id"], None, CONTROLLER_HEADERS), 200)

        assert_pct4(data, "final_delivery_index", 0.9900)
        assert_impressions(data, "credited_impressions_final", 990_000)
        assert_buy_axes(data, stewardship_status="WITHIN_TOLERANCE")
        rows, meta = validate_paginated(
            api.list_make_goods(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert_pagination_meta(meta, expected_total=0)
        assert rows == [], f"no make-good may exist on this buy, found {rows}"


def _scheduled_make_good(api):
    """An accepted make-good, so the acceptance cascade has minted a unit line.

    The buy under-delivers by 100,000 demo impressions, which opens a make-good
    for the whole gap.  The replacement inventory is a second published avail of
    the same seller whose window opens at the logical clock, because a make-good
    may not be offered into a window that has already elapsed.
    """
    world = _adjudicated_buy(api, 900_000)
    make_good = fx.only_make_good(api, world["buy_id"])
    replacement = fx.published_avail(
        api,
        world["seller_id"],
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="LATE",
        program="Late Edition",
        platform="LINEAR",
        window_start=MAKE_GOOD_AVAIL_START,
        window_end=MAKE_GOOD_AVAIL_END,
        total_impressions=REPLACEMENT_AVAIL_IMPRESSIONS,
        forecast_cpm_cents=1800,
        exclusivity_mode="SHARED",
    )
    fx.offer_make_good(
        api,
        make_good["id"],
        world["seller_id"],
        replacement["id"],
        SHORTFALL_IMPRESSIONS,
        offered_window_start=MAKE_GOOD_WINDOW_START,
        offered_window_end=MAKE_GOOD_WINDOW_END,
    )
    fx.accept_make_good(api, make_good["id"])
    world["make_good_id"] = make_good["id"]
    world["replacement_forecast_id"] = replacement["id"]
    return world


class TestBuyUnitsListingByMakeGoodIdLinksTheCascadeCreatedUnit:
    """The make_good_id filter is the only way to reach a minted unit line."""

    def test_the_filter_returns_the_single_minted_replacement_line(self, api):
        """Listing unit lines by the accepted make-good's identifier returns
        exactly the cascade-created line: one free unit of 100,000 impressions on
        the offered avail, in the offered window, restating that avail's
        daypart, program and platform.

        PRD: "On success a replacement unit line is created for the buy with
        `status` `MAKE_GOOD_SCHEDULED`, its `make_good_id` pointing back at this
        make-good, its `forecast_id` taken from `offered_forecast_id`, its
        `projected_impressions` set to `offered_impressions`, its `units` set to
        1, its `unit_rate_cents` set to 0, its `air_window_start` and
        `air_window_end` copied from the offered window, and its `daypart`,
        `program` and `platform` copied from the avail."

        Design: Corner/endpoints/buy_units_listing_by_make_good_id_links_the_cascade_created_unit
        """
        world = _scheduled_make_good(api)

        response = api.list_buy_units(
            BUYER_HEADERS, params={"make_good_id": world["make_good_id"]}
        )
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
        assert len(rows) == 1, f"expected exactly one minted line, got {rows}"
        line = rows[0]
        assert line["status"] == "MAKE_GOOD_SCHEDULED", (
            f"the minted line must be MAKE_GOOD_SCHEDULED, got {line['status']}"
        )
        assert line["make_good_id"] == world["make_good_id"]
        assert line["buy_id"] == world["buy_id"]
        assert line["forecast_id"] == world["replacement_forecast_id"]
        assert line["units"] == 1, f"a make-good line carries one unit, got {line['units']}"
        assert_cents(line, "unit_rate_cents", 0)
        assert_cents(line, "line_net_cents", 0)
        assert_cents(line, "line_commission_cents", 0)
        assert_cents(line, "line_gross_cents", 0)
        assert_impressions(line, "projected_impressions", SHORTFALL_IMPRESSIONS)
        assert line["daypart"] == "LATE"
        assert line["program"] == "Late Edition"
        assert line["platform"] == "LINEAR"
        assert_instant_field(line, "air_window_start", MAKE_GOOD_WINDOW_START)
        assert_instant_field(line, "air_window_end", MAKE_GOOD_WINDOW_END)

    def test_the_minted_line_settles_the_buy_and_the_sellers_exposure(self, api):
        """Booking the replacement inventory closes the buy's open shortfall,
        moves the seller's exposure from open to scheduled, holds 100,000
        impressions on the replacement avail and leaves the buy carrying two
        unit lines.

        PRD: "The seller's `open_make_good_impressions` and
        `scheduled_make_good_impressions` are both recomputed — the exposure
        moves from open to scheduled, which is what consumes the seller's
        capacity."

        Design: Corner/endpoints/buy_units_listing_by_make_good_id_links_the_cascade_created_unit
        """
        world = _scheduled_make_good(api)

        seller = validate_success(api.get_seller(world["seller_id"], BUYER_HEADERS), 200)
        assert_impressions(seller, "scheduled_make_good_impressions", SHORTFALL_IMPRESSIONS)
        assert_impressions(seller, "open_make_good_impressions", 0)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS), 200)
        assert_impressions(buy, "made_good_impressions", SHORTFALL_IMPRESSIONS)
        assert_impressions(buy, "open_shortfall_impressions", 0)
        assert_buy_axes(buy, stewardship_status="MADE_GOOD")

        avail = validate_success(
            api.get_inventory_forecast(world["replacement_forecast_id"], BUYER_HEADERS), 200
        )
        assert_impressions(
            avail,
            "available_impressions",
            REPLACEMENT_AVAIL_IMPRESSIONS - SHORTFALL_IMPRESSIONS,
        )
        assert avail["status"] == "PUBLISHED", (
            f"the replacement avail keeps inventory, got {avail['status']}"
        )

        _, meta = validate_paginated(
            api.list_buy_units(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        )
        assert_pagination_meta(meta, expected_total=2)


class TestCampaignReadReflectsAllocationAndCommitmentRollups:
    """The campaign read projects both its allocations and its placed buys."""

    def test_the_read_carries_the_planning_and_the_commitment_families(self, api):
        """One 100 percent prime upfront allocation of a 10,000,000 cent budget
        projects 4,166,666 impressions and 3.47 rating points, while the single
        placed buy commits 2,354,000 cents and leaves 7,646,000 uncommitted.

        PRD: "Separately, the campaign's `committed_gross_cents` is the sum of
        `gross_cost_cents` over the campaign's buys whose `buy_status` is
        `PLACED`, `IN_FLIGHT`, `COMPLETED` or `CLOSED` — buys still at
        `PENDING_PLACEMENT` and buys that reached `CANCELLED` are excluded — and
        its `uncommitted_budget_cents` is `total_budget_cents` less that
        committed figure."

        Design: Corner/endpoints/campaign_read_reflects_allocation_and_commitment_rollups
        """
        world = _placed_buy(api)

        data = validate_success(api.get_campaign(world["campaign_id"], PLANNER_HEADERS), 200)

        assert_cents(data, "allocated_budget_cents", TOTAL_BUDGET_CENTS)
        assert_cents(data, "unallocated_budget_cents", 0)
        assert_impressions(data, "planned_impressions_total", 4_166_666)
        assert_pct2(data, "planned_grp_total", 3.47)
        assert_cents(data, "committed_gross_cents", GROSS_COST_CENTS)
        assert_cents(data, "uncommitted_budget_cents", TOTAL_BUDGET_CENTS - GROSS_COST_CENTS)
        assert_budget_ledger_balances(data)
        assert_campaign_axes(
            data,
            plan_status="APPROVED",
            plan_posture="WITHIN_PLAN",
            funding_status="UNFUNDED",
        )

    def test_the_read_carries_one_version_per_mutation_of_the_campaign(self, api):
        """Creation, the allocation, submission, approval and the placement are
        five writes against the campaign, so the read answers with version 5.

        PRD: "Most resources additionally carry `updated_at`, refreshed on every
        mutation of the resource, and `version`, an integer that starts at 1 on
        creation and increments by exactly 1 on every mutation of that resource."

        Design: Corner/endpoints/campaign_read_reflects_allocation_and_commitment_rollups
        """
        world = _placed_buy(api)

        data = validate_success(api.get_campaign(world["campaign_id"], PLANNER_HEADERS), 200)

        assert data["version"] == 5, (
            f"the campaign carries one increment per write, expected 5, "
            f"got {data['version']}"
        )


def _prime_avail_payload(seller_id):
    """The prime upfront avail the seller publishes."""
    return fa.inventory_forecast_payload(
        seller_id,
        market="UPFRONT",
        fiscal_quarter="2026Q4",
        daypart="PRIME",
        program="Harbor Nightly",
        platform="LINEAR",
        window_start=FLIGHT_START,
        window_end=FLIGHT_END,
        total_impressions=AVAIL_IMPRESSIONS,
        forecast_cpm_cents=AGREED_CPM_CENTS,
        exclusivity_mode="SHARED",
    )


def _daytime_avail_payload(seller_id):
    """The scatter daytime avail the seller keeps in draft."""
    return fa.inventory_forecast_payload(
        seller_id,
        market="SCATTER",
        fiscal_quarter="2026Q4",
        daypart="DAYTIME",
        program="Harbor Daytime",
        platform="LINEAR",
        window_start=FLIGHT_START,
        window_end=FLIGHT_END,
        total_impressions=REPLACEMENT_AVAIL_IMPRESSIONS,
        forecast_cpm_cents=1800,
        exclusivity_mode="SHARED",
    )


def _one_published_one_draft_avail(api):
    """One seller filing two avails for the same quarter, publishing the first."""
    seller = fx.register_seller(
        api,
        name="Harbor Broadcasting",
        platform_types=["LINEAR", "CTV", "DIGITAL"],
        make_good_capacity_impressions=50_000_000,
    )
    headers = make_seller_rep_headers(seller["id"])
    first = get_success_data(
        api.create_inventory_forecast(_prime_avail_payload(seller["id"]), headers)
    )
    second = get_success_data(
        api.create_inventory_forecast(_daytime_avail_payload(seller["id"]), headers)
    )
    fx.publish_avail(api, first["id"], seller["id"])
    return {
        "seller_id": seller["id"],
        "published_id": first["id"],
        "draft_id": second["id"],
    }


class TestForecastCreateReadAndFilteredListRoundTrip:
    """Filing, publishing and searching avails on the marketplace."""

    def test_a_filed_avail_starts_in_draft_with_its_whole_forecast_available(self, api):
        """The scatter daytime avail is created with HTTP 201 at version 1, in
        DRAFT, carrying all 5,000,000 of its forecast impressions as available.

        PRD: "A newly filed avail has `available_impressions` initialised to
        `total_impressions` and `status` `DRAFT`."

        Design: Corner/endpoints/forecast_create_read_and_filtered_list_round_trip
        """
        seller = fx.register_seller(
            api,
            name="Harbor Broadcasting",
            platform_types=["LINEAR", "CTV", "DIGITAL"],
            make_good_capacity_impressions=50_000_000,
        )
        headers = make_seller_rep_headers(seller["id"])
        get_success_data(
            api.create_inventory_forecast(_prime_avail_payload(seller["id"]), headers)
        )

        data = validate_success(
            api.create_inventory_forecast(_daytime_avail_payload(seller["id"]), headers), 201
        )

        assert data["status"] == "DRAFT", f"a filed avail starts DRAFT, got {data['status']}"
        assert_impressions(data, "available_impressions", REPLACEMENT_AVAIL_IMPRESSIONS)
        assert_impressions(data, "total_impressions", REPLACEMENT_AVAIL_IMPRESSIONS)
        assert data["version"] == 1, f"a fresh avail is version 1, got {data['version']}"

    def test_the_single_read_reflects_the_publication(self, api):
        """Reading the published prime avail back answers PUBLISHED at version 2,
        with its 10,000,000 impressions still unheld and its asking CPM of 2200
        unchanged.

        PRD: "Publication increments the avail's `version` by 1 and makes it
        eligible both for unit-line placement and for use as make-good
        replacement inventory."

        Design: Corner/endpoints/forecast_create_read_and_filtered_list_round_trip
        """
        world = _one_published_one_draft_avail(api)

        data = validate_success(
            api.get_inventory_forecast(world["published_id"], BUYER_HEADERS), 200
        )

        assert data["status"] == "PUBLISHED", (
            f"the published avail must read PUBLISHED, got {data['status']}"
        )
        assert_impressions(data, "available_impressions", AVAIL_IMPRESSIONS)
        assert_cents(data, "forecast_cpm_cents", AGREED_CPM_CENTS)
        assert data["version"] == 2, (
            f"filing then publishing is two writes, expected version 2, "
            f"got {data['version']}"
        )

    def test_the_status_filter_separates_the_two_avails_of_one_seller(self, api):
        """Searching the seller's avails by status returns exactly the published
        one under PUBLISHED and exactly the draft one under DRAFT.

        PRD: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of records
        matching the request's filters before the window is applied and
        `has_more` is true exactly when records remain beyond the returned
        window."

        Design: Corner/endpoints/forecast_create_read_and_filtered_list_round_trip
        """
        world = _one_published_one_draft_avail(api)

        published = api.list_inventory_forecasts(
            BUYER_HEADERS, params={"seller_id": world["seller_id"], "status": "PUBLISHED"}
        )
        published_rows, published_meta = validate_paginated(published)
        assert published.json()["response_type"] == "array"
        assert_pagination_meta(published_meta, expected_total=1, expected_has_more=False)
        assert_ids_equal(published_rows, [world["published_id"]])

        draft = api.list_inventory_forecasts(
            BUYER_HEADERS, params={"seller_id": world["seller_id"], "status": "DRAFT"}
        )
        draft_rows, draft_meta = validate_paginated(draft)
        assert draft.json()["response_type"] == "array"
        assert_pagination_meta(draft_meta, expected_total=1, expected_has_more=False)
        assert_ids_equal(draft_rows, [world["draft_id"]])


def _open_make_good(api):
    """An under-delivered buy whose make-good is still open and never offered."""
    world = _adjudicated_buy(api, 900_000)
    world["make_good"] = fx.only_make_good(api, world["buy_id"])
    world["make_good_id"] = world["make_good"]["id"]
    return world


class TestWaiveDefaultsTheCreditToTheFrozenShortfallValue:
    """Settling an open make-good for cash instead of replacement airtime."""

    def test_the_waiver_credits_the_frozen_shortfall_value(self, api):
        """Waiving the open make-good without naming a figure credits the client
        the full 220,000 cents of contractual value carried by the 100,000
        undelivered demo impressions.

        PRD: "The request may supply `credit_cents`; when it is omitted,
        `waived_credit_cents` defaults to the make-good's own
        `shortfall_value_cents`, so waiving without an explicit figure credits
        the client the full contractual value of the undelivered audience."

        Design: Corner/endpoints/waive_defaults_the_credit_to_the_frozen_shortfall_value
        """
        world = _open_make_good(api)

        data = validate_success(
            api.waive_make_good(world["make_good_id"], fa.waive_payload(), CONTROLLER_HEADERS),
            200,
        )

        assert data["status"] == "WAIVED", (
            f"a waived make-good must read WAIVED, got {data['status']}"
        )
        assert_cents(data, "waived_credit_cents", SHORTFALL_VALUE_CENTS)
        assert_impressions(data, "shortfall_impressions", SHORTFALL_IMPRESSIONS)
        assert_cents(data, "shortfall_value_cents", SHORTFALL_VALUE_CENTS)
        assert data["offer_round"] == 0, (
            f"the make-good was never offered, expected offer_round 0, "
            f"got {data['offer_round']}"
        )

    def test_the_waiver_settles_the_stewardship_axis_without_minting_airtime(self, api):
        """The cash waiver books 100,000 waived impressions against the buy,
        closes its open shortfall and carries stewardship to MADE_GOOD while the
        buy keeps its single original unit line.

        PRD: "The buy's `waived_impressions` grows by the make-good's
        `shortfall_impressions` and its `open_shortfall_impressions` is
        recomputed; because that reaches 0, `stewardship_status` moves
        `UNDER_DELIVERED → MADE_GOOD`."

        Design: Corner/endpoints/waive_defaults_the_credit_to_the_frozen_shortfall_value
        """
        world = _open_make_good(api)

        get_success_data(
            api.waive_make_good(world["make_good_id"], fa.waive_payload(), CONTROLLER_HEADERS)
        )

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS), 200)
        assert_impressions(buy, "waived_impressions", SHORTFALL_IMPRESSIONS)
        assert_impressions(buy, "made_good_impressions", 0)
        assert_impressions(buy, "open_shortfall_impressions", 0)
        assert_buy_axes(buy, stewardship_status="MADE_GOOD")

        units = api.list_buy_units(BUYER_HEADERS, params={"buy_id": world["buy_id"]})
        _, units_meta = validate_paginated(units)
        assert_pagination_meta(units_meta, expected_total=1, expected_has_more=False)
