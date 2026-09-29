"""Interval conventions on the two temporal-overlap rules of the upfront API.

One class pins the half-open air-window test that guards an EXCLUSIVE avail, the
other the closed buffered-flight test that keeps rival advertiser categories apart
on a single seller.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    PLANNER_HEADERS,
    AllocationPosture,
    ApiErrorId,
    BuyStatus,
    ForecastStatus,
    UnitStatus,
    assert_allocation_posture,
    assert_buy_axes,
    assert_cents,
    assert_impressions,
    assert_instant_field,
    assert_pagination_meta,
    get_success_data,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ==========================================================================
# Instance 1 — the half-open air window on an EXCLUSIVE avail
# ==========================================================================
#: The flight the exclusive-avail campaign runs in, and the avail's own window.
EXCLUSIVE_FLIGHT_START = "2026-11-01T00:00:00Z"
EXCLUSIVE_FLIGHT_END = "2026-12-31T23:59:59Z"

#: Buy A's first line runs from the start of the flight to this instant.
UNIT_A1_END = "2026-11-20T00:00:00Z"

#: Buy B's line opens exactly where buy A's first line closes.
UNIT_B1_START = "2026-11-20T00:00:00Z"
UNIT_B1_END = "2026-12-10T00:00:00Z"

#: The refused line opens one second before buy B's line closes.
OVERLAPPING_START = "2026-12-09T23:59:59Z"

#: The accepted line opens exactly where buy B's line closes.
TOUCHING_START = "2026-12-10T00:00:00Z"
TOUCHING_END = "2026-12-20T00:00:00Z"

#: The avail's whole forecast, and what remains once three lines are held.
EXCLUSIVE_AVAIL_IMPRESSIONS = 20_000_000
EXCLUSIVE_AVAIL_REMAINING = 6_000_000


def _accepted_buy(api, campaign_id, seller_id, allocation_id, impressions, cpm_cents):
    """Open, counter and accept one negotiation, returning the buy it creates."""
    negotiation = get_success_data(
        api.create_negotiation(
            {
                "campaign_id": campaign_id,
                "seller_id": seller_id,
                "channel_allocation_id": allocation_id,
                "market": "UPFRONT",
                "channel": "LINEAR_TV",
                "requested_impressions": impressions,
                "opening_cpm_cents": cpm_cents - 100,
                "guarantee_pct": 100,
                "make_good_provision": "MAKE_GOOD_UNITS",
                "option_pct_ceiling": 25,
            },
            BUYER_HEADERS,
        )
    )
    get_success_data(
        api.counter_negotiation(
            negotiation["id"],
            {
                "expected_negotiation_version": negotiation["version"],
                "counter_cpm_cents": cpm_cents,
                "counter_impressions": impressions,
            },
            make_seller_rep_headers(seller_id),
        )
    )
    return get_success_data(api.accept_negotiation(negotiation["id"], None, BUYER_HEADERS))


def _exclusive_avail_world(api):
    """One EXCLUSIVE avail, two buys on one campaign, and buy A's opening line."""
    advertiser = get_success_data(
        api.create_advertiser(
            {
                "name": "Alder Home Goods",
                "category_code": "HOME",
                "credit_limit_cents": 200_000_000,
                "payment_terms_days": 30,
                "sequential_liability_enabled": True,
            },
            CONTROLLER_HEADERS,
        )
    )
    seller = get_success_data(
        api.create_seller(
            {
                "name": "Quarry Sports Network",
                "platform_types": ["LINEAR"],
                "make_good_capacity_impressions": 5_000_000,
            },
            CONTROLLER_HEADERS,
        )
    )
    campaign = get_success_data(
        api.create_campaign(
            {
                "advertiser_id": advertiser["id"],
                "name": "Exclusive Prime Test",
                "target_demo": "A25-54",
                "universe_thousands": 100_000,
                "reach_goal_pct": 40.0,
                "frequency_goal": 3.0,
                "total_budget_cents": 100_000_000,
                "flight_start": EXCLUSIVE_FLIGHT_START,
                "flight_end": EXCLUSIVE_FLIGHT_END,
                "fiscal_quarter": "2026Q4",
            },
            PLANNER_HEADERS,
        )
    )
    allocation = get_success_data(
        api.create_channel_allocation(
            {
                "campaign_id": campaign["id"],
                "channel": "LINEAR_TV",
                "allocation_pct": 100.00,
                "planned_cpm_cents": 2000,
                "planned_market": "UPFRONT",
                "primary_daypart": "PRIME",
            },
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
            {
                "seller_id": seller["id"],
                "market": "UPFRONT",
                "fiscal_quarter": "2026Q4",
                "daypart": "PRIME",
                "program": "Quarry Saturday",
                "platform": "LINEAR",
                "window_start": EXCLUSIVE_FLIGHT_START,
                "window_end": EXCLUSIVE_FLIGHT_END,
                "total_impressions": EXCLUSIVE_AVAIL_IMPRESSIONS,
                "forecast_cpm_cents": 2000,
                "exclusivity_mode": "EXCLUSIVE",
            },
            make_seller_rep_headers(seller["id"]),
        )
    )
    get_success_data(
        api.publish_inventory_forecast(
            forecast["id"], None, make_seller_rep_headers(seller["id"])
        )
    )
    buy_a = _accepted_buy(
        api, campaign["id"], seller["id"], allocation["id"], 3_000_000, 2000
    )
    buy_b = _accepted_buy(
        api, campaign["id"], seller["id"], allocation["id"], 3_000_000, 2000
    )
    unit_a1 = get_success_data(
        api.add_buy_unit(
            buy_a["id"],
            {
                "forecast_id": forecast["id"],
                "daypart": "PRIME",
                "program": "Quarry Saturday",
                "platform": "LINEAR",
                "units": 5,
                "unit_rate_cents": 1_200_000,
                "projected_impressions": 5_000_000,
                "air_window_start": EXCLUSIVE_FLIGHT_START,
                "air_window_end": UNIT_A1_END,
            },
            BUYER_HEADERS,
        )
    )
    return {
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "forecast_id": forecast["id"],
        "buy_a_id": buy_a["id"],
        "buy_b_id": buy_b["id"],
        "unit_a1": unit_a1,
    }


