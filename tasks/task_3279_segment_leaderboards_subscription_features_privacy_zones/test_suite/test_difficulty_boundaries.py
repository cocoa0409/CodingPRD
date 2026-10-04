"""Difficulty queue A: boundary precision.

free_tier_cap_third_plan_allowed: the weekly free-tier route-plan count cap.
heatmap_min_count_boundary: the heat map cell visibility threshold.
"""

from test_helpers import (
    ApiErrorId,
    create_active_segment,
    create_athlete,
    create_route_plan,
    create_subscription,
    make_athlete_headers,
    upload_heatmap_ride,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_route_plan_payload


class TestFreeTierCapThirdPlanAllowed:
    def test_third_plan_allowed_fourth_rejected(self, api):
        """PRD 3.8: "Free-tier athletes are capped at three plans sharing the same `week_start`: creating the third plan succeeds, and the fourth is rejected with `ERR_FREE_TIER_ROUTE_CAP` unless the athlete holds an active subscription (§2.9)."

        Design: Difficulty/boundary_precision_check/free_tier_cap_third_plan_allowed
        """
        athlete = create_athlete(api, email="fb_cap@x.com", display_name="FB Cap")
        headers = make_athlete_headers(athlete["id"])
        for name in ("Plan One", "Plan Two", "Plan Three"):
            resp = api.create_route_plan(athlete["id"], create_route_plan_payload(name=name, week_start="2026-09-07"), headers)
            validate_success(resp, 201)
        fourth = api.create_route_plan(athlete["id"], create_route_plan_payload(name="Plan Four", week_start="2026-09-07"), headers)
        validate_error(fourth, ApiErrorId.ERR_FREE_TIER_ROUTE_CAP)

    def test_cap_is_per_week_start(self, api):
        """PRD 3.8: "Free-tier athletes are capped at three plans sharing the same `week_start`" — a different week_start carries its own allowance.

        Design: Difficulty/boundary_precision_check/free_tier_cap_third_plan_allowed
        """
        athlete = create_athlete(api, email="fb_wk@x.com", display_name="FB Wk")
        headers = make_athlete_headers(athlete["id"])
        for i in range(3):
            validate_success(api.create_route_plan(athlete["id"], create_route_plan_payload(name=f"W1 {i}", week_start="2026-09-07"), headers), 201)
        other_week = api.create_route_plan(athlete["id"], create_route_plan_payload(name="W2 0", week_start="2026-09-14"), headers)
        validate_success(other_week, 201)

    def test_subscribed_athlete_beyond_cap(self, api):
        """PRD 2.9: "the fourth and subsequent plans in the same week require an active subscription".

        Design: Difficulty/boundary_precision_check/free_tier_cap_third_plan_allowed
        """
        athlete = create_athlete(api, email="fb_sub@x.com", display_name="FB Sub")
        create_subscription(api, athlete["id"])
        headers = make_athlete_headers(athlete["id"])
        for i in range(4):
            validate_success(api.create_route_plan(athlete["id"], create_route_plan_payload(name=f"Sub {i}", week_start="2026-09-07"), headers), 201)


class TestHeatmapMinCountBoundary:
    def _world(self, api, suffix, city):
        owner = create_athlete(api, email=f"hc_{suffix}@x.com", display_name=f"HC {suffix}")
        segment = create_active_segment(
            api, owner["id"], name=f"Heat Segment {suffix}", sport_type="RIDE",
            start_lat=42.00, start_lng=-127.00, end_lat=42.01, end_lng=-127.00,
            distance_m=1000, city=city,
        )
        riders = [create_athlete(api, email=f"h{i}_{suffix}@x.com", display_name=f"H{i} {suffix}") for i in range(1, 4)]
        return owner, segment, riders

    def test_cell_invisible_at_two_contributions_visible_at_three(self, api):
        """PRD 3.8: "A cell surfaces publicly only once its `contribution_count` reaches 3; the boundary is inclusive, and the heat map endpoint may be filtered by `city` or `sport_type`."

        Design: Difficulty/boundary_precision_check/heatmap_min_count_boundary
        """
        owner, segment, riders = self._world(api, "hm1", "Heatville1")
        reader = make_athlete_headers(riders[0]["id"])
        upload_heatmap_ride(api, segment, riders[0]["id"], started_at="2026-09-01T06:00:00Z", idempotency_key="hm1-1")
        upload_heatmap_ride(api, segment, riders[1]["id"], started_at="2026-09-01T07:00:00Z", idempotency_key="hm1-2")
        before = validate_success(api.get_heatmap(reader, params={"city": "Heatville1", "sport_type": "RIDE"}), 200)
        assert before == []
        upload_heatmap_ride(api, segment, riders[2]["id"], started_at="2026-09-01T08:00:00Z", idempotency_key="hm1-3")
        after = validate_success(api.get_heatmap(reader, params={"city": "Heatville1", "sport_type": "RIDE"}), 200)
        assert len(after) == 1
        assert after[0]["city"] == "Heatville1"
        assert after[0]["sport_type"] == "RIDE"
        assert after[0]["contribution_count"] == 3

    def test_cell_invisible_at_one_contribution(self, api):
        """PRD 3.8: "A cell surfaces publicly only once its `contribution_count` reaches 3".

        Design: Difficulty/boundary_precision_check/heatmap_min_count_boundary
        """
        owner, segment, riders = self._world(api, "hm2", "Heatville2")
        upload_heatmap_ride(api, segment, riders[0]["id"], started_at="2026-09-01T06:00:00Z", idempotency_key="hm2-1")
        cells = validate_success(api.get_heatmap(make_athlete_headers(riders[0]["id"]), params={"city": "Heatville2", "sport_type": "RIDE"}), 200)
        assert cells == []
