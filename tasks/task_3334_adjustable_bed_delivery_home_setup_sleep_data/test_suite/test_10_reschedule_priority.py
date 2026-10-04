"""Reschedule priority: the visit-completed state guard beats the temporal
window-in-past check when both would fail."""
from test_helpers import (
    ApiErrorId,
    create_delivery_window,
    set_clock,
    setup_delivered_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, SALES


def _setup_verified_visit_with_past_and_future_windows(api):
    """Delivered order (visit VERIFIED) plus a second window whose start the
    clock later passes. Returns (visit, past_window, future_window)."""
    ctx = setup_delivered_order(email="v@x.com", serial_number="SN-V1",
                                window_start="2026-09-04T08:00:00Z",
                                window_end="2026-09-04T12:00:00Z")
    past_window = create_delivery_window(
        ctx["store"]["id"], team_id="T2",
        window_start="2026-09-02T08:00:00Z", window_end="2026-09-02T12:00:00Z")
    future_window = create_delivery_window(
        ctx["store"]["id"], team_id="T2",
        window_start="2026-09-05T08:00:00Z", window_end="2026-09-05T12:00:00Z")
    # Advance the clock past the second window's start without touching the
    # delivered order's trial-close horizon (101 days out).
    set_clock("2026-09-03T00:00:00Z")
    return ctx, past_window, future_window


def test_reschedule_verified_visit_to_past_window_state_beats_temporal(api):
    """PRD §2.7: "the visit-completed guard as `ERR_VISIT_ALREADY_COMPLETED`"
    is reported before "business temporal rules such as window-in-past". PRD
    §3.5: "attempting to reschedule a `VERIFIED` or `CANCELLED` visit is
    rejected with `ERR_VISIT_ALREADY_COMPLETED`."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_verified_visit_to_past_window_state_beats_temporal
    """
    ctx, past_window, _ = _setup_verified_visit_with_past_and_future_windows(api)
    visit = validate_success(api.get_delivery_visit(ctx["visit"]["id"], ADMIN))
    assert visit["status"] == "VERIFIED"

    resp = api.reschedule_visit(visit["id"], {
        "expected_visit_version": visit["version"],
        "new_delivery_window_id": past_window["id"]}, SALES)
    validate_error(resp, ApiErrorId.ERR_VISIT_ALREADY_COMPLETED)
    err = resp.json()["data"]
    assert err["error_id"] != "ERR_WINDOW_IN_PAST", (
        "the state guard (visit-completed) is reported before the temporal "
        "window-in-past check")


def test_reschedule_verified_visit_to_future_window_also_state_error(api):
    """PRD §3.5: "attempting to reschedule a `VERIFIED` or `CANCELLED` visit
    is rejected with `ERR_VISIT_ALREADY_COMPLETED`."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_verified_visit_to_past_window_state_beats_temporal
    """
    ctx, _, future_window = \
        _setup_verified_visit_with_past_and_future_windows(api)
    visit = validate_success(api.get_delivery_visit(ctx["visit"]["id"], ADMIN))
    assert visit["status"] == "VERIFIED"

    resp = api.reschedule_visit(visit["id"], {
        "expected_visit_version": visit["version"],
        "new_delivery_window_id": future_window["id"]}, SALES)
    validate_error(resp, ApiErrorId.ERR_VISIT_ALREADY_COMPLETED)
    after = validate_success(api.get_delivery_visit(visit["id"], ADMIN))
    assert after["status"] == "VERIFIED"
    assert after["delivery_window_id"] == ctx["window"]["id"], (
        "the rejected reschedule leaves the visit on its original window")