def _unit_payload(forecast_id, units, projected, window_start, window_end):
    """One prime linear line on the exclusive avail, over the named window."""
    return {
        "forecast_id": forecast_id,
        "daypart": "PRIME",
        "program": "Quarry Saturday",
        "platform": "LINEAR",
        "units": units,
        "unit_rate_cents": 1_200_000,
        "projected_impressions": projected,
        "air_window_start": window_start,
        "air_window_end": window_end,
    }


def _run_exclusive_triggers(api, world):
    """Add the touching line, the one-second overlap and the clear line, in order."""
    touching = api.add_buy_unit(
        world["buy_b_id"],
        _unit_payload(world["forecast_id"], 5, 5_000_000, UNIT_B1_START, UNIT_B1_END),
        BUYER_HEADERS,
    )
    overlapping = api.add_buy_unit(
        world["buy_a_id"],
        _unit_payload(
            world["forecast_id"], 4, 4_000_000, OVERLAPPING_START, TOUCHING_END
        ),
        BUYER_HEADERS,
    )
    clear = api.add_buy_unit(
        world["buy_a_id"],
        _unit_payload(world["forecast_id"], 4, 4_000_000, TOUCHING_START, TOUCHING_END),
        BUYER_HEADERS,
    )
    return {"touching": touching, "overlapping": overlapping, "clear": clear}


