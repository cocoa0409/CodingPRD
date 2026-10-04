"""The weekly equipment-hours budget: conservation through lock and release."""

from test_helpers import fixtures


def test_lock_consumes_and_release_restores_equipment_hours(api):
    """A 10-hour lock drops the unit's weekly availability to 30.00; release restores 40.00.

    The window runs 06:00-16:00 on Monday 2026-09-07, consuming 10.00 hours of
    unit EQ-9's ISO-week allowance.

    PRD: "Locking a window is permitted only if the sum of `window_hours` over that unit's already-locked windows in the same week plus the new window's `window_hours` does not exceed 40.00 — a total of exactly 40.00 hours is allowed"
    PRD: "Each window exposes `equipment_week_hours_available`, the unit's remaining allowance for that week, computed as 40.00 hours minus the hours consumed by the unit's locked windows in the window's ISO week. Releasing a locked window restores exactly its `window_hours` to the allowance and recomputes this field."
    Design: Difficulty/compensating_invariant/equipment_week_hours_conserved_through_lock_release
    """
    net = fixtures.setup_network(api)
    window = fixtures.create_window(
        api,
        net,
        track_segment_id=net["seg1"]["id"],
        window_start_at="2026-09-07T06:00:00Z",
        window_end_at="2026-09-07T16:00:00Z",
        equipment_unit_id="EQ-9",
        clearance_buffer_minutes=15,
    )
    assert window["equipment_week_hours_available"] == 40.00

    locked = fixtures.lock_window(api, net, window["id"])
    assert locked["status"] == "LOCKED"
    assert locked["equipment_week_hours_available"] == 30.00

    released = fixtures.release_window(api, net, window["id"])
    assert released["status"] == "RELEASED"
    assert released["equipment_week_hours_available"] == 40.00


def test_lock_release_pair_leaves_the_weekly_allowance_undrifted(api):
    """The lock/release pair conserves the unit's weekly allowance exactly at 40.00.

    PRD: "Releasing a locked window restores exactly its `window_hours` to the allowance and recomputes this field."
    Design: Difficulty/compensating_invariant/equipment_week_hours_conserved_through_lock_release
    """
    net = fixtures.setup_network(api)
    window = fixtures.create_window(
        api,
        net,
        track_segment_id=net["seg1"]["id"],
        window_start_at="2026-09-07T06:00:00Z",
        window_end_at="2026-09-07T16:00:00Z",
        equipment_unit_id="EQ-9",
        clearance_buffer_minutes=15,
    )
    assert window["window_hours"] == 10.00

    fixtures.lock_window(api, net, window["id"])
    released = fixtures.release_window(api, net, window["id"])

    assert released["status"] == "RELEASED"
    assert released["equipment_week_hours_available"] == 40.00
    assert fixtures.read_window(api, window["id"])["equipment_week_hours_available"] == 40.00
