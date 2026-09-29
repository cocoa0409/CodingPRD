"""State dimensions that do not advance in a single straight line.

A booking carries an occupancy dimension and a money dimension that move
independently, and a horse's health status is cyclic rather than forward-only.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions
from test_helpers.factories import health_event_payload, party_member, payment_payload
from test_helpers.fixtures import (
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_open_season,
    confirm_booking,
    set_clock_to,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RESERVATIONS_AGENT,
)

DEPOSIT_CENTS = 377607


def _confirmed_booking_seventy_one_days_out(client):
    """A deposit-paid stay whose arrival is 71 days after the startup clock."""
    season = build_open_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
    ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
    cal = build_guest(client, "Cal Child", "2016-05-20", 95)
    booking = build_booking(
        client,
        season["id"],
        cabin["id"],
        [
            party_member(ann["id"], "ADULT"),
            party_member(ben["id"], "ADULT"),
            party_member(cal["id"], "CHILD"),
        ],
        package_tier_code="CLASSIC",
        arrival_date="2026-10-11",
        departure_date="2026-10-18",
    )
    get_success_data(
        client.post_payment(
            booking["id"], payment_payload(DEPOSIT_CENTS, "DEPOSIT"), RESERVATIONS_AGENT
        )
    )
    booking = confirm_booking(client, booking["id"])
    assert booking["payment_status"] == "DEPOSIT_PAID"
    return booking


class TestBookingCarriesTwoIndependentDimensions:
    """One cancel call moves occupancy and money to unrelated terminal values."""

    def test_cancelling_a_paid_hold_lands_on_cancelled_and_partially_refunded(self, client):
        """Occupancy goes terminal while money lands on a mid-band refund value.

        PRD: "The money dimension of a booking, `payment_status`, is entirely
        independent of its occupancy dimension: it starts at
        `AWAITING_DEPOSIT`, and the moment `deposit_paid_cents` reaches or
        passes `deposit_required_cents` it moves `AWAITING_DEPOSIT →
        DEPOSIT_PAID`."

        Design: Difficulty/non_linear_state_machine/booking_status_and_payment_status_dimensions_move_independently_on_cancel
        """
        booking = _confirmed_booking_seventy_one_days_out(client)
        cancelled = validate_success(
            client.cancel_booking(booking["id"], "guest schedule change", RESERVATIONS_AGENT)
        )
        assertions.assert_booking(cancelled)
        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "PARTIALLY_REFUNDED"
        assertions.assert_instant_equals(
            cancelled["cancelled_at"], "2026-08-01T00:00:00Z", "cancelled_at"
        )

    def test_the_mid_band_split_conserves_the_whole_deposit(self, client):
        """A 0.50 band splits 377607 cents into 188804 refunded and 188803 forfeited.

        PRD: "Because the forfeit is defined as the remainder rather than
        computed independently, `refunded_cents` and `forfeited_cents` always
        sum to exactly `deposit_paid_cents`, at every band, without exception."

        Design: Difficulty/non_linear_state_machine/booking_status_and_payment_status_dimensions_move_independently_on_cancel
        """
        booking = _confirmed_booking_seventy_one_days_out(client)
        cancelled = validate_success(
            client.cancel_booking(booking["id"], "guest schedule change", RESERVATIONS_AGENT)
        )
        assert float(cancelled["cancellation_refund_pct"]) == 0.50
        assert cancelled["refunded_cents"] == 188804
        assert cancelled["forfeited_cents"] == 188803
        assert cancelled["refunded_cents"] + cancelled["forfeited_cents"] == DEPOSIT_CENTS
        assertions.assert_cancellation_split_is_conservative(cancelled)


def _walk_a_horse_through_lameness_and_back(client):
    """File lameness, then rehab, then veterinary clearance on the same animal."""
    animal = build_horse(
        client,
        name="Comet",
        min_rider_ability="BEGINNER",
        max_rider_ability="ADVANCED",
        weight_limit_lb=240,
    )
    assert animal["horse_status"] == "IN_SERVICE"

    set_clock_to(client, "2026-10-12T08:00:00Z")
    lameness = validate_success(
        client.create_health_event(
            animal["id"],
            health_event_payload("LAMENESS", "2026-10-12", "off on the left fore"),
            HORSE_PROGRAM_DIRECTOR,
        ),
        201,
    )
    set_clock_to(client, "2026-10-13T08:00:00Z")
    rehab = validate_success(
        client.create_health_event(
            animal["id"],
            health_event_payload("REHAB_START", "2026-10-13", "hand walking"),
            HORSE_PROGRAM_DIRECTOR,
        ),
        201,
    )
    set_clock_to(client, "2026-10-20T08:00:00Z")
    clearance = validate_success(
        client.create_health_event(
            animal["id"],
            health_event_payload("VET_CLEARANCE", "2026-10-20", "sound at trot"),
            HORSE_PROGRAM_DIRECTOR,
        ),
        201,
    )
    animal = validate_success(client.get_horse(animal["id"], HORSE_PROGRAM_DIRECTOR))
    return animal, lameness, rehab, clearance


class TestHorseHealthStatusIsCyclic:
    """IN_SERVICE is reached a second time by a different route than creation."""

    def test_clearance_returns_a_rehabilitating_horse_to_service(self, client):
        """Lameness, rehabilitation and clearance walk the animal back into the pool.

        PRD: "A `VET_CLEARANCE` event returns a horse from `REHAB` or from
        `REST` to `IN_SERVICE`, closing both the lameness cycle and the rest
        cycle so that the same animal may go in and out of service repeatedly
        across a season."

        Design: Difficulty/non_linear_state_machine/horse_status_cycles_in_service_lame_rehab_back_to_in_service
        """
        animal, lameness, rehab, clearance = _walk_a_horse_through_lameness_and_back(client)
        assert lameness["resulting_horse_status"] == "LAME"
        assert rehab["resulting_horse_status"] == "REHAB"
        assert clearance["resulting_horse_status"] == "IN_SERVICE"
        assertions.assert_horse(animal)
        assert animal["horse_status"] == "IN_SERVICE"
        assertions.assert_horse_load(
            animal, scheduled_load_hours=0.0, consecutive_duty_days=0
        )

    def test_the_health_log_keeps_all_three_rows_without_a_version_counter(self, client):
        """Every care record survives the cycle and none of them is versioned.

        PRD: "Health events are the one record type on the ranch that carries no
        version counter and no modification timestamp — only an identifier and a
        creation instant — precisely because nothing may ever change them."

        Design: Difficulty/non_linear_state_machine/horse_status_cycles_in_service_lame_rehab_back_to_in_service
        """
        animal, _lameness, _rehab, _clearance = _walk_a_horse_through_lameness_and_back(client)
        rows, _meta = validate_paginated(
            client.list_health_events(
                HORSE_PROGRAM_DIRECTOR, {"horse_id": animal["id"]}
            )
        )
        assert len(rows) == 3
        recorded = [row["resulting_horse_status"] for row in rows]
        assert sorted(recorded) == ["IN_SERVICE", "LAME", "REHAB"]
        for row in rows:
            assertions.assert_horse_health_event(row)