class TestExclusiveAvailHalfOpenAirWindow:
    """Three lines on one EXCLUSIVE avail, differing only in their start instant."""

    def test_the_line_starting_where_another_buys_line_ends_is_scheduled(self, api):
        """Buy B's line opens exactly at the instant buy A's line closes and is
        scheduled on the exclusive avail.

        PRD: "The overlap test treats each air window as half-open — inclusive of
        its start instant and exclusive of its end instant — so a line beginning
        exactly at the instant another line ends is accepted, while a line
        beginning one millisecond earlier is refused with
        `ERR_EXCLUSIVE_AVAIL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/exclusive_avail_accepts_touching_windows_rejects_one_second_overlap
        """
        world = _exclusive_avail_world(api)
        assert_instant_field(world["unit_a1"], "air_window_end", UNIT_A1_END)

        touching = api.add_buy_unit(
            world["buy_b_id"],
            _unit_payload(world["forecast_id"], 5, 5_000_000, UNIT_B1_START, UNIT_B1_END),
            BUYER_HEADERS,
        )

        line = validate_success(touching, expected_status=201)
        assert line["status"] == UnitStatus.SCHEDULED.value, (
            f"a line touching another buy's end instant must be SCHEDULED, "
            f"got {line['status']}"
        )
        assert_instant_field(line, "air_window_start", UNIT_B1_START)
        assert line["buy_id"] == world["buy_b_id"]

    def test_one_second_of_overlap_with_the_other_buys_line_is_refused(self, api):
        """A line opening one second before buy B's line closes overlaps it and is
        refused with the exclusive-avail conflict.

        PRD: "The overlap test treats each air window as half-open — inclusive of
        its start instant and exclusive of its end instant — so a line beginning
        exactly at the instant another line ends is accepted, while a line
        beginning one millisecond earlier is refused with
        `ERR_EXCLUSIVE_AVAIL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/exclusive_avail_accepts_touching_windows_rejects_one_second_overlap
        """
        world = _exclusive_avail_world(api)
        get_success_data(
            api.add_buy_unit(
                world["buy_b_id"],
                _unit_payload(
                    world["forecast_id"], 5, 5_000_000, UNIT_B1_START, UNIT_B1_END
                ),
                BUYER_HEADERS,
            )
        )

        overlapping = api.add_buy_unit(
            world["buy_a_id"],
            _unit_payload(
                world["forecast_id"], 4, 4_000_000, OVERLAPPING_START, TOUCHING_END
            ),
            BUYER_HEADERS,
        )

        validate_error(
            overlapping, ApiErrorId.EXCLUSIVE_AVAIL_CONFLICT, expected_status=409
        )

    def test_the_line_starting_at_the_other_buys_end_instant_is_scheduled(self, api):
        """After the refusal, a line opening exactly where buy B's line closes is
        scheduled at that instant.

        PRD: "The overlap test treats each air window as half-open — inclusive of
        its start instant and exclusive of its end instant — so a line beginning
        exactly at the instant another line ends is accepted, while a line
        beginning one millisecond earlier is refused with
        `ERR_EXCLUSIVE_AVAIL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/exclusive_avail_accepts_touching_windows_rejects_one_second_overlap
        """
        world = _exclusive_avail_world(api)
        responses = _run_exclusive_triggers(api, world)

        line = validate_success(responses["clear"], expected_status=201)
        assert line["status"] == UnitStatus.SCHEDULED.value, (
            f"a line opening at the other buy's end instant must be SCHEDULED, "
            f"got {line['status']}"
        )
        assert_instant_field(line, "air_window_start", TOUCHING_START)
        assert line["buy_id"] == world["buy_a_id"]

    def test_the_refused_line_took_no_hold_on_the_avail(self, api):
        """Only the three accepted holds drain the avail, which ends at 6,000,000 of
        20,000,000 impressions and stays PUBLISHED.

        PRD: "The remaining-availability figure is a live subtraction rather than a
        counter that only ever decreases: at any moment `available_impressions` is
        `total_impressions` less the sum of `projected_impressions` over the unit
        lines occupying this avail whose `status` is `SCHEDULED`, `AIRED`,
        `MAKE_GOOD_SCHEDULED` or `MAKE_GOOD_AIRED`."

        Design: Difficulty/resource_temporal_overlap/exclusive_avail_accepts_touching_windows_rejects_one_second_overlap
        """
        world = _exclusive_avail_world(api)
        _run_exclusive_triggers(api, world)

        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert_impressions(avail, "total_impressions", EXCLUSIVE_AVAIL_IMPRESSIONS)
        assert_impressions(
            avail, "available_impressions", EXCLUSIVE_AVAIL_REMAINING
        )
        assert avail["status"] == ForecastStatus.PUBLISHED.value, (
            f"an avail with inventory left must stay PUBLISHED, got {avail['status']}"
        )

    def test_each_buy_carries_only_the_lines_the_avail_accepted(self, api):
        """Buy A ends with the two lines that were accepted and buy B with one; the
        refused request left no line behind.

        PRD: "`total_count` always reflects the filtered population, not the whole
        collection."

        Design: Difficulty/resource_temporal_overlap/exclusive_avail_accepts_touching_windows_rejects_one_second_overlap
        """
        world = _exclusive_avail_world(api)
        _run_exclusive_triggers(api, world)

        rows_a, meta_a = validate_paginated(
            api.list_buy_units(BUYER_HEADERS, params={"buy_id": world["buy_a_id"]})
        )
        assert_pagination_meta(meta_a, expected_total=2)
        assert len(rows_a) == 2, f"buy A must carry two lines, got {len(rows_a)}"

        rows_b, meta_b = validate_paginated(
            api.list_buy_units(BUYER_HEADERS, params={"buy_id": world["buy_b_id"]})
        )
        assert_pagination_meta(meta_b, expected_total=1)
        assert len(rows_b) == 1, f"buy B must carry one line, got {len(rows_b)}"


