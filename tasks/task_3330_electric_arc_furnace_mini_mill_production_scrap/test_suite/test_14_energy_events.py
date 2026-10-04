"""Energy events: adjacency gap boundary, strict activate, clock lapse/expiry,
window honor gate (PRD §3.10, §2.5)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    set_clock, make_mill, make_event, activate_event, release_event, make_window,
    get_event, get_window, get_mill,
)

PM = TEST_USERS["plant_manager_headers"]
ED = TEST_USERS["energy_dispatcher_headers"]


def test_energy_event_adjacency_gap_below_floor_rejected():
    """PRD §3.10: "there must be at least 15 minutes between the previous event's
    `released_at` and this event's `called_at` — energy events forbid adjacency, in
    deliberate contrast to campaigns, which allow touching windows. Either violation
    fails with `ERR_EVENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/energy_event_adjacency_gap
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    ev1 = make_event(mill["id"], called_at="2026-09-09T12:00:00Z",
                     released_at="2026-09-09T14:00:00Z")
    activate_event(mill["id"], ev1["id"])
    release_event(mill["id"], ev1["id"])
    ev2 = make_event(mill["id"], called_at="2026-09-09T14:10:00Z",
                     released_at="2026-09-09T15:00:00Z")

    resp = api_client.activate_event(mill["id"], ev2["id"], ED)
    validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP, 409)
    assert get_event(mill["id"], ev2["id"])["status"] == "DECLARED"


def test_energy_event_adjacency_gap_exactly_fifteen_minutes_allowed():
    """PRD §3.10: "there must be at least 15 minutes between the previous event's
    `released_at` and this event's `called_at`"
    PRD §3.10: "On activation the event becomes `ACTIVE`, the mill's posture
    recomputes to `INTERRUPTED`"

    Design: Difficulty/resource_temporal_overlap/energy_event_adjacency_gap
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    ev1 = make_event(mill["id"], called_at="2026-09-09T12:00:00Z",
                     released_at="2026-09-09T14:00:00Z")
    activate_event(mill["id"], ev1["id"])
    release_event(mill["id"], ev1["id"])
    ev3 = make_event(mill["id"], called_at="2026-09-09T14:15:00Z",
                     released_at="2026-09-09T15:30:00Z")

    activated = validate_success(api_client.activate_event(mill["id"], ev3["id"], ED), 200)
    assert activated["status"] == "ACTIVE"
    assert get_mill(mill["id"])["posture"] == "INTERRUPTED"


def test_energy_event_second_activate_rejected():
    """PRD §2.7: "(5) source-state validity yields `ERR_INVALID_STATE`"
    PRD §3.10: "Activating a declared event is where the mill's world changes."

    Design: Corner/state_machines/energy_event_second_activate_rejected_idempotency
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    ev = make_event(mill["id"], called_at="2026-09-09T12:00:00Z",
                    released_at="2026-09-09T14:00:00Z")
    activated = validate_success(api_client.activate_event(mill["id"], ev["id"], ED), 200)
    assert activated["version"] == 2  # declare = 1, first activate = 2

    resp = api_client.activate_event(mill["id"], ev["id"], ED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = get_event(mill["id"], ev["id"])
    assert after["status"] == "ACTIVE"
    assert after["version"] == 2  # the rejected activate did not bump


def test_clock_set_lapses_windows_and_expires_events():
    """PRD §2.5: "interruptible windows lapse when `end_at` passes without a linked
    event, declared energy events expire when `released_at` passes without
    activation"

    Design: Corner/endpoints/clock_set_lapses_windows_and_expires_events
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    window = make_window(mill["id"], label="PJM-ECON",
                         start_at="2026-09-10T12:00:00Z",
                         end_at="2026-09-10T14:00:00Z", curtailment_credit_cents=50000)
    event = make_event(mill["id"], called_at="2026-09-10T12:00:00Z",
                       released_at="2026-09-10T14:00:00Z")

    set_clock("2026-09-11T00:00:00Z")
    assert get_window(mill["id"], window["id"])["status"] == "LAPSED"
    assert get_event(mill["id"], event["id"])["status"] == "EXPIRED"
    assert get_mill(mill["id"])["posture"] == "NORMAL"


def test_window_honor_without_released_event_returns_invalid_state():
    """PRD §3.10: "Honoring a window — allowed while `SCHEDULED`, and only when its
    `linked_event_id` is set and that event has actually been `RELEASED`, proving
    the mill rode out an interruption inside the window"
    PRD §2.7: "(5) source-state validity yields `ERR_INVALID_STATE`"

    Design: Corner/errors/window_honor_without_released_event_returns_invalid_state
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    window = make_window(mill["id"], label="PJM-ECON",
                         start_at="2026-09-10T12:00:00Z",
                         end_at="2026-09-10T14:00:00Z", curtailment_credit_cents=50000)
    event = make_event(mill["id"], called_at="2026-09-10T12:30:00Z",
                       released_at="2026-09-10T13:30:00Z")
    activate_event(mill["id"], event["id"])

    linked = get_window(mill["id"], window["id"])
    assert linked["linked_event_id"] == event["id"]
    assert linked["status"] == "SCHEDULED"

    resp = api_client.honor_window(mill["id"], window["id"], ED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = get_window(mill["id"], window["id"])
    assert after["status"] == "SCHEDULED"
    assert after["linked_event_id"] == event["id"]
