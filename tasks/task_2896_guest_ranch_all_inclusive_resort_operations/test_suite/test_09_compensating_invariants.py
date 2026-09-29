"""Paired writes that must return a running total to its exact prior value.

A damage charge is waived on a closed folio, and a horse handed back before the
ride gives up exactly the hours it was booked for.
"""
from prd_bench_local_runner.testing import (
    assert_version_incremented,
    get_success_data,
    validate_success,
)

from test_helpers import assertions
from test_helpers.factories import (
    check_in_payload,
    check_out_payload,
    folio_adjustment_payload,
    mount_assignment_payload,
    party_member,
    payment_payload,
)
from test_helpers.fixtures import (
    build_activity_slot,
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_in_season,
    build_open_season,
    build_ready_rider,
    confirm_booking,
    set_clock_to,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
)

DEPOSIT_CENTS = 377607
SETTLEMENT_CENTS = 1107648
CLOSED_FOLIO_TOTAL_CENTS = 1485255
CLOSED_GRATUITY_CENTS = 226564
ADJUSTMENT_CENTS = 50000


def _departed_party_with_a_closed_folio(client):
    """A family of three who arrived, took no rides, and settled in full."""
    season = build_in_season(client)
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
    confirm_booking(client, booking["id"])
    set_clock_to(client, "2026-10-11T16:00:00Z")
    get_success_data(
        client.check_in_booking(booking["id"], check_in_payload(True), RESERVATIONS_AGENT)
    )
    set_clock_to(client, "2026-10-18T10:00:00Z")
    departed = get_success_data(
        client.check_out_booking(
            booking["id"], check_out_payload(SETTLEMENT_CENTS), RESERVATIONS_AGENT
        )
    )
    return departed


class TestPairedFolioAdjustmentsCancelOut:
    """A charge and its reversal leave the closed folio exactly as it was."""

    def test_a_damage_charge_reopens_the_closed_folio_arithmetic(self, client):
        """The charge lands on the adjustment total and on the balance at once.

        PRD: "Each accepted adjustment adds its amount to
        `folio_adjustment_total_cents` and increments the booking's `version` by
        1; when the booking has already reached `CHECKED_OUT`,
        `final_folio_total_cents` and `folio_balance_cents` are recomputed on the
        spot so the closed folio stays arithmetically true."

        Design: Difficulty/compensating_invariant/paired_folio_adjustments_restore_the_final_folio_total_exactly
        """
        departed = _departed_party_with_a_closed_folio(client)
        assert departed["final_folio_total_cents"] == CLOSED_FOLIO_TOTAL_CENTS
        assert departed["gratuity_cents"] == CLOSED_GRATUITY_CENTS

        pinned = validate_success(client.get_booking(departed["id"], RANCH_MANAGER))
        charged = validate_success(
            client.post_folio_adjustment(
                departed["id"],
                folio_adjustment_payload(
                    ADJUSTMENT_CENTS,
                    "broken tack repair charged to the folio",
                    pinned["version"],
                ),
                RANCH_MANAGER,
            )
        )
        assertions.assert_booking(charged)
        assert charged["folio_adjustment_total_cents"] == ADJUSTMENT_CENTS
        assert charged["final_folio_total_cents"] == 1535255
        assert charged["folio_balance_cents"] == ADJUSTMENT_CENTS
        assert_version_incremented(charged["version"], pinned["version"])

    def test_waiving_the_charge_restores_the_folio_without_touching_gratuity(self, client):
        """The credit reverses the charge to the cent and the tip never moves.

        PRD: "The base deliberately **excludes** activity surcharges, the applied
        credit, no-show penalties and manual adjustments."

        Design: Difficulty/compensating_invariant/paired_folio_adjustments_restore_the_final_folio_total_exactly
        """
        departed = _departed_party_with_a_closed_folio(client)
        first_pin = validate_success(client.get_booking(departed["id"], RANCH_MANAGER))
        get_success_data(
            client.post_folio_adjustment(
                departed["id"],
                folio_adjustment_payload(
                    ADJUSTMENT_CENTS,
                    "broken tack repair charged to the folio",
                    first_pin["version"],
                ),
                RANCH_MANAGER,
            )
        )
        second_pin = validate_success(client.get_booking(departed["id"], RANCH_MANAGER))
        assert second_pin["version"] == first_pin["version"] + 1

        waived = validate_success(
            client.post_folio_adjustment(
                departed["id"],
                folio_adjustment_payload(
                    -ADJUSTMENT_CENTS,
                    "tack damage waived, charge reversed",
                    second_pin["version"],
                ),
                RANCH_MANAGER,
            )
        )
        assert waived["folio_adjustment_total_cents"] == 0
        assert waived["final_folio_total_cents"] == CLOSED_FOLIO_TOTAL_CENTS
        assert waived["folio_balance_cents"] == 0
        assert waived["gratuity_cents"] == CLOSED_GRATUITY_CENTS
        assertions.assert_folio_waterfall_consistent(waived)
        assertions.assert_folio_balance_consistent(waived)