# ==========================================================================
# Instance 2 — the closed buffered flight window of competitive separation
# ==========================================================================
#: The flight the first AUTOMOTIVE buy occupies on the shared seller.
P_FLIGHT_START = "2026-11-01T00:00:00Z"
P_FLIGHT_END = "2026-12-31T23:59:59Z"

#: Seven days past that flight end — the buffered end instant itself.
BUFFERED_END = "2027-01-07T23:59:59Z"

#: One second past the buffered end instant.
CLEAR_FLIGHT_START = "2027-01-08T00:00:00Z"

#: Every 2027Q1 flight closes here.
Q_FLIGHT_END = "2027-02-28T23:59:59Z"

#: The cost stack one 2,000,000-impression buy at CPM 2200 carries.
BUY_GROSS_CENTS = 4_708_000


def _category_plan(api, advertiser_id, name, flight_start, fiscal_quarter, target_demo):
    """One approved 30,000,000 cent campaign with a single prime linear allocation."""
    campaign = get_success_data(
        api.create_campaign(
            {
                "advertiser_id": advertiser_id,
                "name": name,
                "target_demo": target_demo,
                "universe_thousands": 100_000,
                "reach_goal_pct": 30.0,
                "frequency_goal": 3.0,
                "total_budget_cents": 30_000_000,
                "flight_start": flight_start,
                "flight_end": P_FLIGHT_END if fiscal_quarter == "2026Q4" else Q_FLIGHT_END,
                "fiscal_quarter": fiscal_quarter,
            },
            PLANNER_HEADERS,
        )
    )
    allocation = get_success_data(
        api.create_channel_allocation(
            {
                "campaign_id": campaign["id"],
                "channel": "LINEAR_TV",
                "allocation_pct": 100.00,
                "planned_cpm_cents": 2200,
                "planned_market": "UPFRONT",
                "primary_daypart": "PRIME",
            },
            PLANNER_HEADERS,
        )
    )
    get_success_data(api.submit_plan(campaign["id"], None, PLANNER_HEADERS))
    get_success_data(
        api.approve_plan(
            campaign["id"], None, make_advertiser_client_headers(advertiser_id)
        )
    )
    return {"campaign_id": campaign["id"], "allocation_id": allocation["id"]}


