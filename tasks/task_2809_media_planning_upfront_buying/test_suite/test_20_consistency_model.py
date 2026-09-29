"""Immediate consistency: one option roll-up rewrites the exercise record, the
buy, its allocation and the campaign, and every one of those effects is visible
in the same response or in the very next read."""

from test_helpers import (
    BUYER_HEADERS,
    BUYER_USER_ID,
    assert_cents,
    assert_impressions,
    assert_instant_field,
    assert_pct2,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    make_seller_rep_headers,
    validate_paginated,
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


def _placed_buy_inside_its_option_window(api):
    """A placed buy guaranteeing 1,000,000 impressions at 2200 CPM.  The clock is
    left at its startup instant, which is well before the buy's
    ``option_window_close`` of 45 days ahead of the 2026-11-01 flight start, so
    the option right is live."""
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
    fx.counter(
        api,
        negotiation["id"],
        seller["id"],
        counter_cpm_cents=2200,
        counter_impressions=1_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    fx.add_unit(api, buy["id"], avail["id"], **UNIT)
    fx.place_buy(api, buy["id"], campaign["id"])
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "seller_headers": make_seller_rep_headers(seller["id"]),
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": avail["id"],
        "buy_id": buy["id"],
    }


def _roll_the_option(api, world, requested_pct=10.00):
    """Exercise a ten percent option roll-up against the placed buy."""
    return api.create_rights_exercise(
        fa.rights_exercise_payload(world["buy_id"], "OPTION_ROLL", requested_pct),
        BUYER_HEADERS,
    )


class TestRightsExerciseIsVisibleImmediately:
    def test_the_created_record_already_carries_both_signed_deltas(self, api):
        """The 201 body of the option roll-up is itself the answer: it reports the
        100,000 impressions added and the 235,400 cents of gross the recomputation
        produced, without any follow-up read.

        PRD: "The exercise records `delta_gross_cents`, the signed difference
        between the buy's `gross_cost_cents` after the recomputation and its value
        before it — a large option roll can therefore cross a tier boundary
        downward and produce a proportionally smaller commission increase than the
        impression increase would suggest."

        Design: Corner/consistency_model/rights_exercise_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = _placed_buy_inside_its_option_window(api)

        record = validate_success(_roll_the_option(api, world), 201)

        assert record["kind"] == "OPTION_ROLL"
        assert_pct2(record, "requested_pct", 10.00)
        assert_impressions(record, "delta_impressions", 100_000)
        assert_cents(record, "delta_gross_cents", 235_400)
        assert record["cancelled_unit_count"] == 0
        assert record["exercised_by_user_id"] == BUYER_USER_ID
        assert_instant_field(record, "exercised_at", "2026-08-01T00:00:00Z")

    def test_the_created_record_already_carries_the_ceiling_it_was_measured_against(
        self, api
    ):
        """The exercise stamps the buy's own option ceiling of 25 onto itself, so
        the record explains its own admission without a read of the buy.

        PRD: "For an `OPTION_ROLL` the ceiling is simply the buy's own
        `option_pct_ceiling`, copied from the negotiation."

        Design: Corner/consistency_model/rights_exercise_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = _placed_buy_inside_its_option_window(api)

        record = validate_success(_roll_the_option(api, world), 201)

        assert_pct2(record, "applied_ceiling_pct", 25.00)
        assert_pct2(fx.read_buy(api, world["buy_id"]), "option_pct_cumulative", 10.00)

    def test_the_next_read_of_the_buy_already_shows_the_recomputed_cost_stack(self, api):
        """One read after the exercise — no retry, no polling — the buy already
        guarantees 1,100,000 impressions and carries the whole stack rebuilt on
        that new figure.

        PRD: "The buy's `guaranteed_impressions` is then adjusted by that signed
        amount and its entire cost stack is recomputed from scratch with the
        commission tier re-selected on the new pre-commission net:
        `net_media_cost_cents`, `commission_rate`, `agency_commission_cents` and
        `gross_cost_cents` are all rewritten by the three-tier arithmetic of
        §3.5."

        Design: Corner/consistency_model/rights_exercise_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = _placed_buy_inside_its_option_window(api)
        validate_success(_roll_the_option(api, world), 201)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS), 200)

        assert_impressions(buy, "guaranteed_impressions", 1_100_000)
        assert_cents(buy, "net_media_cost_cents", 2_420_000)
        assert_pct4(buy, "commission_rate", 0.0700)
        assert_cents(buy, "agency_commission_cents", 169_400)
        assert_cents(buy, "gross_cost_cents", 2_589_400)

    def test_the_first_read_of_the_buy_is_not_a_warm_up_for_the_second(self, api):
        """The values the first read reports are already final: reading the buy
        again returns the same figures at the same version, so nothing was settled
        by the act of reading.

        PRD: "Cascades in this system are always deterministic and always complete
        — there is no queue and no eventual convergence."

        Design: Corner/consistency_model/rights_exercise_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = _placed_buy_inside_its_option_window(api)
        validate_success(_roll_the_option(api, world), 201)

        first = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS), 200)
        second = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS), 200)

        for field in (
            "guaranteed_impressions",
            "net_media_cost_cents",
            "agency_commission_cents",
            "gross_cost_cents",
            "version",
        ):
            assert second[field] == first[field], (
                f"{field} changed between two reads: {first[field]} then {second[field]}"
            )

    def test_the_next_read_of_the_allocation_already_shows_the_recomputed_commitment(
        self, api
    ):
        """The allocation the buy names has already absorbed the enlarged buy — its
        commitment reads the buy's new gross and its posture is still inside the
        plan.

        PRD: "The channel allocation named by the buy has its `committed_cents`
        and `posture` recomputed, and the campaign has its
        `committed_gross_cents`, `uncommitted_budget_cents` and `plan_posture`
        recomputed."

        Design: Corner/consistency_model/rights_exercise_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = _placed_buy_inside_its_option_window(api)
        validate_success(_roll_the_option(api, world), 201)

        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], BUYER_HEADERS), 200
        )

        assert_cents(allocation, "committed_cents", 2_589_400)
        assert allocation["posture"] == "WITHIN_PLAN"

    def test_the_next_read_of_the_campaign_already_shows_the_recomputed_ledger(self, api):
        """Two links up the chain, the campaign's budget ledger already balances on
        the new gross: 2,589,400 committed against 7,410,600 still uncommitted of
        the 10,000,000 budget.

        PRD: "The channel allocation named by the buy has its `committed_cents`
        and `posture` recomputed, and the campaign has its
        `committed_gross_cents`, `uncommitted_budget_cents` and `plan_posture`
        recomputed."

        Design: Corner/consistency_model/rights_exercise_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = _placed_buy_inside_its_option_window(api)
        validate_success(_roll_the_option(api, world), 201)

        campaign = validate_success(
            api.get_campaign(world["campaign_id"], BUYER_HEADERS), 200
        )

        assert_cents(campaign, "committed_gross_cents", 2_589_400)
        assert_cents(campaign, "uncommitted_budget_cents", 7_410_600)
        assert campaign["plan_posture"] == "WITHIN_PLAN"

    def test_the_exercise_is_listable_under_its_buy_on_the_very_next_request(self, api):
        """The record is discoverable immediately: the buy's exercise listing
        reports exactly one row, and it is the row the 201 returned.

        PRD: "A cascade is a chain of secondary effects triggered by one primary
        write, and every link in a chain fires within the same request."

        Design: Corner/consistency_model/rights_exercise_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = _placed_buy_inside_its_option_window(api)
        record = validate_success(_roll_the_option(api, world), 201)

        rows, meta = validate_paginated(
            api.list_rights_exercises(BUYER_HEADERS, {"buy_id": world["buy_id"]})
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == record["id"]
        assert_impressions(rows[0], "delta_impressions", 100_000)
        assert_cents(rows[0], "delta_gross_cents", 235_400)