def _comet_booked_on_a_two_hour_ride(client):
    """One beginner seated on a mounted meadow ride with Comet in hand."""
    season = build_open_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, "BEGINNER")
    booking = build_booking(
        client,
        season["id"],
        cabin["id"],
        [party_member(ann["id"], "ADULT")],
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
    slot = build_activity_slot(
        client,
        season["id"],
        activity_type="TRAIL_RIDE",
        starts_at="2026-10-12T15:00:00Z",
        ends_at="2026-10-12T17:00:00Z",
        terrain_grade="MEADOW",
        min_ability_rank="BEGINNER",
        capacity=4,
        rider_surcharge_cents=20000,
        mount_required=True,
    )
    seat = take_seat(client, slot["id"], booking["id"], ann["id"])
    before = get_success_data(client.get_horse(animal["id"], HORSE_PROGRAM_DIRECTOR))
    get_success_data(
        client.assign_mount(
            seat["id"],
            mount_assignment_payload(animal["id"], before["version"]),
            HORSE_PROGRAM_DIRECTOR,
        )
    )
    return animal, slot, seat, before


class TestMountReleaseGivesBackExactlyTheHoursBooked:
    """The animal's scheduled duty returns to the figure it started from."""

    def test_releasing_the_mount_returns_the_scheduled_hours_to_zero(self, client):
        """Two booked hours go on and, when the horse is handed back, come off.

        PRD: "The release moves `mount_status` to `RELEASED`, clears
        `assigned_horse_id`, raises `mount_release_count` by 1, subtracts the
        slot's `duration_hours` from the horse's `scheduled_load_hours` —
        returning that figure to exactly the value it held before the assignment,
        never an approximation of it — lowers the slot's `mount_assigned_count` by
        1, recomputes `readiness_posture` so that an `OPEN` slot which became
        `MOUNT_SHORT` drops to `HOLD`, and increments both the horse's and the
        slot's `version` by 1 each."

        Design: Difficulty/compensating_invariant/mount_release_returns_the_horses_scheduled_hours_to_zero
        """
        animal, slot, seat, before = _comet_booked_on_a_two_hour_ride(client)
        assertions.assert_horse_load(before, scheduled_load_hours=0.0)
        loaded = validate_success(client.get_horse(animal["id"], HORSE_PROGRAM_DIRECTOR))
        assertions.assert_horse_load(loaded, scheduled_load_hours=2.0)

        validate_success(
            client.release_mount(
                seat["id"],
                "swapping the string for a shoeing appointment",
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        after = validate_success(client.get_horse(animal["id"], HORSE_PROGRAM_DIRECTOR))
        assertions.assert_horse(after)
        assertions.assert_horse_load(
            after,
            scheduled_load_hours=0.0,
            realized_load_hours=0.0,
            consecutive_duty_days=0,
        )

        slot_after = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assertions.assert_slot_counters(
            slot_after, mount_assigned_count=0, confirmed_rider_count=1
        )

    def test_the_released_seat_keeps_its_place_and_counts_the_release(self, client):
        """The rider stays on the roster, waiting for another animal.

        PRD: "A released seat may be mounted again, possibly on a different
        animal, and the cycle from `ASSIGNED` to `RELEASED` and back may repeat
        any number of times while the slot is `DRAFT`, `OPEN` or `HOLD`."

        Design: Difficulty/compensating_invariant/mount_release_returns_the_horses_scheduled_hours_to_zero
        """
        _animal, _slot, seat, _before = _comet_booked_on_a_two_hour_ride(client)
        validate_success(
            client.release_mount(
                seat["id"],
                "swapping the string for a shoeing appointment",
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        after = validate_success(client.get_reservation(seat["id"], RESERVATIONS_AGENT))
        assertions.assert_activity_reservation(after)
        assert after["mount_status"] == "RELEASED"
        assert after["assigned_horse_id"] is None
        assert after["mount_release_count"] == 1
        assert after["reservation_status"] == "CONFIRMED"
