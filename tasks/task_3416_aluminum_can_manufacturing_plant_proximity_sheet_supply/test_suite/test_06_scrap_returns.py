"""Closed-loop scrap returns: closed-interval conflicts, daily cap, listing,
and credit feeding recycled content (PRD §2.3, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    set_clock, create_plant, create_customer, create_scrap_return,
    credit_scrap_return, publish_index, setup_in_progress_run, complete_run,
    get_plant, make_customer_planner_headers, manager, api_client,
)


class TestPickupWindows:
    def test_scrap_pickup_touching_windows_conflict_closed_interval(self, api):
        """PRD §3.8: "Pickup windows conflict under closed-interval semantics:
        two windows of the same customer that merely touch — one's end equal to
        the other's start — already conflict, and any overlap with another
        `SCHEDULED` return of that customer is rejected with
        `ERR_PICKUP_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/scrap_pickup_windows_closed_interval_touching_conflicts_and_daily_cap
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        create_scrap_return(customer["id"], plant["id"],
                            pickup_window_start="2026-09-05T09:00:00Z",
                            pickup_window_end="2026-09-05T10:00:00Z")
        resp = api.create_scrap_return(
            customer["id"],
            {"plant_id": plant["id"],
             "pickup_window_start": "2026-09-05T10:00:00Z",
             "pickup_window_end": "2026-09-05T11:00:00Z",
             "declared_weight_lbs": 4000},
            make_customer_planner_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_CONFLICT)

    def test_scrap_pickup_daily_cap_third_pickup_rejected(self, api):
        """PRD §3.8: "A customer may also hold at most two `SCHEDULED` pickups
        on a single UTC day; a request that would push the count beyond two is
        rejected with `ERR_PICKUP_DAILY_LIMIT`".

        Design: Difficulty/resource_temporal_overlap/scrap_pickup_windows_closed_interval_touching_conflicts_and_daily_cap
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        create_scrap_return(customer["id"], plant["id"],
                            pickup_window_start="2026-09-05T09:00:00Z",
                            pickup_window_end="2026-09-05T10:00:00Z")
        second = create_scrap_return(customer["id"], plant["id"],
                                     pickup_window_start="2026-09-05T12:00:00Z",
                                     pickup_window_end="2026-09-05T13:00:00Z",
                                     declared_weight_lbs=4000)
        assert second["status"] == "SCHEDULED"
        resp = api.create_scrap_return(
            customer["id"],
            {"plant_id": plant["id"],
             "pickup_window_start": "2026-09-05T15:00:00Z",
             "pickup_window_end": "2026-09-05T16:00:00Z",
             "declared_weight_lbs": 4000},
            make_customer_planner_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_PICKUP_DAILY_LIMIT)
        rows, meta = validate_paginated(api.list_scrap_returns(
            manager(), params={"customer_id": customer["id"],
                               "status": "SCHEDULED"}))
        assert len(rows) == 2


class TestScrapListing:
    def test_scrap_returns_list_filters_and_paginates(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; it defaults to 10 ... List responses carry the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`" and
        "the scrap-return list accepts `customer_id`, `plant_id`, and `status`".

        Design: Corner/entities/scrap_returns_list_filters_and_paginates
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        for day, weight in (("05", 5000), ("06", 6000), ("07", 7000)):
            create_scrap_return(
                customer["id"], plant["id"],
                pickup_window_start=f"2026-09-{day}T09:00:00Z",
                pickup_window_end=f"2026-09-{day}T10:00:00Z",
                declared_weight_lbs=weight)
        rows, meta = validate_paginated(api.list_scrap_returns(
            manager(), params={"customer_id": customer["id"],
                               "limit": 2, "offset": 0}))
        assert len(rows) == 2 and meta["total_count"] == 3
        assert meta["has_more"] is True
        rows2, meta2 = validate_paginated(api.list_scrap_returns(
            manager(), params={"customer_id": customer["id"],
                               "limit": 2, "offset": 2}))
        assert len(rows2) == 1 and meta2["total_count"] == 3
        assert meta2["has_more"] is False
        rows3, _ = validate_paginated(api.list_scrap_returns(
            manager(), params={"customer_id": customer["id"],
                               "status": "SCHEDULED"}))
        assert len(rows3) == 3
        rows4, _ = validate_paginated(api.list_scrap_returns(
            manager(), params={"plant_id": plant["id"]}))
        assert len(rows4) == 3
        rows5, meta5 = validate_paginated(api.list_scrap_returns(manager()))
        assert len(rows5) == 3 and meta5["limit"] == 10 and meta5["offset"] == 0


class TestScrapCredit:
    def test_scrap_credit_sets_fields_and_recomputes_recycled_content(self, api):
        """PRD §3.8: "The verified weight is recorded as `credited_weight_lbs`
        alongside the `grade`, and the return moves from `SCHEDULED` to
        `CREDITED`." and "the plant's `recycled_content_pct` is recomputed as
        100 times `scrap_credit_lbs_ytd` divided by `metal_consumed_lbs_ytd`,
        rounded half-up to 2 decimal places".

        Design: Corner/state_machines/scrap_credit_sets_fields_and_recomputes_recycled_content
        """
        # Completion requires the prior-month index (2026-08) to be published.
        set_clock()
        publish_index("2026-08", 128.0)
        publish_index("2026-09", 128.0)
        env = setup_in_progress_run(run_overrides={"scheduled_qty": 250000})
        complete_run(env["run"]["id"], 250000, 5000)
        sr = create_scrap_return(env["customer"]["id"], env["plant"]["id"],
                                 pickup_window_start="2026-09-05T09:00:00Z",
                                 pickup_window_end="2026-09-05T10:00:00Z",
                                 declared_weight_lbs=5800)
        credited = credit_scrap_return(sr["id"], 6000, grade="UBC")
        assert credited["status"] == "CREDITED"
        assert credited["credited_weight_lbs"] == 6000
        assert credited["grade"] == "UBC"
        plant = get_plant(env["plant"]["id"])
        assert plant["scrap_credit_lbs_ytd"] == 6000
        assert plant["metal_consumed_lbs_ytd"] == pytest.approx(7650.0)
        # round_half_up(100 * 6000 / 7650, 2) == 78.43
        assert plant["recycled_content_pct"] == pytest.approx(78.43, abs=0.005)
