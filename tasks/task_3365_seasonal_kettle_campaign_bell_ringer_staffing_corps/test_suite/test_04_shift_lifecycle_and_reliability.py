"""Shift lifecycle: no-shows, suspension cascades and the cyclic rebook edges."""
import pytest

from test_helpers import (
    cancel_shift,
    create_shift_ok,
    get_ringer,
    get_shift,
    no_show_shift,
    rebook_shift,
    set_clock,
    setup_ringing_scenario,
)


def test_no_show_marks_shift_and_recomputes_reliability(api):
    """PRD §3.3: "the shift becomes `NO_SHOW`, the ringer's `scheduled_hours` is
    reduced by the shift's duration in hours, and the ringer's
    `reliability_score` is recomputed with the fifteen-point no-show penalty
    included."

    Design: Difficulty/non_linear_state_machine/shift_cycle_no_show_back_to_scheduled
    """
    network = setup_ringing_scenario()
    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-18T09:00:00Z", "2026-11-18T17:00:00Z")
    set_clock("2026-11-20T00:00:00Z")

    marked = no_show_shift(shift["id"])
    assert marked["status"] == "NO_SHOW"

    ringer = get_ringer(network.ringer["id"])
    assert ringer["reliability_score"] == 85, "100 plus one no-show penalty of -15"
    assert ringer["engagement_status"] == "ACTIVE", "85 is still at or above the threshold"


def test_no_show_shift_can_be_rebooked_to_scheduled(api):
    """PRD §3.3: "Rebooking a `NO_SHOW` shift requires the new window and an
    `ACTIVE` engagement, but not the screening and location re-checks."
    PRD §3.3: "Either rebooking increases the ringer's `scheduled_hours` by the
    shift's duration in hours."

    Design: Difficulty/non_linear_state_machine/shift_cycle_no_show_back_to_scheduled
    """
    network = setup_ringing_scenario()
    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-18T09:00:00Z", "2026-11-18T17:00:00Z")
    set_clock("2026-11-20T00:00:00Z")
    no_show_shift(shift["id"])

    rebooked = rebook_shift(shift["id"], "2026-11-25T09:00:00Z", "2026-11-25T17:00:00Z")
    assert rebooked["id"] == shift["id"], "the same Shift row returns to SCHEDULED"
    assert rebooked["status"] == "SCHEDULED"
    assert get_ringer(network.ringer["id"])["scheduled_hours"] == pytest.approx(8.0, abs=0.001)


def test_three_no_shows_suspend_the_ringer(api):
    """PRD §3.3: "The score starts from a base of 100 and adds one point for
    every shift the ringer has completed, subtracts five points for every late
    cancellation, and subtracts fifteen points for every no-show".
    PRD §3.3: "When a no-show recomputation leaves the ringer's
    `reliability_score` below 60, the engagement transitions from `ACTIVE` to
    `SUSPENDED` as a system consequence".

    Design: Difficulty/transitive_cascade/no_show_cascade_suspends_ringer_and_cancels_future_shifts
    """
    network = setup_ringing_scenario(screening_completed_at="2026-10-25T00:00:00Z")
    shifts = [
        create_shift_ok(network.location["id"], network.ringer["id"],
                        f"2026-11-{day}T09:00:00Z", f"2026-11-{day}T17:00:00Z")
        for day in ("10", "11", "12", "30")
    ]
    set_clock("2026-11-20T00:00:00Z")

    for shift in shifts[:3]:
        no_show_shift(shift["id"])

    assert get_shift(shifts[2]["id"])["status"] == "NO_SHOW"
    ringer = get_ringer(network.ringer["id"])
    assert ringer["reliability_score"] == 55, "100 plus three no-show penalties of -15"
    assert ringer["engagement_status"] == "SUSPENDED"


def test_suspension_cancels_the_ringers_future_scheduled_shift(api):
    """PRD §3.3: "every one of that ringer's shifts still in `SCHEDULED` status
    and starting after the current logical clock instant is cancelled, and for
    each cancelled shift the affected kettle location's `covered_minutes` is
    recomputed".

    Design: Difficulty/transitive_cascade/no_show_cascade_suspends_ringer_and_cancels_future_shifts
    """
    network = setup_ringing_scenario(screening_completed_at="2026-10-25T00:00:00Z")
    shifts = [
        create_shift_ok(network.location["id"], network.ringer["id"],
                        f"2026-11-{day}T09:00:00Z", f"2026-11-{day}T17:00:00Z")
        for day in ("10", "11", "12", "30")
    ]
    set_clock("2026-11-20T00:00:00Z")

    for shift in shifts[:3]:
        no_show_shift(shift["id"])

    # The 2026-11-30 shift starts after the logical clock instant, so the
    # suspension cascade — not the no-show call itself — cancels it.
    assert get_shift(shifts[3]["id"])["status"] == "CANCELLED"
    assert get_shift(shifts[0]["id"])["status"] == "NO_SHOW"
    assert get_shift(shifts[1]["id"])["status"] == "NO_SHOW"


def test_shift_cancel_reduces_scheduled_hours(api):
    """PRD §3.3: "cancellation reduces the ringer's `scheduled_hours` by the
    shift's duration in hours."
    PRD §3.3: "cancelling a shift that was still only `SCHEDULED` leaves the
    ringer's reliability untouched".

    Design: Difficulty/compensating_invariant/shift_cancel_then_rebook_conserves_scheduled_hours
    """
    network = setup_ringing_scenario()
    shift_a = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z")
    create_shift_ok(network.location["id"], network.ringer["id"],
                    "2026-11-18T09:00:00Z", "2026-11-18T17:00:00Z")
    assert get_ringer(network.ringer["id"])["scheduled_hours"] == pytest.approx(16.0, abs=0.001)

    cancelled = cancel_shift(shift_a["id"], reason="weather closure")
    assert cancelled["status"] == "CANCELLED"
    assert get_ringer(network.ringer["id"])["scheduled_hours"] == pytest.approx(8.0, abs=0.001)


def test_shift_rebook_restores_scheduled_hours(api):
    """PRD §3.3: "Rebooking a `CANCELLED` shift returns it to `SCHEDULED` with a
    new `starts_at` and `ends_at`".
    PRD §3.3: "Either rebooking increases the ringer's `scheduled_hours` by the
    shift's duration in hours."

    Design: Difficulty/compensating_invariant/shift_cancel_then_rebook_conserves_scheduled_hours
    """
    network = setup_ringing_scenario()
    shift_a = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z")
    create_shift_ok(network.location["id"], network.ringer["id"],
                    "2026-11-18T09:00:00Z", "2026-11-18T17:00:00Z")
    hours_before_cancel = get_ringer(network.ringer["id"])["scheduled_hours"]
    cancel_shift(shift_a["id"], reason="weather closure")

    rebooked = rebook_shift(shift_a["id"], "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z")
    assert rebooked["status"] == "SCHEDULED"
    hours_after_rebook = get_ringer(network.ringer["id"])["scheduled_hours"]
    assert hours_after_rebook == pytest.approx(16.0, abs=0.001)
    assert hours_after_rebook - hours_before_cancel == pytest.approx(0.0, abs=0.001)
