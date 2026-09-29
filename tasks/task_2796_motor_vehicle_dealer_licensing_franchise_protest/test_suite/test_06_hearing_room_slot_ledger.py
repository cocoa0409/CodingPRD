"""The hearing docket as a shared resource: the buffered interval test and the
room-slot ledger that has to give a slot back completely.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_docket_released,
    assert_room_slot_ledger,
    assert_same_instant,
)
from test_helpers.test_users import HEARING_CLERK


def _two_protests_with_the_first_docketed():
    """One room, one incumbent at the origin, two ADDITIONAL_POINT filings and
    two protests, with the first protest docketed 10:00-13:00 on 2026-11-02.

    The second proposed point sits exactly on the 24.00 km relevant-market
    radius, so the second protestant has standing too and the two protests
    compete for the same room on the same day.
    """
    ctx = fx.setup_licensed_dealer()
    manufacturer, dealer = ctx["manufacturer"], ctx["dealer"]
    ctx["room"] = fx.create_hearing_room()

    first_filing = fx.open_additional_point_filing(
        manufacturer["id"], proposed_effective_on="2026-11-15",
        site_x_km=9, site_y_km=12)
    second_filing = fx.open_additional_point_filing(
        manufacturer["id"], proposed_effective_on="2026-11-16",
        site_x_km=14.4, site_y_km=19.2)

    fx.set_clock("2026-09-10T00:00:00Z")
    first_filing = fx.serve_notice(first_filing["id"], manufacturer["id"])
    second_filing = fx.serve_notice(second_filing["id"], manufacturer["id"])
    ctx["first_filing"], ctx["second_filing"] = first_filing, second_filing

    fx.set_clock("2026-09-15T00:00:00Z")
    ctx["first_protest"] = fx.file_protest(
        first_filing["id"], dealer["id"], first_filing["version"],
        grounds_code="MARKET_ENCROACHMENT")
    ctx["second_protest"] = fx.file_protest(
        second_filing["id"], dealer["id"], second_filing["version"],
        grounds_code="MARKET_ENCROACHMENT")

    ctx["first_protest"] = fx.schedule_hearing(
        ctx["first_protest"]["id"], ctx["room"]["id"], ctx["room"]["version"],
        "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z")
    ctx["room"] = fx.read_room(ctx["room"]["id"])
    return ctx


def _docket(protest_id, room_id, room_version, start_at, end_at):
    """Attempt a docketing without asserting success, as the hearing clerk."""
    return api_client.schedule_protest_hearing(
        protest_id,
        f.schedule_payload(room_id, start_at, end_at, room_version),
        HEARING_CLERK,
    )


class TestBufferedRoomCollision:
    def test_a_thirty_minute_gap_collides_with_the_sitting_hearing(self, api):
        """PRD 3.6: "Two bookings collide when the new booking's start is earlier
        than the existing booking's end extended forward by the room's
        `buffer_minutes`, and the existing booking's start is earlier than the new
        booking's end extended forward by the same buffer." A 13:30 start is
        earlier than 13:00 pushed out to 14:00, so the 60-minute changeover is
        not respected. PRD 3.6: "Because both comparisons are strict, a gap
        exactly equal to the buffer is permitted, while genuinely back-to-back
        bookings collide. A collision is refused with
        `ERR_HEARING_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_overlap_rejects_adjacent_session
        """
        ctx = _two_protests_with_the_first_docketed()
        room = ctx["room"]
        assert room["buffer_minutes"] == 60
        assert room["booked_hearing_count"] == 1
        assert ctx["first_protest"]["distance_to_site_km"] == 15.00
        assert ctx["second_protest"]["distance_to_site_km"] == 24.00

        response = _docket(
            ctx["second_protest"]["id"], room["id"], room["version"],
            "2026-11-02T13:30:00Z", "2026-11-02T15:30:00Z")
        validate_error(response, ApiErrorId.ERR_HEARING_ROOM_CONFLICT.value,
                       expected_status=409)

        after_room = fx.read_room(room["id"])
        after_protest = fx.read_protest(ctx["second_protest"]["id"])
        assert after_room["booked_hearing_count"] == 1
        assert after_protest["status"] == "FILED"
        assert_docket_released(after_protest)

    def test_a_gap_of_exactly_the_buffer_is_admitted(self, api):
        """PRD 3.6: "Because both comparisons are strict, a gap exactly equal to
        the buffer is permitted, while genuinely back-to-back bookings collide."
        A 14:00 start leaves exactly the 60 minutes of changeover after a 13:00
        end. PRD 3.6: "Docketing stores all four docket fields on the protest,
        derives `evidence_deadline_at` as exactly 7 days before
        `hearing_start_at`, increments the room's `booked_hearing_count` by 1 and
        increments the room's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_overlap_rejects_adjacent_session
        """
        ctx = _two_protests_with_the_first_docketed()
        room = ctx["room"]

        docketed = get_success_data(_docket(
            ctx["second_protest"]["id"], room["id"], room["version"],
            "2026-11-02T14:00:00Z", "2026-11-02T16:00:00Z"))

        assert docketed["status"] == "SCHEDULED"
        assert docketed["hearing_room_id"] == room["id"]
        assert_same_instant(docketed["hearing_start_at"], "2026-11-02T14:00:00Z")
        assert_same_instant(docketed["hearing_end_at"], "2026-11-02T16:00:00Z")
        assert_same_instant(docketed["evidence_deadline_at"], "2026-10-26T14:00:00Z")
        assert docketed["hearing_session_count"] == 1

        after_room = fx.read_room(room["id"])
        assert after_room["booked_hearing_count"] == 2
        assert after_room["version"] == room["version"] + 1
        assert_room_slot_ledger(
            after_room,
            [fx.read_protest(ctx["first_protest"]["id"]), docketed])


class TestSlotReleasedByAmendment:
    def test_the_amendment_cascade_hands_the_whole_slot_back(self, api):
        """PRD 3.4: "For each of those withdrawn protests the docket is released:
        `hearing_room_id`, `hearing_start_at`, `hearing_end_at` and
        `hearing_session_count` are all cleared, and for each hearing room so
        affected the room's `booked_hearing_count` is recomputed and its `version`
        increments by 1." PRD 2.11 fixes what that recomputation must yield:
        "Releasing a slot decrements the count by exactly one and frees both the
        time interval and the day slot".

        Design: Difficulty/compensating_invariant/hearing_room_session_slot_released_on_amendment
        """
        ctx = _two_protests_with_the_first_docketed()
        assert ctx["first_protest"]["status"] == "SCHEDULED"
        assert ctx["room"]["booked_hearing_count"] == 1

        fx.set_clock("2026-09-16T00:00:00Z")
        amended = fx.amend_filing(
            ctx["first_filing"]["id"], ctx["manufacturer"]["id"], "2026-11-20",
            site_x_km=9, site_y_km=12)

        assert amended["status"] == "NOTICE_SERVED"
        assert amended["active_protest_count"] == 0
        assert amended["amendment_count"] == 1

        withdrawn = fx.read_protest(ctx["first_protest"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert_docket_released(withdrawn)

        after_room = fx.read_room(ctx["room"]["id"])
        assert after_room["booked_hearing_count"] == 0
        assert after_room["version"] > ctx["room"]["version"]
        assert_room_slot_ledger(
            after_room,
            [withdrawn, fx.read_protest(ctx["second_protest"]["id"])])

    def test_the_released_interval_is_immediately_rebookable_exactly_once(self, api):
        """PRD 2.11: "so a room whose slot has just been released can be rebooked
        at the very same instant by a different protest." PRD 2.11 also bounds the
        result: "The **room-slot ledger** conserves a hearing room's
        `booked_hearing_count` as exactly the number of protests that both name
        that room and hold a slot in it", so the rebooking takes the count back to
        1 and never to 2.

        Design: Difficulty/compensating_invariant/hearing_room_session_slot_released_on_amendment
        """
        ctx = _two_protests_with_the_first_docketed()
        fx.set_clock("2026-09-16T00:00:00Z")
        fx.amend_filing(
            ctx["first_filing"]["id"], ctx["manufacturer"]["id"], "2026-11-20",
            site_x_km=9, site_y_km=12)
        released = fx.read_room(ctx["room"]["id"])
        assert released["booked_hearing_count"] == 0

        rebooked = get_success_data(_docket(
            ctx["second_protest"]["id"], released["id"], released["version"],
            "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z"))

        assert rebooked["status"] == "SCHEDULED"
        assert_same_instant(rebooked["hearing_start_at"], "2026-11-02T10:00:00Z")
        assert_same_instant(rebooked["hearing_end_at"], "2026-11-02T13:00:00Z")
        assert_same_instant(rebooked["evidence_deadline_at"], "2026-10-26T10:00:00Z")

        after_room = fx.read_room(released["id"])
        assert after_room["booked_hearing_count"] == 1
        assert after_room["booked_hearing_count"] != 2
        assert_room_slot_ledger(
            after_room,
            [fx.read_protest(ctx["first_protest"]["id"]), rebooked])
