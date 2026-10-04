"""Difficulty rule: priority_pair_validation_conflict — the union-crew
safety minimum beats the elevator-conflict temporal rule at window creation
(PRD §3.7)."""

from test_helpers import (
    ApiErrorId,
    create_window,
    make_dealer_headers,
    make_install_window_payload,
    setup_scheduled_phase,
    validate_error,
)


def test_safety_error_beats_temporal_error_on_window(api):
    """PRD §3.7: "Three rules guard creation, evaluated after body-shape and
    date-window checks in this order: the union minimum, the elevator
    conflict rule, and the zone crew aggregate." and "when `union_required`
    is true, `crew_size` must be at least 4, else the booking is rejected
    with `ERR_UNION_CREW_MINIMUM`." A union window with crew 3 that also
    overlaps a RESERVED elevator window fails the safety rule first.

    Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_window
    """
    ctx = setup_scheduled_phase(api)
    dealer_h = make_dealer_headers(ctx["dealer"]["id"])
    create_window(api, ctx["phase"]["id"], ctx["dealer"]["id"])

    resp = api.create_install_window(
        make_install_window_payload(
            ctx["phase"]["id"],
            start_at="2026-12-01T10:00:00Z",
            end_at="2026-12-01T13:00:00Z",
            union_required=True,
            elevator_required=True,
            crew_size=3,
        ),
        dealer_h,
    )
    validate_error(resp, ApiErrorId.ERR_UNION_CREW_MINIMUM)


def test_elevator_conflict_fires_once_union_minimum_met(api):
    """Control leg of the same design instance: the same overlapping window
    with a union-legal crew of 4 passes the safety rule and is then rejected
    by the elevator conflict rule — "The rejection is `ERR_WINDOW_CONFLICT`
    (HTTP 409)" (PRD §3.7) — proving the overlap was genuinely present in the
    priority scenario.

    Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_window
    """
    ctx = setup_scheduled_phase(api)
    dealer_h = make_dealer_headers(ctx["dealer"]["id"])
    create_window(api, ctx["phase"]["id"], ctx["dealer"]["id"])

    resp = api.create_install_window(
        make_install_window_payload(
            ctx["phase"]["id"],
            start_at="2026-12-01T10:00:00Z",
            end_at="2026-12-01T13:00:00Z",
            union_required=True,
            elevator_required=True,
            crew_size=4,
        ),
        dealer_h,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)
