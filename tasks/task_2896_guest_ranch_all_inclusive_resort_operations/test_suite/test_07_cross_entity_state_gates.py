"""Writes refused because a neighbouring record, not the target, is in the way.

A rider's seat is impeccable but her waiver has lapsed with the clock; an
arriving party's stay is impeccable but the cabin is still being cleaned.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import assertions
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    check_in_payload,
    check_out_payload,
    party_member,
    payment_payload,
    reservation_payload,
)
from test_helpers.fixtures import (
    assign_guide,
    build_activity_slot,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_in_season,
    build_ready_rider,
    confirm_booking,
    open_slot,
    set_clock_to,
)
from test_helpers.test_users import (
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
    make_activity_guide_headers,
)

DEPOSIT_CENTS = 377607


def _running_hike_whose_riders_waiver_has_lapsed(client):
    """A seat taken while the waiver was live, reached after it expired."""
    season = build_in_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_ready_rider(
        client, "Ann Adult", "1985-04-02", 165, "BEGINNER", "2025-10-13"
    )
    booking = build_booking(
        client,
        season["id"],
        cabin["id"],
        [party_member(ann["id"], "ADULT")],
        package_tier_code="CLASSIC",
        arrival_date="2026-10-11",
        departure_date="2026-10-18",
    )
    guide = build_active_guide(
        client,
        season["id"],
        full_name="Gus Guide",
        certifications=["WILDERNESS_FIRST_AID", "EQUINE_HANDLER"],
    )
    slot = build_activity_slot(
        client,
        season["id"],
        activity_type="HIKE",
        starts_at="2026-10-14T15:00:00Z",
        ends_at="2026-10-14T17:00:00Z",
        terrain_grade="MEADOW",
        min_ability_rank="BEGINNER",
        capacity=6,
        rider_surcharge_cents=0,
        mount_required=False,
    )
    assign_guide(client, slot["id"], guide["id"], "LEAD")
    slot = get_success_data(client.get_activity_slot(slot["id"], RESERVATIONS_AGENT))
    seat = get_success_data(
        client.create_reservation(
            slot["id"],
            reservation_payload(booking["id"], ann["id"], slot["version"]),
            RESERVATIONS_AGENT,
        )
    )
    open_slot(client, slot["id"])
    set_clock_to(client, "2026-10-14T15:00:00Z")
    guide_headers = make_activity_guide_headers(guide["id"])
    slot = get_success_data(client.run_slot(slot["id"], guide_headers))
    return ann, seat, slot, guide_headers


class TestRiderCheckInBlockedByALapsedWaiver:
    """The corral turns away a rider whose signature ran out overnight."""

    def test_the_guide_cannot_check_in_a_rider_whose_waiver_has_lapsed(self, client):
        """The seat is sound and the ride is under way, and still she is refused.

        PRD: "A waiver that lapsed between booking and riding blocks the check-in
        with `ERR_WAIVER_NOT_SIGNED` even though the seat itself is perfectly
        valid."

        Design: Difficulty/cross_entity_state_dependency/seat_checkin_blocked_by_the_guests_expired_waiver_state
        """
        _ann, seat, _slot, guide_headers = _running_hike_whose_riders_waiver_has_lapsed(
            client
        )
        validate_error(
            client.check_in_reservation(seat["id"], guide_headers),
            ApiErrorId.ERR_WAIVER_NOT_SIGNED.value,
            409,
        )

    def test_the_waiver_lapsed_one_year_after_signature_with_no_write(self, client):
        """The signature of October 2025 expires a year on and the posture follows.

        PRD: "From the supplied signature date the system computes
        `waiver_expires_on` as that date plus 365 days, sets `waiver_signed_on`,
        records `equine_statute_ack`, clears any `waiver_revoked_at`, and
        increments the guest's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/seat_checkin_blocked_by_the_guests_expired_waiver_state
        """
        ann, seat, _slot, guide_headers = _running_hike_whose_riders_waiver_has_lapsed(
            client
        )
        validate_error(
            client.check_in_reservation(seat["id"], guide_headers),
            ApiErrorId.ERR_WAIVER_NOT_SIGNED.value,
            409,
        )
        guest = validate_success(client.get_guest(ann["id"], RESERVATIONS_AGENT))
        assertions.assert_guest(guest)
        assert guest["waiver_signed_on"] == "2025-10-13"
        assert guest["waiver_expires_on"] == "2026-10-13"
        assert guest["waiver_status"] == "EXPIRED"

    def test_the_refused_check_in_leaves_the_seat_and_the_ride_untouched(self, client):
        """Nothing is stamped on the seat, and the ride carries on without her.

        PRD: "The seat must be `CONFIRMED`, its slot must be `RUNNING`, the
        guest's resolved `waiver_status` must still be `SIGNED` with
        `equine_statute_ack` true, the guest's `guest_standing` must not be
        `SUSPENDED`, and the seat's `mount_status` must be `NOT_REQUIRED` or
        `ASSIGNED` — a rider whose horse was released by a health cascade cannot
        mount up."

        Design: Difficulty/cross_entity_state_dependency/seat_checkin_blocked_by_the_guests_expired_waiver_state
        """
        _ann, seat, slot, guide_headers = _running_hike_whose_riders_waiver_has_lapsed(
            client
        )
        validate_error(
            client.check_in_reservation(seat["id"], guide_headers),
            ApiErrorId.ERR_WAIVER_NOT_SIGNED.value,
            409,
        )
        after = validate_success(client.get_reservation(seat["id"], RESERVATIONS_AGENT))
        assertions.assert_activity_reservation(after)
        assert after["reservation_status"] == "CONFIRMED"
        assert after["checked_in_at"] is None

        slot_after = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert slot_after["slot_status"] == "RUNNING"


def _cabin_left_in_turnover_by_the_departing_party(client):
    """Back-to-back weekly parties sharing one cabin, the first just departed."""
    season = build_in_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
    ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
    cal = build_guest(client, "Cal Child", "2016-05-20", 95)
    dee = build_guest(client, "Dee Adult", "1990-01-15", 175)
    eli = build_guest(client, "Eli Adult", "1988-06-05", 180)
    fay = build_guest(client, "Fay Child", "2015-03-03", 90)

    bookings = []
    for members, arrival, departure in (
        (
            [
                party_member(ann["id"], "ADULT"),
                party_member(ben["id"], "ADULT"),
                party_member(cal["id"], "CHILD"),
            ],
            "2026-10-04",
            "2026-10-11",
        ),
        (
            [
                party_member(dee["id"], "ADULT"),
                party_member(eli["id"], "ADULT"),
                party_member(fay["id"], "CHILD"),
            ],
            "2026-10-11",
            "2026-10-18",
        ),
    ):
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            members,
            package_tier_code="CLASSIC",
            arrival_date=arrival,
            departure_date=departure,
        )
        get_success_data(
            client.post_payment(
                booking["id"],
                payment_payload(DEPOSIT_CENTS, "DEPOSIT"),
                RESERVATIONS_AGENT,
            )
        )
        bookings.append(confirm_booking(client, booking["id"]))

    booking_a, booking_b = bookings
    set_clock_to(client, "2026-10-04T16:00:00Z")
    get_success_data(
        client.check_in_booking(booking_a["id"], check_in_payload(True), RESERVATIONS_AGENT)
    )
    set_clock_to(client, "2026-10-11T10:00:00Z")
    departed = get_success_data(
        client.check_out_booking(
            booking_a["id"], check_out_payload(1107648), RESERVATIONS_AGENT
        )
    )
    return season, cabin, departed, booking_b


class TestPartyArrivalBlockedByTheCabinsTurnover:
    """The next party waits on housekeeping, not on their own paperwork."""

    def test_the_departing_party_leaves_the_cabin_awaiting_housekeeping(self, client):
        """Check-out re-prices the week and hands the cabin to housekeeping.

        PRD: "When the party checks out, the cabin moves `OCCUPIED → TURNOVER`
        and the season's `in_house_guest_count` falls by the same size."

        Design: Difficulty/cross_entity_state_dependency/booking_checkin_blocked_by_the_cabins_turnover_state
        """
        _season, cabin, departed, _booking_b = _cabin_left_in_turnover_by_the_departing_party(
            client
        )
        assertions.assert_booking(departed)
        assert departed["booking_status"] == "CHECKED_OUT"
        assert departed["realized_nights"] == 7
        assert departed["final_folio_total_cents"] == 1485255

        cabin_after = validate_success(client.get_cabin(cabin["id"], RANCH_MANAGER))
        assertions.assert_cabin(cabin_after)
        assert cabin_after["cabin_status"] == "TURNOVER"

    def test_the_arriving_party_is_turned_away_while_the_cabin_is_in_turnover(self, client):
        """A flawless confirmed stay still cannot walk into an uncleaned cabin.

        PRD: "Attempting to check a party into a cabin that is not `READY` —
        because it is still `OCCUPIED`, awaiting turnover, or out of service — is
        refused with `ERR_CABIN_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/booking_checkin_blocked_by_the_cabins_turnover_state
        """
        _season, _cabin, _departed, booking_b = _cabin_left_in_turnover_by_the_departing_party(
            client
        )
        validate_error(
            client.check_in_booking(
                booking_b["id"], check_in_payload(True), RESERVATIONS_AGENT
            ),
            ApiErrorId.ERR_CABIN_NOT_READY.value,
            409,
        )
        unchanged = validate_success(client.get_booking(booking_b["id"], RESERVATIONS_AGENT))
        assert unchanged["booking_status"] == "CONFIRMED"
        assert unchanged["checked_in_at"] is None

    def test_reporting_the_turnover_finished_lets_the_same_arrival_through(self, client):
        """Housekeeping clears the cabin and the identical request now succeeds.

        PRD: "A cabin in `TURNOVER` is not available to the next party until
        housekeeping reports the turnover finished, which moves it `TURNOVER →
        READY` and stamps `last_turnover_completed_at` with the logical clock
        instant."

        Design: Difficulty/cross_entity_state_dependency/booking_checkin_blocked_by_the_cabins_turnover_state
        """
        season, cabin, _departed, booking_b = _cabin_left_in_turnover_by_the_departing_party(
            client
        )
        validate_error(
            client.check_in_booking(
                booking_b["id"], check_in_payload(True), RESERVATIONS_AGENT
            ),
            ApiErrorId.ERR_CABIN_NOT_READY.value,
            409,
        )
        cleared = validate_success(client.cabin_turnover_complete(cabin["id"], RANCH_MANAGER))
        assert cleared["cabin_status"] == "READY"
        assertions.assert_instant_equals(
            cleared["last_turnover_completed_at"],
            "2026-10-11T10:00:00Z",
            "last_turnover_completed_at",
        )

        arrived = validate_success(
            client.check_in_booking(
                booking_b["id"], check_in_payload(True), RESERVATIONS_AGENT
            )
        )
        assert arrived["booking_status"] == "CHECKED_IN"

        cabin_after = validate_success(client.get_cabin(cabin["id"], RANCH_MANAGER))
        assert cabin_after["cabin_status"] == "OCCUPIED"
        assertions.assert_instant_equals(
            cabin_after["last_turnover_completed_at"],
            "2026-10-11T10:00:00Z",
            "last_turnover_completed_at",
        )

        season_after = validate_success(client.get_season(season["id"], RANCH_MANAGER))
        assert season_after["in_house_guest_count"] == 3