def _category_buy(api, plan, seller_id, forecast_id, air_start, air_end):
    """One 2,000,000-impression buy at CPM 2200, fully covered by a single line."""
    buy = _accepted_buy(
        api, plan["campaign_id"], seller_id, plan["allocation_id"], 2_000_000, 2200
    )
    get_success_data(
        api.add_buy_unit(
            buy["id"],
            {
                "forecast_id": forecast_id,
                "daypart": "PRIME",
                "program": "Highline Nightly",
                "platform": "LINEAR",
                "units": 1,
                "unit_rate_cents": 4_400_000,
                "projected_impressions": 2_000_000,
                "air_window_start": air_start,
                "air_window_end": air_end,
            },
            BUYER_HEADERS,
        )
    )
    plan["buy_id"] = buy["id"]
    return plan


def _published_avail(api, seller_id, fiscal_quarter, window_start, window_end, total):
    """One SHARED prime linear avail on the seller, published and buyable."""
    avail = get_success_data(
        api.create_inventory_forecast(
            {
                "seller_id": seller_id,
                "market": "UPFRONT",
                "fiscal_quarter": fiscal_quarter,
                "daypart": "PRIME",
                "program": "Highline Nightly",
                "platform": "LINEAR",
                "window_start": window_start,
                "window_end": window_end,
                "total_impressions": total,
                "forecast_cpm_cents": 2200,
                "exclusivity_mode": "SHARED",
            },
            make_seller_rep_headers(seller_id),
        )
    )
    get_success_data(
        api.publish_inventory_forecast(
            avail["id"], None, make_seller_rep_headers(seller_id)
        )
    )
    return avail["id"]


def _advertiser(api, name, category_code):
    """One brand client in the named competitive category."""
    return get_success_data(
        api.create_advertiser(
            {
                "name": name,
                "category_code": category_code,
                "credit_limit_cents": 50_000_000,
                "payment_terms_days": 30,
                "sequential_liability_enabled": True,
            },
            CONTROLLER_HEADERS,
        )
    )["id"]


def _category_separation_world(api):
    """One seller facing four unplaced buys: three AUTOMOTIVE and one ELECTRONICS."""
    seller_id = get_success_data(
        api.create_seller(
            {
                "name": "Highline Regional TV",
                "platform_types": ["LINEAR"],
                "make_good_capacity_impressions": 3_000_000,
            },
            CONTROLLER_HEADERS,
        )
    )["id"]
    adv_p = _advertiser(api, "Redstone Auto", "AUTOMOTIVE")
    adv_q = _advertiser(api, "Northpeak Auto", "AUTOMOTIVE")
    adv_r = _advertiser(api, "Volt Electronics", "ELECTRONICS")

    plan_p = _category_plan(api, adv_p, "Redstone Q4", P_FLIGHT_START, "2026Q4", "A25-54")
    avail_p = _published_avail(
        api, seller_id, "2026Q4", P_FLIGHT_START, P_FLIGHT_END, 5_000_000
    )
    plan_p = _category_buy(
        api,
        plan_p,
        seller_id,
        avail_p,
        "2026-11-02T00:00:00Z",
        "2026-11-30T23:59:59Z",
    )

    plan_q1 = _category_plan(
        api, adv_q, "Northpeak Q1 Touch", BUFFERED_END, "2027Q1", "A25-54"
    )
    avail_q = _published_avail(
        api, seller_id, "2027Q1", CLEAR_FLIGHT_START, Q_FLIGHT_END, 10_000_000
    )
    plan_q1 = _category_buy(
        api,
        plan_q1,
        seller_id,
        avail_q,
        "2027-01-10T00:00:00Z",
        "2027-02-10T23:59:59Z",
    )

    plan_q2 = _category_plan(
        api, adv_q, "Northpeak Q1 Clear", CLEAR_FLIGHT_START, "2027Q1", "A25-54"
    )
    plan_q2 = _category_buy(
        api,
        plan_q2,
        seller_id,
        avail_q,
        "2027-02-11T00:00:00Z",
        "2027-02-20T23:59:59Z",
    )

    plan_r = _category_plan(api, adv_r, "Volt Q1 Touch", BUFFERED_END, "2027Q1", "A18-49")
    plan_r = _category_buy(
        api,
        plan_r,
        seller_id,
        avail_q,
        "2027-02-21T00:00:00Z",
        "2027-02-28T23:59:59Z",
    )

    return {"seller_id": seller_id, "P": plan_p, "Q1": plan_q1, "Q2": plan_q2, "R": plan_r}


