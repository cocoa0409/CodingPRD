"""Two scarce resources booked against overlapping intervals.

A cabin is held by whole dates with no buffer, so back-to-back weeks touch
without clashing; a horse is held by the minute plus an hour of recovery.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_booking_payload,
    mount_assignment_payload,
    party_member,
)
from test_helpers.fixtures import (
    build_activity_slot,
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_open_season,
    build_ready_rider,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
)


def _cabin_held_for_the_first_week(client):
    """Aspen held 2026-10-04 to 2026-10-11 by one party of three."""
    season = build_open_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
    ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
    cal = build_guest(client, "Cal Child", "2016-05-20", 95)
    dee = build_guest(client, "Dee Adult", "1990-01-15", 175)
    eli = build_guest(client, "Eli Adult", "1988-06-05", 180)
    fay = build_guest(client, "Fay Child", "2015-03-03", 90)
    party_a = [
        party_member(ann["id"], "ADULT"),
        party_member(ben["id"], "ADULT"),
        party_member(cal["id"], "CHILD"),
    ]
    party_b = [
        party_member(dee["id"], "ADULT"),
        party_member(eli["id"], "ADULT"),
        party_member(fay["id"], "CHILD"),
    ]
    booking_a = build_booking(
        client,
        season["id"],
        cabin["id"],
        party_a,
        package_tier_code="CLASSIC",
        arrival_date="2026-10-04",
        departure_date="2026-10-11",
    )
    return season, cabin, booking_a, party_a, party_b


class TestCabinStayIntervalsAreHalfOpen:
    """A departure date and an arrival date may be the same calendar day."""

    def test_the_next_party_may_arrive_on_the_first_partys_departure_day(self, client):
        """The weekly cadence hands the cabin over without an idle night.

        PRD: "A booking occupies its cabin from `arrival_date` inclusive up to but
        not including `departure_date`."

        Design: Difficulty/resource_temporal_overlap/cabin_stay_intervals_are_half_open_so_adjacency_is_legal
        """
        season, cabin, booking_a, _party_a, party_b = _cabin_held_for_the_first_week(client)
        adjacent = validate_success(
            client.create_booking(
                create_booking_payload(
                    season["id"],
                    cabin["id"],
                    party_b[0]["guest_id"],
                    party_b,
                    "CLASSIC",
                    "2026-10-11",
                    "2026-10-18",
                ),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        assertions.assert_booking(adjacent)
        assert adjacent["provisional_package_total_cents"] == 1258691
        assert adjacent["arrival_date"] == "2026-10-11"
        assert booking_a["departure_date"] == "2026-10-11"

    def test_re_booking_the_identical_week_in_the_same_cabin_is_refused(self, client):
        """A whole shared week is a genuine clash, unlike a shared boundary day.

        PRD: "Two bookings on the same cabin conflict exactly when the candidate's
        arrival falls strictly before the existing booking's departure *and* the
        existing booking's arrival falls strictly before the candidate's
        departure; consequently one party departing on the very day another
        arrives is not a conflict, while a single overlapping night is."

        Design: Difficulty/resource_temporal_overlap/cabin_stay_intervals_are_half_open_so_adjacency_is_legal
        """
        season, cabin, _booking_a, party_a, party_b = _cabin_held_for_the_first_week(client)
        get_success_data(
            client.create_booking(
                create_booking_payload(
                    season["id"],
                    cabin["id"],
                    party_b[0]["guest_id"],
                    party_b,
                    "CLASSIC",
                    "2026-10-11",
                    "2026-10-18",
                ),
                RESERVATIONS_AGENT,
            )
        )
        validate_error(
            client.create_booking(
                create_booking_payload(
                    season["id"],
                    cabin["id"],
                    party_a[0]["guest_id"],
                    party_a,
                    "CLASSIC",
                    "2026-10-11",
                    "2026-10-18",
                ),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_CABIN_DOUBLE_BOOKED.value,
            409,
        )
        rows, meta = validate_paginated(
            client.list_bookings(RESERVATIONS_AGENT, {"cabin_id": cabin["id"]})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2


def _one_horse_and_three_evening_rides(client):
    """Comet booked on the 15:00 ride, with a 17:30 and an 18:00 ride waiting."""
    season = build_open_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, "BEGINNER")
    ben = build_ready_rider(client, "Ben Adult", "1983-07-11", 190, "BEGINNER")
    cy = build_ready_rider(client, "Cy Adult", "1979-02-09", 175, "BEGINNER")
    booking = build_booking(
        client,
        season["id"],
        cabin["id"],
        [
            party_member(ann["id"], "ADULT"),
            party_member(ben["id"], "ADULT"),
            party_member(cy["id"], "ADULT"),
        ],
        package_tier_code="CLASSIC",
        arrival_date="2026-10-11",
        departure_date="2026-10-18",
    )
    animal = build_horse(
        client,
        name="Comet",
        min_rider_ability="BEGINNER",
        max_rider_ability="ADVANCED",
        weight_limit_lb=240,
    )
    slots = []
    for starts_at, ends_at in (
        ("2026-10-12T15:00:00Z", "2026-10-12T17:00:00Z"),
        ("2026-10-12T17:30:00Z", "2026-10-12T19:30:00Z"),
        ("2026-10-12T18:00:00Z", "2026-10-12T20:00:00Z"),
    ):
        slots.append(
            build_activity_slot(
                client,
                season["id"],
                activity_type="TRAIL_RIDE",
                starts_at=starts_at,
                ends_at=ends_at,
                terrain_grade="MEADOW",
                min_ability_rank="BEGINNER",
                capacity=4,
                rider_surcharge_cents=0,
                mount_required=True,
            )
        )
    slot_a, slot_b, slot_c = slots
    seat_a = take_seat(client, slot_a["id"], booking["id"], ann["id"])
    seat_b = take_seat(client, slot_b["id"], booking["id"], ben["id"])
    seat_c = take_seat(client, slot_c["id"], booking["id"], cy["id"])

    horse_row = get_success_data(client.get_horse(animal["id"], HORSE_PROGRAM_DIRECTOR))
    get_success_data(
        client.assign_mount(
            seat_a["id"],
            mount_assignment_payload(animal["id"], horse_row["version"]),
            HORSE_PROGRAM_DIRECTOR,
        )
    )
    return {
        "booking": booking,
        "horse": animal,
        "slot_b": slot_b,
        "slot_c": slot_c,
        "seat_b": seat_b,
        "seat_c": seat_c,
    }


def _assign_comet(client, horse_id, reservation_id):
    """Pin the horse version read just now and offer it to the seat."""
    horse_row = get_success_data(client.get_horse(horse_id, HORSE_PROGRAM_DIRECTOR))
    return client.assign_mount(
        reservation_id,
        mount_assignment_payload(horse_id, horse_row["version"]),
        HORSE_PROGRAM_DIRECTOR,
    )


class TestHorseRecoveryBufferIsStrictlySixtyMinutes:
    """Half an hour off is not enough rest; a full hour is."""

    def test_a_thirty_minute_gap_between_rides_is_refused(self, client):
        """The 17:30 ride comes too soon after the 17:00 finish.

        PRD: "That buffer test is deliberately strict on both sides: two rides
        conflict when the candidate slot starts before the other slot's `ends_at`
        plus 60 minutes **and** the other slot starts before the candidate's
        `ends_at` plus 60 minutes."

        Design: Difficulty/resource_temporal_overlap/horse_mount_intervals_carry_a_strict_sixty_minute_recovery_buffer
        """
        fixture = _one_horse_and_three_evening_rides(client)
        assert fixture["booking"]["provisional_package_total_cents"] == 1438500
        loaded = validate_success(
            client.get_horse(fixture["horse"]["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assertions.assert_horse_load(loaded, scheduled_load_hours=2.0)

        validate_error(
            _assign_comet(client, fixture["horse"]["id"], fixture["seat_b"]["id"]),
            ApiErrorId.ERR_MOUNT_INTERVAL_CONFLICT.value,
            409,
        )
        seat_b = validate_success(
            client.get_reservation(fixture["seat_b"]["id"], RESERVATIONS_AGENT)
        )
        assert seat_b["mount_status"] == "PENDING"
        assert seat_b["assigned_horse_id"] is None

        slot_b = validate_success(
            client.get_activity_slot(fixture["slot_b"]["id"], RANCH_MANAGER)
        )
        assertions.assert_slot_counters(slot_b, mount_assigned_count=0)

    def test_a_gap_of_exactly_sixty_minutes_is_permitted(self, client):
        """The 18:00 ride is exactly one hour clear, so Comet may go out again.

        PRD: "An accepted assignment moves the seat's `mount_status` from
        `PENDING` or `RELEASED` to `ASSIGNED`, sets `assigned_horse_id`, adds the
        slot's `duration_hours` to the horse's `scheduled_load_hours`, raises the
        slot's `mount_assigned_count` by 1"

        Design: Difficulty/resource_temporal_overlap/horse_mount_intervals_carry_a_strict_sixty_minute_recovery_buffer
        """
        fixture = _one_horse_and_three_evening_rides(client)
        validate_error(
            _assign_comet(client, fixture["horse"]["id"], fixture["seat_b"]["id"]),
            ApiErrorId.ERR_MOUNT_INTERVAL_CONFLICT.value,
            409,
        )
        get_success_data(
            _assign_comet(client, fixture["horse"]["id"], fixture["seat_c"]["id"])
        )
        seat_c = validate_success(
            client.get_reservation(fixture["seat_c"]["id"], RESERVATIONS_AGENT)
        )
        assert seat_c["mount_status"] == "ASSIGNED"
        assert seat_c["assigned_horse_id"] == fixture["horse"]["id"]

        animal = validate_success(
            client.get_horse(fixture["horse"]["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assertions.assert_horse_load(animal, scheduled_load_hours=4.0)

        slot_c = validate_success(
            client.get_activity_slot(fixture["slot_c"]["id"], RANCH_MANAGER)
        )
        assertions.assert_slot_counters(slot_c, mount_assigned_count=1)
