"""Property window counters conservation and immediate consistency (PRD §3.2, §3.3)."""
from test_helpers import (
    RM,
    create_active_property,
    create_window,
    get_success_data,
    validate_success,
)


def test_property_window_counters_conserved_across_schedule_cancel_cycle(api):
    """PRD §3.2: "A successfully created window starts in `SCHEDULED`,
    increments the property's `version`, and is reflected in the appropriate
    consumed counter."
    PRD §3.3: "Cancellation ... decrements the property's
    `simulcast_windows_consumed` or `exclusive_windows_consumed` counter
    according to the window's `rights_mode` ...".

    Schedule (0 -> 1) then cancel (1 -> 0); the quota field never changes.

    Design: Difficulty/compensating_invariant/property_window_counters_conserved_across_schedule_cancel_cycle
    """
    prop = create_active_property(simulcast_windows_count=5, exclusive_windows_count=5)
    before = get_success_data(api.get_property(prop["id"], RM))
    assert before["simulcast_windows_consumed"] == 0
    window = create_window(
        prop["id"],
        rights_mode="SIMULCAST",
        scheduled_start="2026-09-21T18:00:00Z",
        scheduled_end="2026-09-21T21:00:00Z",
    )
    mid = get_success_data(api.get_property(prop["id"], RM))
    assert mid["simulcast_windows_consumed"] == 1
    validate_success(api.cancel_window(window["id"], RM))
    after = get_success_data(api.get_property(prop["id"], RM))
    assert after["simulcast_windows_consumed"] == 0, (
        f"schedule+cancel must restore the counter, got {after['simulcast_windows_consumed']}"
    )
    assert after["simulcast_windows_count"] == 5


def test_property_window_counters_per_rights_mode(api):
    """PRD §3.3: "Cancellation ... decrements the property's
    `simulcast_windows_consumed` or `exclusive_windows_consumed` counter
    according to the window's `rights_mode` ...".

    Scheduling one SIMULCAST and one EXCLUSIVE window moves each counter
    independently; cancelling the EXCLUSIVE window restores only its own
    counter.

    Design: Difficulty/compensating_invariant/property_window_counters_conserved_across_schedule_cancel_cycle
    """
    prop = create_active_property(simulcast_windows_count=5, exclusive_windows_count=5)
    sim = create_window(prop["id"], rights_mode="SIMULCAST",
                        scheduled_start="2026-09-21T18:00:00Z",
                        scheduled_end="2026-09-21T21:00:00Z")
    exc = create_window(prop["id"], rights_mode="EXCLUSIVE",
                        scheduled_start="2026-09-22T18:00:00Z",
                        scheduled_end="2026-09-22T21:00:00Z")
    mid = get_success_data(api.get_property(prop["id"], RM))
    assert mid["simulcast_windows_consumed"] == 1
    assert mid["exclusive_windows_consumed"] == 1
    validate_success(api.cancel_window(exc["id"], RM))
    after = get_success_data(api.get_property(prop["id"], RM))
    assert after["exclusive_windows_consumed"] == 0
    assert after["simulcast_windows_consumed"] == 1


def test_cancel_immediately_visible_on_read(api):
    """PRD §1: "All state transitions are immediate (no async jobs), and
    several cascades are synchronous — for example, suspending a property
    immediately cancels every still-scheduled window under it, and that
    cancellation immediately cancels the ad slots attached to those
    windows."

    After POST cancel returns, a GET on the same window shows CANCELLED.

    Design: Corner/consistency_model/cancel_immediately_visible_on_read
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-10-09T18:00:00Z",
        scheduled_end="2026-10-09T21:00:00Z",
    )
    cancelled = validate_success(api.cancel_window(window["id"], RM))
    assert cancelled["status"] == "CANCELLED"
    fetched = validate_success(api.get_window(window["id"], RM))
    assert fetched["status"] == "CANCELLED"