def _place(api, plan):
    """Place the plan's buy, quoting the campaign version last read."""
    campaign = get_success_data(api.get_campaign(plan["campaign_id"], BUYER_HEADERS))
    return api.place_buy(
        plan["buy_id"], {"expected_campaign_version": campaign["version"]}, BUYER_HEADERS
    )


def _run_placements(api, world):
    """Place P, then the rival flight touching its buffer, then Q2 and R."""
    responses = {"P": _place(api, world["P"])}
    before = get_success_data(
        api.get_campaign(world["Q1"]["campaign_id"], BUYER_HEADERS)
    )
    responses["q1_campaign_version"] = before["version"]
    responses["Q1"] = api.place_buy(
        world["Q1"]["buy_id"],
        {"expected_campaign_version": before["version"]},
        BUYER_HEADERS,
    )
    responses["Q2"] = _place(api, world["Q2"])
    responses["R"] = _place(api, world["R"])
    return responses


class TestCategorySeparationClosedBufferedWindow:
    """Four placements on one seller, differing only in start instant and category."""

    def test_the_first_automotive_buy_takes_the_sellers_flight_window(self, api):
        """The AUTOMOTIVE buy that goes first is placed over 2026-11-01 to
        2026-12-31T23:59:59Z and becomes the occupancy the buffer is measured from.

        PRD: "A successful placement moves `buy_status` `PENDING_PLACEMENT →
        PLACED`, records the acting `X-User-ID` as `placed_by_user_id` on the buy,
        and increments the campaign's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/category_separation_buffer_rejects_flight_touching_the_buffered_end
        """
        world = _category_separation_world(api)
        responses = _run_placements(api, world)

        buy = validate_success(responses["P"])
        assert_buy_axes(buy, buy_status=BuyStatus.PLACED.value)
        assert_instant_field(buy, "flight_start", P_FLIGHT_START)
        assert_instant_field(buy, "flight_end", P_FLIGHT_END)
        assert buy["placed_by_user_id"] == "buyer-01", (
            f"the acting buyer must be recorded, got {buy['placed_by_user_id']!r}"
        )

    def test_the_rival_flight_starting_on_the_buffered_end_instant_is_refused(self, api):
        """A second AUTOMOTIVE flight whose start is exactly the buffered end of the
        first is refused as a competitive-separation conflict.

        PRD: "Both intervals in this test are **closed**, so a flight starting
        exactly on the buffered end instant of a rival's window is a conflict, not a
        near miss."

        Design: Difficulty/resource_temporal_overlap/category_separation_buffer_rejects_flight_touching_the_buffered_end
        """
        world = _category_separation_world(api)
        responses = _run_placements(api, world)

        validate_error(
            responses["Q1"], ApiErrorId.CATEGORY_SEPARATION_CONFLICT, expected_status=409
        )

    def test_the_refused_placement_commits_nothing_on_the_rival_plan(self, api):
        """The refused rival buy stays at PENDING_PLACEMENT, so its allocation
        commits nothing and its campaign version never moves.

        PRD: "An allocation's `committed_cents` is the sum of `gross_cost_cents`
        over buys whose `channel_allocation_id` is this allocation and whose
        `buy_status` is `PLACED`, `IN_FLIGHT`, `COMPLETED` or `CLOSED`."

        Design: Difficulty/resource_temporal_overlap/category_separation_buffer_rejects_flight_touching_the_buffered_end
        """
        world = _category_separation_world(api)
        responses = _run_placements(api, world)

        buy = validate_success(api.get_buy(world["Q1"]["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, buy_status=BuyStatus.PENDING_PLACEMENT.value)

        allocation = validate_success(
            api.get_channel_allocation(world["Q1"]["allocation_id"], PLANNER_HEADERS)
        )
        assert_cents(allocation, "committed_cents", 0)
        assert_allocation_posture(
            allocation, posture=AllocationPosture.WITHIN_PLAN.value
        )

        campaign = validate_success(
            api.get_campaign(world["Q1"]["campaign_id"], BUYER_HEADERS)
        )
        assert campaign["version"] == responses["q1_campaign_version"], (
            f"a refused placement must not move the campaign version: expected "
            f"{responses['q1_campaign_version']}, got {campaign['version']}"
        )

    def test_the_flight_one_second_past_the_buffered_end_is_placed(self, api):
        """The same AUTOMOTIVE brand's other flight, opening one second past the
        buffered end instant, is placed.

        PRD: "Both intervals in this test are **closed**, so a flight starting
        exactly on the buffered end instant of a rival's window is a conflict, not a
        near miss."

        Design: Difficulty/resource_temporal_overlap/category_separation_buffer_rejects_flight_touching_the_buffered_end
        """
        world = _category_separation_world(api)
        responses = _run_placements(api, world)

        buy = validate_success(responses["Q2"])
        assert_buy_axes(buy, buy_status=BuyStatus.PLACED.value)
        assert_instant_field(buy, "flight_start", CLEAR_FLIGHT_START)

    def test_the_electronics_flight_touching_the_buffer_is_placed(self, api):
        """A flight identical to the refused one is placed because its advertiser
        carries a different category_code.

        PRD: "For every buy already placed on the same seller whose campaign belongs
        to a *different* advertiser carrying the *same* `category_code`, the system
        takes that existing buy's flight window and expands it by seven days at each
        end."

        Design: Difficulty/resource_temporal_overlap/category_separation_buffer_rejects_flight_touching_the_buffered_end
        """
        world = _category_separation_world(api)
        responses = _run_placements(api, world)

        buy = validate_success(responses["R"])
        assert_buy_axes(buy, buy_status=BuyStatus.PLACED.value)
        assert_instant_field(buy, "flight_start", BUFFERED_END)
        assert_instant_field(buy, "flight_end", Q_FLIGHT_END)

    def test_only_the_three_placed_buys_commit_gross_on_their_campaigns(self, api):
        """The three placed campaigns each commit 4,708,000 cents while the refused
        one commits nothing.

        PRD: "Separately, the campaign's `committed_gross_cents` is the sum of
        `gross_cost_cents` over the campaign's buys whose `buy_status` is `PLACED`,
        `IN_FLIGHT`, `COMPLETED` or `CLOSED` — buys still at `PENDING_PLACEMENT` and
        buys that reached `CANCELLED` are excluded — and its
        `uncommitted_budget_cents` is `total_budget_cents` less that committed
        figure."

        Design: Difficulty/resource_temporal_overlap/category_separation_buffer_rejects_flight_touching_the_buffered_end
        """
        world = _category_separation_world(api)
        _run_placements(api, world)

        for key in ("P", "Q2", "R"):
            campaign = validate_success(
                api.get_campaign(world[key]["campaign_id"], BUYER_HEADERS)
            )
            assert_cents(campaign, "committed_gross_cents", BUY_GROSS_CENTS)

        blocked = validate_success(
            api.get_campaign(world["Q1"]["campaign_id"], BUYER_HEADERS)
        )
        assert_cents(blocked, "committed_gross_cents", 0)
