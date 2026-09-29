"""Two window conventions that disagree on purpose at the shared instant.

Selection-event windows are half-open, so two events may touch; seat hold
windows are closed, so a pick landing exactly on a prior hold's ``hold_end``
still collides with it.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_SEAT_HOLD_CONFLICT,
    ERR_SELECTION_WINDOW_OVERLAP,
)
from test_helpers.assertions import (
    assert_instant,
    assert_seat_inventory,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    EVENT_OPEN,
    EVENT_SLOTS_PUBLISHED,
    NON_ALUMNUS,
    OCCUPANCY_HELD,
    OCCUPANCY_RELEASED,
    RELEASE_SUPERSEDED_BY_NEW_HOLD,
    SEAT_HELD,
    SLOT_CONSUMED,
    SLOT_SCHEDULED,
)
from test_helpers.fixtures import (
    certified_cycle,
    create_event,
    create_section_with_seats,
    gate_event,
    publish_and_open,
    publish_slots,
    read_assignment,
    read_event,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import OFFICER, make_donor_headers


def _three_events_touching_and_overlapping(client):
    """EV1 open, EV2 abutting its end exactly, EV3 overlapping EV2's interior.

    Only EV1 and EV2 have their slots published here.  EV3 is left in ``DRAFT``
    on purpose: the gate check of PRD 2.8 step 16 reads every *other* event on
    the recalculation that is in ``SLOTS_PUBLISHED`` or ``OPEN``, so publishing
    EV3 up front would make EV2's own gate collide with EV3 and there would be
    no way to observe the permitted boundary touch at all.  Each test that
    needs EV3's slots publishes them once EV2 is already ``OPEN``.
    """
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)

    windows = (
        (f.instant(2026, 9, 1), f.instant(2026, 9, 5)),
        (f.instant(2026, 9, 5), f.instant(2026, 9, 9)),
        (f.instant(2026, 9, 8), f.instant(2026, 9, 12)),
    )
    events = [
        create_event(client, cycle["id"], window_start, window_end, 2880)
        for window_start, window_end in windows
    ]
    publish_slots(client, events[0]["id"])
    publish_slots(client, events[1]["id"])

    gate_event(client, events[0]["id"], EVENT_OPEN)
    return donor, events


class TestSelectionEventWindowsAreHalfOpen:
    """Touching at a shared boundary is permitted; interior overlap is not."""

    def test_an_event_may_open_touching_the_previous_window(self, client):
        """EV2 starts at exactly EV1's excluded upper bound, so it may open.

        PRD 3.6: "Event windows on the same recalculation are half-open by the
        same convention, so two events may touch at a shared boundary instant
        without overlapping, while any genuine interior overlap is a conflict."

        Design: Difficulty/resource_temporal_overlap/selection_event_windows_half_open_adjacency_allowed_overlap_rejected
        """
        _donor, events = _three_events_touching_and_overlapping(client)

        opened = gate_event(client, events[1]["id"], EVENT_OPEN)
        assert opened["status"] == EVENT_OPEN

    def test_an_interior_overlap_is_refused(self, client):
        """EV3 overlaps EV2's interior by a day, so its gate is rejected.

        PRD 2.9: "The event's window does not overlap the window of another
        event on the same recalculation that is in `SLOTS_PUBLISHED` or `OPEN`;
        touching at a shared boundary instant is permitted. This applies to the
        event gate operation. Violation: `ERR_SELECTION_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/selection_event_windows_half_open_adjacency_allowed_overlap_rejected
        """
        _donor, events = _three_events_touching_and_overlapping(client)
        gate_event(client, events[1]["id"], EVENT_OPEN)
        publish_slots(client, events[2]["id"])

        refused = client.gate_selection_event(
            events[2]["id"], f.gate_payload(EVENT_OPEN), headers=OFFICER
        )
        validate_error(refused, ERR_SELECTION_WINDOW_OVERLAP, 409)

        assert read_event(client, events[2]["id"])["status"] == EVENT_SLOTS_PUBLISHED

    def test_the_refusal_leaves_every_published_slot_scheduled(self, client):
        """A blocked gate is inert: EV1 stays open and no slot moves.

        PRD 3.6: "`published_slot_count` and `scheduled_slot_count` are both set
        to the pool size, every new slot starts in `slot_status` `SCHEDULED`,
        and the event's `version` advances by 1."

        Design: Difficulty/resource_temporal_overlap/selection_event_windows_half_open_adjacency_allowed_overlap_rejected
        """
        donor, events = _three_events_touching_and_overlapping(client)
        gate_event(client, events[1]["id"], EVENT_OPEN)
        publish_slots(client, events[2]["id"])
        client.gate_selection_event(
            events[2]["id"], f.gate_payload(EVENT_OPEN), headers=OFFICER
        )

        assert read_event(client, events[0]["id"])["status"] == EVENT_OPEN
        for event in events:
            slot = slot_for_donor(client, event["id"], donor["id"])
            assert slot["slot_index"] == 0
            assert slot["slot_status"] == SLOT_SCHEDULED


def _seat_held_up_to_its_boundary(client):
    """Donor A holds seat I/1 and the clock sits exactly on that hold's end."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("I", 1, {"max_concurrent_holds": 1}), ("I", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    seat_i1 = seats[0]

    donor_a = register_donor(client, alumni_status=NON_ALUMNUS)
    donor_b = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 6), 2880
    )
    slot_a = slot_for_donor(client, event["id"], donor_a["id"])
    slot_b = slot_for_donor(client, event["id"], donor_b["id"])

    set_clock(client, f.instant(2026, 9, 1, 12))
    held = validate_success(
        client.pick_seat(
            slot_a["id"],
            f.pick_payload(seat_i1["id"], read_seat(client, seat_i1["id"])["version"]),
            headers=make_donor_headers(donor_a["id"]),
        ),
        201,
    )

    set_clock(client, f.instant(2026, 9, 4, 12))
    seat_version = read_seat(client, seat_i1["id"])["version"]
    return section, seat_i1, donor_b, slot_b, held, seat_version


def _pick_i1(client, slot_b, seat_i1, donor_b, seat_version):
    return client.pick_seat(
        slot_b["id"],
        f.pick_payload(seat_i1["id"], seat_version),
        headers=make_donor_headers(donor_b["id"]),
    )


class TestSeatHoldWindowsAreClosed:
    """A pick at exactly a prior hold's end still collides with it."""

    def test_the_hold_runs_seventy_two_hours_from_the_pick_instant(self, client):
        """hold_start is the clock at the pick and hold_end is 4,320 minutes on.

        PRD 3.9: "Its hold window is closed at both ends: `hold_start` is the
        current logical clock instant and `hold_end` is 72 hours later — a hold
        lasts 4,320 minutes."

        Design: Difficulty/resource_temporal_overlap/seat_hold_windows_closed_interval_touching_rejected
        """
        _section, _seat, _donor_b, _slot_b, held, _v = _seat_held_up_to_its_boundary(
            client
        )

        assert_instant(held["hold_start"], "2026-09-01T12:00:00.000Z", "hold_start")
        assert_instant(held["hold_end"], "2026-09-04T12:00:00.000Z", "hold_end")

    def test_a_pick_at_exactly_the_hold_end_collides(self, client):
        """The closed upper bound is still occupied, so the seat is at capacity.

        PRD 2.9: "The number of the seat's hold windows whose closed intervals
        contain the pick instant is strictly below the seat's
        `max_concurrent_holds`. This applies to seat picks only. Violation:
        `ERR_SEAT_HOLD_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/seat_hold_windows_closed_interval_touching_rejected
        """
        _section, seat_i1, donor_b, slot_b, _held, version = (
            _seat_held_up_to_its_boundary(client)
        )

        refused = _pick_i1(client, slot_b, seat_i1, donor_b, version)
        validate_error(refused, ERR_SEAT_HOLD_CONFLICT, 409)

        assert read_slot(client, slot_b["id"])["slot_status"] == SLOT_SCHEDULED

    def test_one_millisecond_later_the_pick_supersedes_the_stale_hold(self, client):
        """Past the closed end the earlier hold is displaced, not blocking.

        PRD 3.9: "When the seat already carries a hold whose closed interval has
        ended before the pick instant, that earlier assignment is moved `HELD →
        RELEASED` by the system with `release_reason` set to
        `SUPERSEDED_BY_NEW_HOLD` and its `version` advanced by 1 — and, unlike a
        donor-initiated release, the seat is **left in `HELD`** for the incoming
        assignment rather than returned to `AVAILABLE`, because the seat never
        actually became free."

        Design: Difficulty/resource_temporal_overlap/seat_hold_windows_closed_interval_touching_rejected
        """
        _section, seat_i1, donor_b, slot_b, held, version = (
            _seat_held_up_to_its_boundary(client)
        )
        _pick_i1(client, slot_b, seat_i1, donor_b, version)

        set_clock(client, f.instant(2026, 9, 4, 12, 0, 0, 1))
        accepted = _pick_i1(client, slot_b, seat_i1, donor_b, version)
        second = validate_success(accepted, 201)

        superseded = read_assignment(client, held["id"])
        assert superseded["occupancy_status"] == OCCUPANCY_RELEASED
        assert superseded["release_reason"] == RELEASE_SUPERSEDED_BY_NEW_HOLD

        assert second["occupancy_status"] == OCCUPANCY_HELD
        assert_instant(second["hold_start"], "2026-09-04T12:00:00.001Z", "hold_start")
        assert_instant(second["hold_end"], "2026-09-07T12:00:00.001Z", "hold_end")

    def test_the_supersede_leaves_the_seat_held_rather_than_free(self, client):
        """The seat never became free, so the inventory does not swing back.

        PRD 2.5: "`seat_row_count` is the number of seat rows in the section;
        `seats_available` counts those whose `seat_status` is `AVAILABLE`;
        `seats_committed_count` counts those whose `seat_status` is either `HELD`
        or `ASSIGNED`; and `decommissioned_seat_count` counts those whose
        `seat_status` is `DECOMMISSIONED`."

        Design: Difficulty/resource_temporal_overlap/seat_hold_windows_closed_interval_touching_rejected
        """
        section, seat_i1, donor_b, slot_b, _held, version = (
            _seat_held_up_to_its_boundary(client)
        )
        set_clock(client, f.instant(2026, 9, 4, 12, 0, 0, 1))
        validate_success(_pick_i1(client, slot_b, seat_i1, donor_b, version), 201)

        assert read_seat(client, seat_i1["id"])["seat_status"] == SEAT_HELD
        assert_seat_inventory(
            read_section(client, section["id"]),
            seats_available=1,
            seats_committed_count=1,
            decommissioned_seat_count=0,
            seat_row_count=2,
        )
        assert read_slot(client, slot_b["id"])["slot_status"] == SLOT_CONSUMED
