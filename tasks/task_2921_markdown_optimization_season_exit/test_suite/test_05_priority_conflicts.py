"""Requests that break two rules at once, where the ladder of §2.7 decides
which single code comes back.
"""

import pytest

from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import markdown_step_payload, salvage_order_payload


def _closed_season(api):
    sc = fx.base_scenario(api)
    fx.transition_season(api, sc.season["id"], "EXIT_WINDOW")
    fx.generate_review(api, sc.season["id"], "FINAL")
    sc["season"] = fx.transition_season(api, sc.season["id"], "CLOSED")
    return sc


class TestClosedSeasonOutranksUnitShortfall:
    """Rule 9 is reached long before rule 32."""

    def test_the_closed_season_is_reported_and_not_the_unit_shortfall(
        self, api, analyst
    ):
        """PRD 2.7 rule 9: "A season whose status is `CLOSED` accepts no write at
        all, including another exit review, and rejects with `ERR_SEASON_CLOSED`
        (409)." The ladder is normative: "When a request violates more than one
        rule, the response is decided by the lowest-numbered rule in the ordered
        ladder below."

        Design: Difficulty/priority_pair_validation_conflict/closed_season_outranks_disposition_unit_shortfall
        """
        sc = _closed_season(api)

        response = api.create_disposition_order(
            salvage_order_payload(sc.season["id"], sc.item["id"], 9999, 300), analyst
        )

        validate_error(response, ApiErrorId.SEASON_CLOSED, 409)

    def test_the_refused_order_leaves_no_row_and_no_committed_units(
        self, api, analyst
    ):
        """PRD 2.7 rule 32: "Unit availability, reported as
        `ERR_INSUFFICIENT_AVAILABLE_UNITS` (409): a disposition order's `units` may
        not exceed the item's on-hand units less those already committed to
        disposition, `settled_units` may not exceed the order's `units`, and a
        posted week's `units_sold` may not exceed the item's on-hand units at
        posting time."

        Design: Difficulty/priority_pair_validation_conflict/closed_season_outranks_disposition_unit_shortfall
        """
        sc = _closed_season(api)
        api.create_disposition_order(
            salvage_order_payload(sc.season["id"], sc.item["id"], 9999, 300), analyst
        )

        _, meta = validate_paginated(
            api.list_disposition_orders(analyst, {"season_id": sc.season["id"]})
        )
        item = fx.read_item(api, sc.item["id"])

        assert meta["total_count"] == 0
        assert item["units_committed_disposition"] == 0
        assert item["on_hand_units"] == 343
        assert fx.read_season(api, sc.season["id"])["status"] == "CLOSED"


def _protected_plan(api):
    sc = fx.base_scenario(api)
    fx.set_clock(api, "2026-09-27T00:00:00Z")
    estimate = fx.create_estimate(api, sc.item["id"])
    sc["estimate"] = fx.certify_estimate(api, estimate["id"])
    sc["plan"] = fx.create_plan(api, sc.season["id"], sc.item["id"], sc.estimate["id"])
    sc["step1"] = fx.add_rung(api, sc.plan["id"], 1, "2026-10-15", 30.00)
    return sc


