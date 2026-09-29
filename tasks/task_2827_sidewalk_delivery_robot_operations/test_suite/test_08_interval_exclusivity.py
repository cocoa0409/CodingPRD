"""Two exclusivity tests over the same shape of data with opposite semantics.

A bay window is half-open and inflated by a fifteen-minute buffer on both sides,
while a hard closure interval is fully closed and carries no buffer at all, so
the boundary case of one is the accepted case of the other.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    add_depot_bay,
    api_client,
    create_bay_reservation_payload,
    create_segment_closure_payload,
    read_bay,
    read_closure,
    read_segment,
    read_zone,
    reserve_bay,
    setup_permitted_zone,
    setup_available_robot,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_WINDOW = {
    "window_start_utc": "2026-08-03T10:00:00.000Z",
    "window_end_utc": "2026-08-03T11:00:00.000Z",
}
FOURTEEN_MINUTES_LATER = {
    "window_start_utc": "2026-08-03T11:14:00.000Z",
    "window_end_utc": "2026-08-03T12:00:00.000Z",
}
FIFTEEN_MINUTES_LATER = {
    "window_start_utc": "2026-08-03T11:15:00.000Z",
    "window_end_utc": "2026-08-03T12:00:00.000Z",
}
FIRST_CLOSURE = {
    "closure_kind": "HARD",
    "cause": "CONSTRUCTION",
    "starts_at_utc": "2026-08-03T08:00:00.000Z",
    "ends_at_utc": "2026-08-03T10:00:00.000Z",
}
TOUCHING_WINDOW = {
    "starts_at_utc": "2026-08-03T10:00:00.000Z",
    "ends_at_utc": "2026-08-03T11:00:00.000Z",
}
MINUTE_AFTER_WINDOW = {
    "starts_at_utc": "2026-08-03T10:01:00.000Z",
    "ends_at_utc": "2026-08-03T11:00:00.000Z",
}


def _bay_holding_one_hour_window() -> dict:
    """An open charge bay with one HELD reservation over [10:00, 11:00), and the
    bay re-read so the client holds the concurrency token the ledger left."""
    ctx = setup_available_robot()
    bay = add_depot_bay(ctx["z"], "B1", bay_type="CHARGE", power_kw=22.0, state="OPEN")
    ctx["reservation"] = reserve_bay(bay, ctx["r"], **FIRST_WINDOW)
    ctx["res"] = ctx["reservation"]["id"]
    ctx["b"] = bay["id"]
    ctx["bay"] = read_bay(bay["id"])
    return ctx


class TestBayWindowTurnaroundBuffer:
    def test_a_window_starting_fourteen_minutes_after_the_last_one_conflicts(self, api):
        """PRD §3.4: "Bay windows are exclusive, and the exclusivity test is not
        a bare interval overlap: each existing reservation of the same bay whose
        `state` is `HELD` or `ACTIVE` is first inflated by a turnaround buffer of
        15 minutes on both sides, to allow a robot to vacate and the next one to
        arrive."
        PRD §3.4: "Because the comparisons are strict at both ends, a window that
        starts exactly 15 minutes after an existing window ends is accepted, while
        one that starts 14 minutes after it ends is rejected."

        Design: Difficulty/resource_temporal_overlap/bay_window_half_open_with_turnaround_buffer
        """
        ctx = _bay_holding_one_hour_window()
        assert ctx["reservation"]["window_minutes"] == 60

        validate_error(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["b"], ctx["r"], ctx["bay"]["version"], **FOURTEEN_MINUTES_LATER
                ),
                DISPATCHER,
            ),
            "ERR_BAY_WINDOW_CONFLICT",
        )

        assert read_bay(ctx["b"])["committed_minutes"] == 60
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 60

    def test_a_window_starting_exactly_fifteen_minutes_later_books_its_minutes(self, api):
        """PRD §3.4: "From that window the server derives `window_minutes` as the
        number of whole minutes from start to end, discarding any partial minute,
        and that value is frozen for the life of the reservation even though the
        window fields themselves are also immutable."
        PRD §3.4: "Creating a reservation books its minutes into two denormalized
        ledgers at once: the bay's `committed_minutes` increases by
        `window_minutes` and the zone's `reserved_bay_minutes` increases by the
        same amount, with the `version` of the bay, the zone and the new
        reservation each advancing by one."

        Design: Difficulty/resource_temporal_overlap/bay_window_half_open_with_turnaround_buffer
        """
        ctx = _bay_holding_one_hour_window()

        second = validate_success(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["b"], ctx["r"], ctx["bay"]["version"], **FIFTEEN_MINUTES_LATER
                ),
                DISPATCHER,
            ),
            201,
        )

        rows, _meta = validate_paginated(
            api.list_bay_reservations(DISPATCHER, {"bay_id": ctx["b"], "state": "HELD"})
        )
        assert second["window_minutes"] == 45
        assert second["state"] == "HELD"
        assert read_bay(ctx["b"])["committed_minutes"] == 105
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 105
        assert len(rows) == 2


def _segment_with_one_scheduled_hard_closure() -> dict:
    """An approved segment carrying a single SCHEDULED hard closure over the
    closed interval 08:00 through 10:00."""
    ctx = setup_permitted_zone()
    closure = validate_success(
        api_client.create_segment_closure(
            create_segment_closure_payload(ctx["s1"], **FIRST_CLOSURE), ADMIN
        ),
        201,
    )
    ctx["closure"] = closure
    ctx["cl1"] = closure["id"]
    return ctx


class TestHardClosureClosedInterval:
    def test_a_hard_closure_starting_where_the_last_one_ends_conflicts(self, api):
        """PRD §3.2: "When a hard closure is scheduled, its interval is compared
        against the interval of every existing closure of the same segment that
        is also `HARD` and whose `state` is `SCHEDULED` or `ACTIVE`; a conflict
        exists when the new closure's start is at or before the existing
        closure's end and the new closure's end is at or after the existing
        closure's start."
        PRD §3.2: "Because both interval endpoints are inclusive and no buffer is
        applied, two hard closures that merely touch at a shared instant do
        conflict, and the request is refused with `ERR_HARD_CLOSURE_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hard_closure_closed_interval_no_buffer
        """
        ctx = _segment_with_one_scheduled_hard_closure()
        assert ctx["closure"]["state"] == "SCHEDULED"

        validate_error(
            api.create_segment_closure(
                create_segment_closure_payload(
                    ctx["s1"], closure_kind="HARD", cause="EVENT", **TOUCHING_WINDOW
                ),
                ADMIN,
            ),
            "ERR_HARD_CLOSURE_OVERLAP",
        )

        rows, _meta = validate_paginated(
            api.list_segment_closures(ADMIN, {"segment_id": ctx["s1"], "closure_kind": "HARD"})
        )
        assert len(rows) == 1

    def test_an_advisory_closure_over_the_contested_window_never_conflicts(self, api):
        """PRD §3.2: "Advisory closures are outside the scope of this test
        entirely: an advisory closure never conflicts with anything, in either
        direction."
        PRD §3.2: "A new closure lands in `state` `SCHEDULED` with
        `reroute_triggered_count` at zero."

        Design: Difficulty/resource_temporal_overlap/hard_closure_closed_interval_no_buffer
        """
        ctx = _segment_with_one_scheduled_hard_closure()

        advisory = validate_success(
            api.create_segment_closure(
                create_segment_closure_payload(
                    ctx["s1"], closure_kind="ADVISORY", cause="EVENT", **TOUCHING_WINDOW
                ),
                ADMIN,
            ),
            201,
        )

        assert advisory["state"] == "SCHEDULED"
        assert advisory["reroute_triggered_count"] == 0
        assert read_segment(ctx["s1"])["status"] == "APPROVED"

    def test_a_hard_closure_one_minute_after_the_shared_instant_is_accepted(self, api):
        """PRD §3.2: "Because both interval endpoints are inclusive and no buffer
        is applied, two hard closures that merely touch at a shared instant do
        conflict, and the request is refused with `ERR_HARD_CLOSURE_OVERLAP`
        (HTTP 409)."
        PRD §3.2: "The distinction between the two kinds is total: a `HARD`
        closure blocks the segment and forces reroutes, while an `ADVISORY`
        closure is purely informational and never changes a segment's status."

        Design: Difficulty/resource_temporal_overlap/hard_closure_closed_interval_no_buffer
        """
        ctx = _segment_with_one_scheduled_hard_closure()

        later = validate_success(
            api.create_segment_closure(
                create_segment_closure_payload(
                    ctx["s1"], closure_kind="HARD", cause="EVENT", **MINUTE_AFTER_WINDOW
                ),
                ADMIN,
            ),
            201,
        )

        rows, _meta = validate_paginated(
            api.list_segment_closures(ADMIN, {"segment_id": ctx["s1"], "closure_kind": "HARD"})
        )
        assert later["state"] == "SCHEDULED"
        assert len(rows) == 2
        assert read_closure(ctx["cl1"])["state"] == "SCHEDULED"
        assert read_segment(ctx["s1"])["status"] == "APPROVED"
