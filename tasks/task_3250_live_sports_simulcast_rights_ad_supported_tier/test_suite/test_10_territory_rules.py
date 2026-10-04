"""Territory rules: interval validity, overlap, adjacency, lift (PRD §3.11)."""
from test_helpers import (
    RM,
    ApiErrorId,
    create_active_property,
    create_territory_rule_payload,
    create_window,
    make_live_window,
    validate_error,
    validate_success,
)


def _scheduled_window(api, scheduled_start="2026-09-18T09:00:00Z",
                      scheduled_end="2026-09-18T20:00:00Z", regional_block=True):
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        regional_block=regional_block,
    )
    return prop, window


def test_blackout_adjacent_intervals_allowed_overlap_rejected(api):
    """PRD §3.11: "a new `BLACKOUT` rule for a `(window, region)` pair is
    rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409) when its half-open
    effective interval intersects the half-open effective interval of any
    existing `ACTIVE` `BLACKOUT` rule for the same pair — intersection means
    the new rule's `effective_start` is strictly before the existing rule's
    `effective_end` and the existing rule's `effective_start` is strictly
    before the new rule's `effective_end`. Adjacent intervals — where the
    new rule's `effective_start` equals the existing rule's `effective_end`
    — do **not** overlap and are permitted; two adjacent rules must not be
    merged, because each mirrors a distinct broadcast obligation."

    Design: Difficulty/resource_temporal_overlap/blackout_half_open_adjacency_allowed
    """
    _, window = _scheduled_window(api)
    r1 = create_territory_rule_payload(
        window["id"], effective_start="2026-09-18T10:00:00Z",
        effective_end="2026-09-18T12:00:00Z", broadcast_obligation_ref="BC-1",
    )
    rule1 = validate_success(api.create_territory_rule(r1, RM), expected_status=201)
    # Adjacent: start == r1.end -> permitted, no merge.
    r2 = create_territory_rule_payload(
        window["id"], effective_start="2026-09-18T12:00:00Z",
        effective_end="2026-09-18T14:00:00Z", broadcast_obligation_ref="BC-2",
    )
    rule2 = validate_success(api.create_territory_rule(r2, RM), expected_status=201)
    assert rule1["id"] != rule2["id"]
    assert rule1["rule_status"] == "ACTIVE" and rule2["rule_status"] == "ACTIVE"
    # Overlapping [11:00, 13:00) intersects [10:00, 12:00) -> rejected.
    r3 = create_territory_rule_payload(
        window["id"], effective_start="2026-09-18T11:00:00Z",
        effective_end="2026-09-18T13:00:00Z", broadcast_obligation_ref="BC-3",
    )
    resp = api.create_territory_rule(r3, RM)
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_OVERLAP)


def test_blackout_overlap_same_region_only(api):
    """PRD §3.11: "a new `BLACKOUT` rule for a `(window, region)` pair is
    rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409) when its half-open
    effective interval intersects the half-open effective interval of any
    existing `ACTIVE` `BLACKOUT` rule for the same pair".

    Overlap is judged per (window, region): an overlapping interval on a
    different region is permitted, while the same-region overlap is not.

    Design: Difficulty/resource_temporal_overlap/blackout_half_open_adjacency_allowed
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-09-18T09:00:00Z",
        scheduled_end="2026-09-18T20:00:00Z",
        territory_scope=["510", "620"],
        regional_block=True,
    )
    r1 = create_territory_rule_payload(
        window["id"], region_code="510",
        effective_start="2026-09-18T10:00:00Z",
        effective_end="2026-09-18T12:00:00Z", broadcast_obligation_ref="BC-A",
    )
    validate_success(api.create_territory_rule(r1, RM), expected_status=201)
    # Same interval, different region -> allowed.
    r2 = create_territory_rule_payload(
        window["id"], region_code="620",
        effective_start="2026-09-18T10:00:00Z",
        effective_end="2026-09-18T12:00:00Z", broadcast_obligation_ref="BC-B",
    )
    validate_success(api.create_territory_rule(r2, RM), expected_status=201)
    # Same region, partial overlap -> rejected.
    r3 = create_territory_rule_payload(
        window["id"], region_code="510",
        effective_start="2026-09-18T11:00:00Z",
        effective_end="2026-09-18T13:00:00Z", broadcast_obligation_ref="BC-C",
    )
    resp = api.create_territory_rule(r3, RM)
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_OVERLAP)


def test_rule_window_invalid_when_end_before_start(api):
    """PRD §3.11: "First, the interval itself: `effective_start` must be
    strictly before `effective_end`, and `effective_start` must be greater
    than or equal to the window's `scheduled_start` minus 24 hours; a
    violation surfaces `ERR_RULE_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/rule_window_invalid_when_end_before_start
    """
    _, window = _scheduled_window(
        api, scheduled_start="2026-10-10T18:00:00Z", scheduled_end="2026-10-10T21:00:00Z",
        regional_block=False,
    )
    payload = create_territory_rule_payload(
        window["id"],
        effective_start="2026-10-10T12:00:00Z",
        effective_end="2026-10-10T11:00:00Z",
    )
    resp = api.create_territory_rule(payload, RM)
    validate_error(resp, ApiErrorId.ERR_RULE_WINDOW_INVALID)


def test_territory_rule_lift_on_live_window_rejected(api):
    """PRD §3.11: "Lifting a rule transitions it from `ACTIVE` to `LIFTED`
    and is permitted only while the window is still `SCHEDULED` — a blackout
    cannot be lifted once the window is live, because broadcast obligations
    lock at go-live."

    Design: Corner/state_machines/territory_rule_lift_on_live_window_rejected
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-09-23T18:00:00Z",
        scheduled_end="2026-09-23T21:00:00Z",
        territory_scope=["510", "620"],
        regional_block=True,
    )
    rule = validate_success(
        api.create_territory_rule(
            create_territory_rule_payload(
                window["id"], region_code="620",
                effective_start="2026-09-23T17:00:00Z",
                effective_end="2026-09-23T20:00:00Z",
            ),
            RM,
        ),
        expected_status=201,
    )
    from test_helpers import create_pool, hold_and_confirm, set_clock
    pool = create_pool(total_units=10)
    hold_and_confirm(pool["id"], window["id"], units=1)
    set_clock("2026-09-23T18:00:00Z")
    validate_success(api.go_live_window(window["id"], RM))
    resp = api.lift_territory_rule(rule["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