class TestProtectedPeriodOutranksDepthMonotonicity:
    """Rule 17 beats both rule 18 and rule 22."""

    def test_the_protected_period_is_reported_and_not_the_shape_violations(
        self, api, analyst
    ):
        """PRD 2.7 rule 17: "Protected new-arrival period on ladder-rung creation:
        the rung's `effective_date` must be strictly later than the item's
        `protected_until_date`; a rung falling exactly on that date is a violation,
        reported as `ERR_PROTECTED_PERIOD_ACTIVE` (422)."

        Design: Difficulty/priority_pair_validation_conflict/protected_period_outranks_depth_monotonicity
        """
        sc = _protected_plan(api)

        response = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(2, "2026-10-01", 20.00), analyst
        )

        validate_error(response, ApiErrorId.PROTECTED_PERIOD_ACTIVE, 422)

    def test_the_refused_rung_leaves_the_ladder_at_one_step(self, api, analyst):
        """PRD 2.7 rule 22: "Ladder shape on rung creation: `step_index` must equal
        the plan's current `ladder_step_count` plus 1, else
        `ERR_STEP_INDEX_OUT_OF_SEQUENCE` (422); `ladder_step_count` must be below 4,
        else `ERR_MAX_LADDER_STEPS` (422); and `depth_pct` must be strictly greater
        than the previous rung's `depth_pct`, else `ERR_DEPTH_NOT_MONOTONIC` (422)."

        Design: Difficulty/priority_pair_validation_conflict/protected_period_outranks_depth_monotonicity
        """
        sc = _protected_plan(api)
        api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(2, "2026-10-01", 20.00), analyst
        )

        _, meta = validate_paginated(api.list_plan_steps(sc.plan["id"], analyst))

        assert meta["total_count"] == 1
        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 1

    def test_a_new_arrival_item_clamps_the_recommendation_up_to_the_floor(self, api):
        """PRD 3.5: "The base depth is keyed to the item's `lifecycle_stage`: 0.00
        percent for `NEW_ARRIVAL`, 5.00 for `CORE`, 15.00 for `AGING`, 30.00 for
        `CLEARANCE`, 50.00 for `EXIT_PENDING` and 0.00 for `DISPOSED` — every stage is
        keyed, because a plan may be opened on an item at any stage." PRD 3.2:
        "`protected_until_date` is `first_receipt_date` advanced by the category's
        protected period: six weeks for `APPAREL`, eight weeks for `FOOTWEAR`, four
        weeks for `ACCESSORIES` and three weeks for `SEASONAL_DECOR` — that is, 42,
        56, 28 and 21 days respectively."

        Design: Difficulty/priority_pair_validation_conflict/protected_period_outranks_depth_monotonicity
        """
        sc = _protected_plan(api)

        item = fx.read_item(api, sc.item["id"])

        assert item["protected_until_date"] == "2026-10-01"
        assert item["lifecycle_stage"] == "NEW_ARRIVAL"
        assert sc.plan["recommended_depth_pct"] == pytest.approx(10.00, abs=0.001)


def _new_arrival_in_exit_window(api):
    sc = fx.base_scenario(api)
    sc["item_c"] = fx.create_item(
        api,
        sc.season["id"],
        sku="C-3003",
        first_receipt_date="2026-10-05",
        original_retail_cents=2999,
        unit_cost_cents=1200,
        units_received_total=500,
    )
    sc["season"] = fx.transition_season(api, sc.season["id"], "EXIT_WINDOW")
    return sc


class TestNewArrivalIneligibilityOutranksUnitShortfall:
    """Rule 16 is reached before rule 32."""

    def test_the_eligibility_gate_is_reported_and_not_the_unit_shortfall(
        self, api, analyst
    ):
        """PRD 2.7 rule 16: "Disposition eligibility on disposition-order creation:
        the item's `lifecycle_stage` must be `CLEARANCE` or `EXIT_PENDING`, else
        `ERR_ITEM_NOT_EXIT_ELIGIBLE` (422)."

        Design: Difficulty/priority_pair_validation_conflict/new_arrival_ineligibility_outranks_disposition_unit_shortfall
        """
        sc = _new_arrival_in_exit_window(api)

        response = api.create_disposition_order(
            salvage_order_payload(sc.season["id"], sc.item_c["id"], 9999, 300), analyst
        )

        validate_error(response, ApiErrorId.ITEM_NOT_EXIT_ELIGIBLE, 422)

    def test_the_ineligible_item_keeps_its_untouched_pool(self, api, analyst):
        """PRD 3.2: "Registration also initialises `current_retail_cents` to
        `original_retail_cents`, sets `on_hand_units` to `units_received_total`, and
        leaves `units_sold_total`, `units_committed_disposition`,
        `units_disposed_total` and `sample_weeks` at 0, `sell_through_pct` at 0.00,
        `weeks_of_supply` at 999.99, `permanent_markdown_reserve_cents` and
        `promo_discount_cents` at 0, `lifecycle_stage` at `NEW_ARRIVAL` and
        `markdown_state` at `FULL_PRICE`."

        Design: Difficulty/priority_pair_validation_conflict/new_arrival_ineligibility_outranks_disposition_unit_shortfall
        """
        sc = _new_arrival_in_exit_window(api)
        api.create_disposition_order(
            salvage_order_payload(sc.season["id"], sc.item_c["id"], 9999, 300), analyst
        )

        item = fx.read_item(api, sc.item_c["id"])
        _, meta = validate_paginated(
            api.list_disposition_orders(analyst, {"item_id": sc.item_c["id"]})
        )

        assert item["protected_until_date"] == "2026-11-16"
        assert item["lifecycle_stage"] == "NEW_ARRIVAL"
        assert item["units_committed_disposition"] == 0
        assert item["on_hand_units"] == 500
        assert meta["total_count"] == 0
