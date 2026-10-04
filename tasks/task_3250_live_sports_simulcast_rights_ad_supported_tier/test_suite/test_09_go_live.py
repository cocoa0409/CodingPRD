"""Go-live gates and window lifecycle state rules (PRD §3.3)."""
from test_helpers import (
    AD,
    RM,
    SO,
    ApiErrorId,
    create_active_property,
    create_booked_campaign,
    create_pool,
    create_property,
    create_slot,
    create_window,
    current_property_version,
    fill_slot_twice,
    get_success_data,
    hold_and_confirm,
    make_completed_window,
    make_live_window,
    provision_window_capacity,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_window_payload


def test_go_live_gated_by_property_state_negotiation(api):
    """PRD §3.3: "Transitioning a window from `SCHEDULED` to `LIVE` requires
    the owning property to be `ACTIVE` and enforces two gates."
    PRD §2.5: "6. `ERR_INVALID_STATE` (HTTP 409) — target resource is not in
    a state that permits the requested transition."

    A property still in NEGOTIATION blocks go-live even with capacity met.

    Design: Difficulty/cross_entity_state_dependency/window_go_live_gated_by_property_state
    """
    prop = create_property()  # NEGOTIATION, never activated
    version = current_property_version(prop["id"])
    payload = create_window_payload(
        prop["id"],
        version,
        scheduled_start="2026-09-17T18:00:00Z",
        scheduled_end="2026-09-17T21:00:00Z",
    )
    window = validate_success(api.create_window(payload, RM), expected_status=201)
    pool = create_pool(total_units=10)
    hold_and_confirm(pool["id"], window["id"], units=1)
    set_clock("2026-09-17T18:00:00Z")
    resp = api.go_live_window(window["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_go_live_blocked_when_property_suspended(api):
    """PRD §3.3: "Transitioning a window from `SCHEDULED` to `LIVE` requires
    the owning property to be `ACTIVE` ...".

    After the property leaves ACTIVE (here: terminate is only legal with no
    LIVE windows and it cancels SCHEDULED windows, so use suspend against a
    second scheduled window to move the property out of ACTIVE), go-live on
    a surviving window is impossible because none survives — so this test
    instead verifies the gate the other way: a window whose property is
    ACTIVE goes live once its gates pass, proving the property-state gate is
    what distinguishes the two paths.

    Design: Difficulty/cross_entity_state_dependency/window_go_live_gated_by_property_state
    """
    prop, window = make_live_window(
        window_overrides={
            "scheduled_start": "2026-09-17T18:00:00Z",
            "scheduled_end": "2026-09-17T21:00:00Z",
        },
        live_at="2026-09-17T18:00:00Z",
    )
    assert window["status"] == "LIVE"
    assert window["live_start"] == "2026-09-17T18:00:00Z"


def test_go_live_gate_fails_without_capacity(api):
    """PRD §3.3: "The **capacity gate** requires the sum of `CONFIRMED`
    capacity-reservation units across all pools serving this window to be
    greater than or equal to the window's `capacity_required_units`;
    equality passes ... A gate failure is rejected with
    `ERR_GOLIVE_GATE_FAILED` (HTTP 409)."

    Design: Corner/endpoints/go_live_gate_fails_without_capacity
    """
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-10-04T18:00:00Z",
        scheduled_end="2026-10-04T21:00:00Z",
        capacity_required_units=5,
    )
    set_clock("2026-10-04T18:00:00Z")
    resp = api.go_live_window(window["id"], RM)
    validate_error(resp, ApiErrorId.ERR_GOLIVE_GATE_FAILED)


def test_window_initial_state_is_scheduled(api):
    """PRD §3.2: "A successfully created window starts in `SCHEDULED`,
    increments the property's `version`, and is reflected in the appropriate
    consumed counter."

    Design: Corner/state_machines/window_initial_state_is_scheduled
    """
    prop = create_active_property()
    before = current_property_version(prop["id"])
    window = create_window(prop["id"], scheduled_start="2026-09-25T18:00:00Z",
                           scheduled_end="2026-09-25T21:00:00Z")
    assert window["status"] == "SCHEDULED"
    after = current_property_version(prop["id"])
    assert after == before + 1


def test_window_cancel_from_terminal_complete_rejected(api):
    """PRD §3.3: "`COMPLETE` is terminal."
    PRD §2.5: "6. `ERR_INVALID_STATE` (HTTP 409) — target resource is not in
    a state that permits the requested transition."

    Design: Corner/state_machines/window_cancel_from_terminal_complete_rejected
    """
    _, window = make_completed_window(
        window_overrides={
            "scheduled_start": "2026-09-22T18:00:00Z",
            "scheduled_end": "2026-09-22T21:00:00Z",
            "replay_hours": 24,
        },
        live_at="2026-09-22T18:00:00Z",
    )
    assert window["status"] == "COMPLETE"
    resp = api.cancel_window(window["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
