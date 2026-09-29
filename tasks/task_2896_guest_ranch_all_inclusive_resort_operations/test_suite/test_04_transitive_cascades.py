"""Single writes that must reach three and four levels down the ranch.

A herd-health filing, a stay cancellation and a payroll separation each touch
one aggregate and are required to move several others in the same request.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions
from test_helpers.factories import (
    health_event_payload,
    onboard_payload,
    party_member,
    payment_payload,
)
from test_helpers.fixtures import (
    assign_guide,
    attach_mount,
    build_activity_slot,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_open_season,
    build_ready_rider,
    build_staff_member,
    confirm_booking,
    open_slot,
    set_clock_to,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
)

DEPOSIT_CENTS = 377607
SURCHARGE_CENTS = 20000


def _opened_mounted_ride(client):
    """An open trail ride with one mounted beginner rider off a confirmed stay."""
    season = build_open_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, "BEGINNER")
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

    guide = build_active_guide(client, season["id"], full_name="Gus Guide")
    animal = build_horse(client, name="Comet")
    slot = build_activity_slot(
        client,
        season["id"],
        activity_type="TRAIL_RIDE",
        starts_at="2026-10-12T15:00:00Z",
        ends_at="2026-10-12T17:00:00Z",
        terrain_grade="MEADOW",
        min_ability_rank="BEGINNER",
        capacity=4,
        rider_surcharge_cents=SURCHARGE_CENTS,
        mount_required=True,
    )
    guide_assignment = assign_guide(client, slot["id"], guide["id"], "LEAD")
    seat = take_seat(client, slot["id"], booking["id"], ann["id"])
    attach_mount(client, seat["id"], animal["id"])
    slot = open_slot(client, slot["id"])
    assertions.assert_readiness_posture(slot, "STAFFED_READY")
    assert slot["slot_status"] == "OPEN"
    return {
        "season": season,
        "booking": booking,
        "guide": guide,
        "guide_assignment": guide_assignment,
        "horse": animal,
        "slot": slot,
        "seat": seat,
        "rider": ann,
    }


class TestLamenessCascadesToTheSlot:
    """One health filing reaches the horse, the seat, the counters and the slot."""

    def test_lameness_releases_the_mount_and_returns_the_scheduled_hours(self, client):
        """The animal goes lame, its seat loses the mount, its hours come back.

        PRD: "Second, because the animal is no longer available, every activity
        seat that holds it — every reservation whose `assigned_horse_id` is this
        horse, whose `mount_status` is `ASSIGNED`, and whose slot has not yet
        started according to the logical clock — moves `mount_status` to
        `RELEASED`, clears `assigned_horse_id` and raises `mount_release_count`
        by 1."

        Design: Difficulty/transitive_cascade/lameness_event_cascades_four_levels_to_slot_hold
        """
        fixture = _opened_mounted_ride(client)
        validate_success(
            client.create_health_event(
                fixture["horse"]["id"],
                health_event_payload(
                    "LAMENESS", "2026-08-01", "acute lameness on morning check"
                ),
                HORSE_PROGRAM_DIRECTOR,
            ),
            201,
        )
        animal = validate_success(
            client.get_horse(fixture["horse"]["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert animal["horse_status"] == "LAME"
        assertions.assert_horse_load(animal, scheduled_load_hours=0.0)

        seat = validate_success(
            client.get_reservation(fixture["seat"]["id"], RESERVATIONS_AGENT)
        )
        assert seat["mount_status"] == "RELEASED"
        assert seat["assigned_horse_id"] is None
        assert seat["mount_release_count"] == 1
        assert seat["reservation_status"] == "CONFIRMED"

    def test_lameness_pushes_the_open_slot_onto_a_mount_short_hold(self, client):
        """The slot recounts its mounts and takes itself off the sale board.

        PRD: "Fourth, because the posture degraded, each such slot that was
        `OPEN` transitions to `HOLD` with `hold_reason` of `MOUNT_SHORT`."

        Design: Difficulty/transitive_cascade/lameness_event_cascades_four_levels_to_slot_hold
        """
        fixture = _opened_mounted_ride(client)
        validate_success(
            client.create_health_event(
                fixture["horse"]["id"],
                health_event_payload(
                    "LAMENESS", "2026-08-01", "acute lameness on morning check"
                ),
                HORSE_PROGRAM_DIRECTOR,
            ),
            201,
        )
        slot = validate_success(
            client.get_activity_slot(fixture["slot"]["id"], RANCH_MANAGER)
        )
        assertions.assert_activity_slot(slot)
        assertions.assert_slot_counters(
            slot, confirmed_rider_count=1, mount_assigned_count=0
        )
        assertions.assert_readiness_posture(slot, "MOUNT_SHORT")
        assert slot["slot_status"] == "HOLD"
        assert slot["hold_reason"] == "MOUNT_SHORT"


class TestBookingCancelCascadesToTheSlot:
    """Cancelling the parent stay unwinds the seat, the mount and the counters."""

    def test_cancelling_the_stay_reverses_the_seat_surcharge_and_the_mount(self, client):
        """The seat is cancelled, its surcharge reversed and the horse handed back.

        PRD: "Because the booking is `CANCELLED`, every activity seat of the
        booking whose `reservation_status` is `CONFIRMED` or `CHECKED_IN`
        becomes `CANCELLED` with `surcharge_reversed_cents` set to that seat's
        own `surcharge_cents`, which returns the booking's
        `activity_surcharge_total_cents` to the value it held before those seats
        existed."

        Design: Difficulty/transitive_cascade/booking_cancel_cascades_three_levels_to_slot_recount_and_surcharge_reversal
        """
        fixture = _opened_mounted_ride(client)
        before = validate_success(
            client.get_booking(fixture["booking"]["id"], RESERVATIONS_AGENT)
        )
        assert before["activity_surcharge_total_cents"] == SURCHARGE_CENTS

        cancelled = validate_success(
            client.cancel_booking(
                fixture["booking"]["id"], "family emergency at home", RANCH_MANAGER
            )
        )
        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["activity_surcharge_total_cents"] == 0
        assert cancelled["refunded_cents"] == 188804
        assert cancelled["forfeited_cents"] == 188803

        seat = validate_success(
            client.get_reservation(fixture["seat"]["id"], RESERVATIONS_AGENT)
        )
        assert seat["reservation_status"] == "CANCELLED"
        assert seat["surcharge_reversed_cents"] == SURCHARGE_CENTS
        assert seat["mount_status"] == "RELEASED"

        animal = validate_success(
            client.get_horse(fixture["horse"]["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assertions.assert_horse_load(animal, scheduled_load_hours=0.0)

    def test_cancelling_the_stay_returns_the_slot_to_its_pre_seat_counters(self, client):
        """With the last rider gone the slot is staffed-ready and stays open.

        PRD: "And because those seats have left `CONFIRMED`, each parent slot
        recomputes `confirmed_rider_count`, `minor_rider_count`,
        `mount_assigned_count`, `required_guide_count`, `seats_available` and
        `readiness_posture`, with any slot that was `OPEN` and whose posture has
        degraded to `UNDERSTAFFED` or `MOUNT_SHORT` moving to `HOLD` and
        recording the matching `hold_reason`."

        Design: Difficulty/transitive_cascade/booking_cancel_cascades_three_levels_to_slot_recount_and_surcharge_reversal
        """
        fixture = _opened_mounted_ride(client)
        validate_success(
            client.cancel_booking(
                fixture["booking"]["id"], "family emergency at home", RANCH_MANAGER
            )
        )
        slot = validate_success(
            client.get_activity_slot(fixture["slot"]["id"], RANCH_MANAGER)
        )
        assertions.assert_slot_counters(
            slot,
            confirmed_rider_count=0,
            mount_assigned_count=0,
            seats_available=4,
            required_guide_count=0,
        )
        assertions.assert_readiness_posture(slot, "STAFFED_READY")
        assert slot["slot_status"] == "OPEN"


def _opened_hike_with_a_single_guide(client):
    """An open unmounted hike whose one rider is covered by exactly one guide."""
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
    staff = build_staff_member(
        client,
        season["id"],
        full_name="Gus Guide",
        role_type="GUIDE",
        certifications=["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"],
        hired_on="2026-08-15",
        contract_end_date="2026-11-15",
    )
    set_clock_to(client, "2026-08-15T09:00:00Z")
    staff = get_success_data(
        client.onboard_staff_member(
            staff["id"],
            onboard_payload("BUNKHOUSE-A", 3),
            RANCH_MANAGER,
        )
    )
    slot = build_activity_slot(
        client,
        season["id"],
        activity_type="HIKE",
        starts_at="2026-10-12T15:00:00Z",
        ends_at="2026-10-12T17:00:00Z",
        terrain_grade="MEADOW",
        min_ability_rank="BEGINNER",
        capacity=6,
        rider_surcharge_cents=0,
        mount_required=False,
    )
    guide_assignment = assign_guide(client, slot["id"], staff["id"], "LEAD")
    seat = take_seat(client, slot["id"], booking["id"], ann["id"])
    slot = open_slot(client, slot["id"])
    assertions.assert_readiness_posture(slot, "STAFFED_READY")
    return {
        "season": season,
        "booking": booking,
        "staff": staff,
        "guide_assignment": guide_assignment,
        "slot": slot,
        "seat": seat,
    }


class TestStaffSeparationCascadesToTheSlot:
    """A payroll write strips the slot of its guide and forces a hold."""

    def test_separation_releases_the_guides_scheduled_duty(self, client):
        """The departing guide is cleared of duty and of scheduled hours.

        PRD: "Second, because the person has left, every guide assignment of
        theirs still in `SCHEDULED` becomes `RELEASED` and their
        `scheduled_guide_hours` drops to 0."

        Design: Difficulty/transitive_cascade/staff_separation_cascades_three_levels_to_slot_understaffed_hold
        """
        fixture = _opened_hike_with_a_single_guide(client)
        separated = validate_success(
            client.separate_staff_member(
                fixture["staff"]["id"], "left for a winter job", RANCH_MANAGER
            )
        )
        assertions.assert_staff_member(separated)
        assert separated["employment_status"] == "DEPARTED_EARLY"
        assert separated["days_worked"] == 0
        assert separated["retention_bonus_settled_cents"] == 0
        assert float(separated["scheduled_guide_hours"]) == 0.0

        assignment = validate_success(
            client.get_guide_assignment(
                fixture["guide_assignment"]["id"], RANCH_MANAGER
            )
        )
        assertions.assert_guide_assignment(assignment)
        assert assignment["assignment_status"] == "RELEASED"

    def test_separation_pushes_the_open_slot_onto_an_understaffed_hold(self, client):
        """The rider keeps the seat while the slot loses its right to sell more.

        PRD: "Third, because those guides were released, each affected slot
        recomputes `assigned_guide_count` and `readiness_posture`, and an `OPEN`
        slot whose posture became `UNDERSTAFFED` transitions to `HOLD` with
        `hold_reason` of `UNDERSTAFFED`."

        Design: Difficulty/transitive_cascade/staff_separation_cascades_three_levels_to_slot_understaffed_hold
        """
        fixture = _opened_hike_with_a_single_guide(client)
        validate_success(
            client.separate_staff_member(
                fixture["staff"]["id"], "left for a winter job", RANCH_MANAGER
            )
        )
        slot = validate_success(
            client.get_activity_slot(fixture["slot"]["id"], RANCH_MANAGER)
        )
        assertions.assert_slot_counters(
            slot, assigned_guide_count=0, required_guide_count=1
        )
        assertions.assert_readiness_posture(slot, "UNDERSTAFFED")
        assert slot["slot_status"] == "HOLD"
        assert slot["hold_reason"] == "UNDERSTAFFED"

        seat = validate_success(
            client.get_reservation(fixture["seat"]["id"], RESERVATIONS_AGENT)
        )
        assert seat["reservation_status"] == "CONFIRMED"
        assert seat["mount_status"] == "NOT_REQUIRED"
