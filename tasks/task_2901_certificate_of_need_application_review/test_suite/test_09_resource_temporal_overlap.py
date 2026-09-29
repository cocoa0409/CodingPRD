"""Two booked resources with opposite interval semantics: a room and a review slot."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    batching_cycle_payload,
    public_hearing_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    INTAKE,
    seed_batching_cycle,
    seed_hearing_room,
)

INCUMBENT_START = "2026-08-26T09:00:00Z"
INCUMBENT_END = "2026-08-26T11:00:00Z"
INCUMBENT_OCCUPANCY_START = "2026-08-26T08:00:00Z"

SECOND_CYCLE_CALENDAR = {
    "loi_deadline_at": "2026-09-25T00:00:00Z",
    "application_deadline_at": "2026-09-30T00:00:00Z",
    "comment_period_closes_at": "2026-10-05T00:00:00Z",
    "intervention_deadline_at": "2026-10-10T00:00:00Z",
    "completeness_deadline_at": "2026-10-15T00:00:00Z",
    "decision_deadline_at": "2026-10-31T00:00:00Z",
}


def _room_with_one_scheduled_hearing():
    world = seed_batching_cycle()
    world["room"] = seed_hearing_room(name="BOARD-A", setup_buffer_minutes=60)
    world["hearing_1"] = get_success_data(
        api_client.create_public_hearing(
            public_hearing_payload(
                world["cycle"]["id"],
                world["room"]["id"],
                scheduled_start_at=INCUMBENT_START,
                scheduled_end_at=INCUMBENT_END,
            ),
            INTAKE,
        ),
        201,
    )
    return world


def _book_hearing(world, start, end):
    return api_client.create_public_hearing(
        public_hearing_payload(
            world["cycle"]["id"],
            world["room"]["id"],
            scheduled_start_at=start,
            scheduled_end_at=end,
        ),
        INTAKE,
    )


class TestHearingRoomBufferedOccupancy:
    def test_the_buffer_reaches_back_before_the_gavel(self):
        """A 60-minute setup buffer starts the room's occupancy an hour early.

        PRD §3.6: "The server then computes `occupancy_start_at` as
        `scheduled_start_at` minus the room's `setup_buffer_minutes`, which is the
        true beginning of the room's exclusive occupancy."
        PRD §3.6: "A hearing is created in `SCHEDULED`, with `attendee_count` and
        `transcript_reference` null and `reschedule_count` at 0."

        Design: Difficulty/resource_temporal_overlap/hearing_room_half_open_buffered_interval_conflict
        """
        world = _room_with_one_scheduled_hearing()
        hearing = world["hearing_1"]

        assert_instant_equals(
            hearing["occupancy_start_at"], INCUMBENT_OCCUPANCY_START
        )
        assert hearing["status"] == "SCHEDULED"
        assert hearing["reschedule_count"] == 0
        assert hearing["attendee_count"] is None
        assert hearing["transcript_reference"] is None

    def test_a_booking_that_starts_when_the_incumbent_ends_still_conflicts(self):
        """Its buffered interval reaches back to 10:00, inside [08:00, 11:00).

        PRD §3.6: "Room conflicts are evaluated on that **buffered** interval,
        running from `occupancy_start_at` up to but not including
        `scheduled_end_at`, and are compared against the equally buffered
        intervals of the other hearings in the same room whose `status` is
        `SCHEDULED`."
        PRD §3.6: "Because the intervals are half-open, touching at an endpoint is
        permitted — one hearing's `scheduled_end_at` may equal the next hearing's
        `occupancy_start_at` — while any genuine overlap is refused with
        `ERR_HEARING_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_half_open_buffered_interval_conflict
        """
        world = _room_with_one_scheduled_hearing()

        response = _book_hearing(
            world, "2026-08-26T11:00:00Z", "2026-08-26T12:00:00Z"
        )

        validate_error(response, ApiErrorId.ERR_HEARING_ROOM_CONFLICT, 409)

    def test_a_booking_whose_buffered_start_touches_the_incumbents_end_succeeds(self):
        """Buffered [11:00, 13:00) only touches [08:00, 11:00) at one endpoint.

        PRD §3.6: "Because the intervals are half-open, touching at an endpoint is
        permitted — one hearing's `scheduled_end_at` may equal the next hearing's
        `occupancy_start_at` — while any genuine overlap is refused with
        `ERR_HEARING_ROOM_CONFLICT`."
        PRD §3.6: "The server then computes `occupancy_start_at` as
        `scheduled_start_at` minus the room's `setup_buffer_minutes`, which is the
        true beginning of the room's exclusive occupancy."

        Design: Difficulty/resource_temporal_overlap/hearing_room_half_open_buffered_interval_conflict
        """
        world = _room_with_one_scheduled_hearing()
        _book_hearing(world, "2026-08-26T11:00:00Z", "2026-08-26T12:00:00Z")

        response = _book_hearing(
            world, "2026-08-26T12:00:00Z", "2026-08-26T13:00:00Z"
        )

        hearing_3 = get_success_data(response, 201)
        assert_instant_equals(hearing_3["occupancy_start_at"], INCUMBENT_END)
        assert hearing_3["status"] == "SCHEDULED"

        hearings, meta = validate_paginated(
            api_client.list_public_hearings(
                INTAKE, params={"hearing_room_id": world["room"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert len(hearings) == 2


class TestCycleReviewWindowExclusivity:
    def test_sharing_a_single_instant_of_the_closed_window_is_a_conflict(self):
        """The second cycle opens exactly where the first one closes.

        PRD §3.2: "Separately, the cycle's review window — the closed interval
        running from `application_deadline_at` through `decision_deadline_at`,
        both endpoints included — must not intersect the review window of any
        other cycle for the same `hsa_id` and the same `service_type` whose
        `status` is anything other than `CLOSED`."
        PRD §3.2: "Because both windows are closed, sharing even a single instant
        is a conflict: a new cycle whose `application_deadline_at` equals an
        existing cycle's `decision_deadline_at` is refused with
        `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/batching_cycle_review_window_closed_interval_conflict
        """
        world = seed_batching_cycle()
        assert world["cycle"]["status"] == "OPEN_FOR_LOI"

        response = api_client.create_batching_cycle(
            batching_cycle_payload(
                world["hsa"]["id"], world["formula"]["id"], **SECOND_CYCLE_CALENDAR
            ),
            ADMIN,
        )

        body = validate_error(response, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP, 409)
        assert body["error_id"] != ApiErrorId.ERR_INVALID_CYCLE_WINDOW

    def test_one_second_later_clears_the_closed_interval(self):
        """Moving the opening bound past the incumbent's close makes room.

        PRD §3.2: "Separately, the cycle's review window — the closed interval
        running from `application_deadline_at` through `decision_deadline_at`,
        both endpoints included — must not intersect the review window of any
        other cycle for the same `hsa_id` and the same `service_type` whose
        `status` is anything other than `CLOSED`."
        PRD §3.2: "Fifth, inventory and need are captured:
        `inventory_beds_at_open` is the area's `existing_licensed_beds` plus its
        `approved_unimplemented_beds` as they stand at that instant, and
        `unmet_bed_need_at_open` is the greater of 0 and `required_beds_final`
        minus `inventory_beds_at_open`."

        Design: Difficulty/resource_temporal_overlap/batching_cycle_review_window_closed_interval_conflict
        """
        world = seed_batching_cycle()
        calendar = dict(SECOND_CYCLE_CALENDAR)
        calendar["application_deadline_at"] = "2026-09-30T00:00:01Z"

        response = api_client.create_batching_cycle(
            batching_cycle_payload(
                world["hsa"]["id"], world["formula"]["id"], **calendar
            ),
            ADMIN,
        )

        cycle_2 = get_success_data(response, 201)
        assert cycle_2["status"] == "OPEN_FOR_LOI"
        assert_instant_equals(
            cycle_2["application_deadline_at"], "2026-09-30T00:00:01Z"
        )
        assert cycle_2["unmet_bed_need_at_open"] == 19

        cycles, meta = validate_paginated(
            api_client.list_batching_cycles(
                ADMIN, params={"hsa_id": world["hsa"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in cycles} == {world["cycle"]["id"], cycle_2["id"]}
