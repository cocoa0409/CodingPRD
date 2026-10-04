"""Difficulty rule: resource_temporal_overlap — freight-elevator exclusivity
with the 15-minute turnover buffer, and the zone crew aggregate cap across
overlapping windows (PRD §2.8, §3.7)."""

from test_helpers import (
    ApiErrorId,
    create_window,
    make_dealer_headers,
    make_install_window_payload,
    setup_scheduled_phase,
    validate_error,
    validate_success,
)

DAY = "2026-12-02"


def _window(api, phase_id, dealer_id, start, end, crew, elevator=True,
            union=False, day=DAY):
    return api.create_install_window(
        make_install_window_payload(
            phase_id,
            start_at=f"{day}T{start}:00Z",
            end_at=f"{day}T{end}:00Z",
            union_required=union,
            elevator_required=elevator,
            crew_size=crew,
        ),
        make_dealer_headers(dealer_id),
    )


def test_exactly_15_minute_gap_accepted(api):
    """PRD §3.7: "In practice this means back-to-back booking is allowed only
    when the new window's `start_at` is at least 15 minutes after the
    existing window's `end_at`" — a window starting exactly 15 minutes after
    (and one ending exactly 15 minutes before) an existing elevator window is
    accepted.

    Design: Difficulty/resource_temporal_overlap/freight_elevator_exclusive_with_15min_turnover_buffer
    """
    ctx = setup_scheduled_phase(api)
    dealer_id = ctx["dealer"]["id"]
    phase_id = ctx["phase"]["id"]

    w1 = create_window(api, phase_id, dealer_id)  # 2026-12-01 09:00-12:00
    assert w1["status"] == "RESERVED"

    # Exactly the 15-minute turnover buffer after W1 ends.
    resp = api.create_install_window(
        make_install_window_payload(
            phase_id,
            start_at="2026-12-01T12:15:00Z",
            end_at="2026-12-01T13:00:00Z",
            crew_size=2,
        ),
        make_dealer_headers(dealer_id),
    )
    w2 = validate_success(resp, 201)
    assert w2["status"] == "RESERVED"

    # Ends exactly 15 minutes before W1 starts (buffer on the other side).
    resp = api.create_install_window(
        make_install_window_payload(
            phase_id,
            start_at="2026-12-01T07:00:00Z",
            end_at="2026-12-01T08:45:00Z",
            crew_size=2,
        ),
        make_dealer_headers(dealer_id),
    )
    w4 = validate_success(resp, 201)
    assert w4["status"] == "RESERVED"


def test_14_minute_gap_rejected(api):
    """PRD §3.7: "starting 14 minutes after still conflicts" — the rejection
    is `ERR_WINDOW_CONFLICT` (HTTP 409).

    Design: Difficulty/resource_temporal_overlap/freight_elevator_exclusive_with_15min_turnover_buffer
    """
    ctx = setup_scheduled_phase(api)
    dealer_id = ctx["dealer"]["id"]
    create_window(api, ctx["phase"]["id"], dealer_id)  # 09:00-12:00

    resp = api.create_install_window(
        make_install_window_payload(
            ctx["phase"]["id"],
            start_at="2026-12-01T12:14:00Z",
            end_at="2026-12-01T13:00:00Z",
            crew_size=2,
        ),
        make_dealer_headers(dealer_id),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)


def test_overlapping_crews_sum_to_cap_and_nonoverlap_free(api):
    """PRD §3.7: the crew rule "considers all `RESERVED` windows in the zone
    regardless of `elevator_required`" and "if the total exceeds 10 the
    booking is rejected with `ERR_ZONE_CREW_CAPACITY`. Windows on the same
    date that do not overlap do not sum." Crew 6 (elevator) + crew 4 (dock,
    overlapping) = 10 is accepted; a non-overlapping crew-10 window is
    accepted on its own.

    Design: Difficulty/resource_temporal_overlap/zone_crew_aggregate_capacity_across_overlapping_windows
    """
    ctx = setup_scheduled_phase(api)
    phase_id = ctx["phase"]["id"]
    dealer_id = ctx["dealer"]["id"]

    resp = _window(api, phase_id, dealer_id, "09:00", "13:00", 6)
    assert validate_success(resp, 201)["status"] == "RESERVED"
    resp = _window(api, phase_id, dealer_id, "10:00", "14:00", 4,
                   elevator=False)
    assert validate_success(resp, 201)["status"] == "RESERVED"
    # Overlaps neither window -> no crew sum applies even at crew 10.
    resp = _window(api, phase_id, dealer_id, "14:30", "16:00", 10,
                   elevator=False)
    assert validate_success(resp, 201)["status"] == "RESERVED"


def test_crew_sum_over_cap_rejected(api):
    """PRD §3.7: "if the total exceeds 10 the booking is rejected with
    `ERR_ZONE_CREW_CAPACITY`" — a dock window with crew 1 overlapping the 6 +
    4 already reserved pushes the zone's overlapping crew to 11.

    Design: Difficulty/resource_temporal_overlap/zone_crew_aggregate_capacity_across_overlapping_windows
    """
    ctx = setup_scheduled_phase(api)
    phase_id = ctx["phase"]["id"]
    dealer_id = ctx["dealer"]["id"]

    _window(api, phase_id, dealer_id, "09:00", "13:00", 6)
    _window(api, phase_id, dealer_id, "10:00", "14:00", 4, elevator=False)

    resp = _window(api, phase_id, dealer_id, "11:00", "12:00", 1,
                   elevator=False)
    validate_error(resp, ApiErrorId.ERR_ZONE_CREW_CAPACITY)
