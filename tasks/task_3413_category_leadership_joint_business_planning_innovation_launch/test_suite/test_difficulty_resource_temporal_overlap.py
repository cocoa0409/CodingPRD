"""Difficulty queue — temporal resource-overlap semantics.

Two interval geometries: promotional events occupy half-open
[start_date, end_date) intervals that may touch but never intersect within one
(plan, event_type) (PRD §3.2), while launches of one plan must keep a minimum
84-day separation that passes at exactly 84 days (PRD §3.5). Each test
translates one difficulty-design instance and cites the PRD rule it pins.
"""
from test_helpers import (
    ApiErrorId,
    assert_innovation_launch,
    assert_promotional_event,
    setup_activated_plan,
    validate_error,
    validate_success,
)


def _feature(name, start, end):
    return {
        "name": name,
        "event_type": "FEATURE",
        "start_date": start,
        "end_date": end,
        "discount_depth_pct": 20,
    }


def test_half_open_adjacency_passes_but_intersection_fails(api, manufacturer_planner_headers):
    """PRD §3.2: "An event occupies the half-open interval from its `start_date` up to but not including its `end_date`, and the calendar forbids collisions: within one plan and one `event_type`, a new event whose interval intersects an existing `PENCILED` or `LOCKED` event is rejected with `ERR_PROMO_OVERLAP` (HTTP 409), while pure adjacency — one event's `end_date` equal to another's `start_date` — is expressly allowed."

    With A = [03-01, 03-10) penciled: B = [03-10, 03-20) touches A and is
    created, while C = [03-09, 03-12) intersects both and is rejected.

    Design: Difficulty/resource_temporal_overlap/promo_overlap_half_open_adjacency
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]

    event_a = validate_success(
        api.create_event(plan_id, _feature("Feature A", "2027-03-01T00:00:00Z", "2027-03-10T00:00:00Z"), manufacturer_planner_headers),
        201,
    )
    assert_promotional_event(event_a)
    event_b = validate_success(
        api.create_event(plan_id, _feature("Feature B", "2027-03-10T00:00:00Z", "2027-03-20T00:00:00Z"), manufacturer_planner_headers),
        201,
    )
    assert event_b["status"] == "PENCILED", "adjacency end == start is allowed"

    validate_error(
        api.create_event(plan_id, _feature("Feature C", "2027-03-09T00:00:00Z", "2027-03-12T00:00:00Z"), manufacturer_planner_headers),
        ApiErrorId.ERR_PROMO_OVERLAP,
    )

    features = validate_success(
        api.list_events(plan_id, manufacturer_planner_headers, params={"event_type": "FEATURE"}), 200
    )
    assert sorted(e["name"] for e in features) == ["Feature A", "Feature B"], (
        f"the intersecting event must not persist, got {[e['name'] for e in features]}"
    )


def test_overlap_rule_is_scoped_per_event_type(api, manufacturer_planner_headers):
    """PRD §3.2: "Events of different types, and events already `CANCELLED`, never block the calendar."
    PRD §3.2: "An event occupies the half-open interval from its `start_date` up to but not including its `end_date`, and the calendar forbids collisions: within one plan and one `event_type`, a new event whose interval intersects an existing `PENCILED` or `LOCKED` event is rejected with `ERR_PROMO_OVERLAP` (HTTP 409), while pure adjacency — one event's `end_date` equal to another's `start_date` — is expressly allowed."

    A DISPLAY event fully inside the FEATURE event's dates is created: the
    overlap rule scopes to one (plan, event_type) pair.

    Design: Difficulty/resource_temporal_overlap/promo_overlap_half_open_adjacency
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]

    validate_success(
        api.create_event(plan_id, _feature("Feature A", "2027-03-01T00:00:00Z", "2027-03-10T00:00:00Z"), manufacturer_planner_headers),
        201,
    )
    display = validate_success(
        api.create_event(
            plan_id,
            {
                "name": "Display D",
                "event_type": "DISPLAY",
                "start_date": "2027-03-05T00:00:00Z",
                "end_date": "2027-03-08T00:00:00Z",
                "discount_depth_pct": 15,
            },
            manufacturer_planner_headers,
        ),
        201,
    )
    assert_promotional_event(display)
    assert display["status"] == "PENCILED"

    events = validate_success(api.list_events(plan_id, manufacturer_planner_headers), 200)
    assert len(events) == 2


def _launch_payload(product_name, pack_family, launch_date):
    return {
        "product_name": product_name,
        "pack_family": pack_family,
        "launch_date": launch_date,
        "total_trade_budget_cents": 500000,
    }


def test_launch_inside_min_gap_rejected(api, manufacturer_planner_headers):
    """PRD §3.5: "And the calendar must breathe: the new `launch_date` must sit at least 84 days away from the `launch_date` of every other launch of the same plan that is still `PLANNING` or already `LAUNCHED`, with a separation of exactly 84 days passing; a closer date fails with `ERR_LAUNCH_TOO_CLOSE` (HTTP 422)."

    A second launch 80 days after the existing 2027-03-01 launch is one day
    too few and is rejected; only the first launch persists.

    Design: Difficulty/resource_temporal_overlap/launch_min_gap_buffer_semantics
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]

    validate_success(
        api.create_launch(plan_id, _launch_payload("UltraTabs", "tabs", "2027-03-01T00:00:00Z"), manufacturer_planner_headers),
        201,
    )
    validate_error(
        api.create_launch(plan_id, _launch_payload("MegaPods", "pods", "2027-05-20T00:00:00Z"), manufacturer_planner_headers),
        ApiErrorId.ERR_LAUNCH_TOO_CLOSE,
    )

    launches = validate_success(api.list_launches(plan_id, manufacturer_planner_headers), 200)
    assert len(launches) == 1, f"the too-close launch must not persist, got {len(launches)}"


def test_launch_at_exactly_min_gap_passes(api, manufacturer_planner_headers):
    """PRD §3.5: "And the calendar must breathe: the new `launch_date` must sit at least 84 days away from the `launch_date` of every other launch of the same plan that is still `PLANNING` or already `LAUNCHED`, with a separation of exactly 84 days passing; a closer date fails with `ERR_LAUNCH_TOO_CLOSE` (HTTP 422)."

    2027-05-24 is exactly 84 days after 2027-03-01, and the `at least` rule
    passes at the boundary: the launch is created and born PLANNING.

    Design: Difficulty/resource_temporal_overlap/launch_min_gap_buffer_semantics
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]

    validate_success(
        api.create_launch(plan_id, _launch_payload("UltraTabs", "tabs", "2027-03-01T00:00:00Z"), manufacturer_planner_headers),
        201,
    )
    second = validate_success(
        api.create_launch(plan_id, _launch_payload("MegaPods", "pods", "2027-05-24T00:00:00Z"), manufacturer_planner_headers),
        201,
    )
    assert_innovation_launch(second)
    assert second["status"] == "PLANNING"

    launches = validate_success(api.list_launches(plan_id, manufacturer_planner_headers), 200)
    assert len(launches) == 2
