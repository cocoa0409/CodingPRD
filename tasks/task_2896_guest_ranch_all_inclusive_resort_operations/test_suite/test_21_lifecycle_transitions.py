"""Lifecycle transitions: initial states, guarded steps, terminal locks and cascades.

This module walks the ranch's state machines: the season's forward march, the
booking's two independent dimensions, the slot's staffing and start guards, the
assessment's re-evaluation loop, and the fan-out a single request performs
across seats, mounts, guides, horses, cabins and folios.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import assertions, constants
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    check_in_payload,
    complete_slot_payload,
    dispose_payload,
    evaluate_assessment_payload,
    incident_report_payload,
    party_member,
    rider_assessment_payload,
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
    build_in_season,
    build_open_season,
    build_season,
    build_staff_member,
    confirm_booking,
    open_slot,
    pay_deposit,
    set_clock_to,
    sign_guest_waiver,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
    SAFETY_OFFICER,
    SAFETY_OFFICER_ONE_USER_ID,
    make_activity_guide_headers,
)

HIKE_SLOT = {
    "activity_type": "HIKE",
    "terrain_grade": "ROLLING",
    "min_ability_rank": "UNASSESSED",
    "capacity": 4,
    "rider_surcharge_cents": 0,
    "mount_required": False,
}


def open_assessment(client, guest_id, requested_ability):
    """Open an ability assessment, pinning the guest version read just now."""
    guest = get_success_data(client.get_guest(guest_id, HORSE_PROGRAM_DIRECTOR))
    return get_success_data(
        client.create_rider_assessment(
            guest_id,
            rider_assessment_payload(requested_ability, guest["version"]),
            HORSE_PROGRAM_DIRECTOR,
        )
    )


def evaluate_assessment(client, assessment_id, ability, note, evaluated_at):
    """Record the arena verdict on an assessment."""
    return get_success_data(
        client.evaluate_rider_assessment(
            assessment_id,
            evaluate_assessment_payload(ability, note, evaluated_at),
            HORSE_PROGRAM_DIRECTOR,
        )
    )


def build_assessed_rider(client, full_name, birth_date, weight_lb, ability):
    """A guest with a live waiver and an evaluated ability rank."""
    guest = build_guest(client, full_name, birth_date, weight_lb)
    sign_guest_waiver(client, guest["id"], "2026-08-01", True)
    assessment = open_assessment(client, guest["id"], ability)
    evaluate_assessment(
        client, assessment["id"], ability, "balanced at all three gaits", "2026-08-01T12:00:00Z"
    )
    return get_success_data(client.get_guest(guest["id"], RESERVATIONS_AGENT))


class TestInitialStates:
    """Every row lands in its declared starting state."""

    def test_newly_created_rows_start_in_their_declared_initial_states(self, client):
        """A held stay, a draft slot, a hired guide, a ready cabin and a fresh guest agree.

        PRD: "A new booking is created with `booking_status` of `HELD`, `payment_status` of `AWAITING_DEPOSIT`, `dietary_briefing_ack` false, `no_show_count` and every money counter at 0, `realized_nights` at 0, and `checked_in_at`, `checked_out_at` and `cancelled_at` all null."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        horse_row = build_horse(client, "Comet", "BEGINNER", "ADVANCED", 240)
        staff = build_staff_member(client, season["id"], full_name="Gus Guide")
        slot = build_activity_slot(client, season["id"])

        booking = validate_success(
            client.create_booking(
                {
                    "season_id": season["id"],
                    "cabin_id": cabin["id"],
                    "lead_guest_id": guest["id"],
                    "package_tier_code": "CLASSIC",
                    "arrival_date": constants.ARRIVAL_DATE,
                    "departure_date": constants.DEPARTURE_DATE,
                    "party_members": [party_member(guest["id"], "ADULT")],
                },
                RESERVATIONS_AGENT,
            ),
            201,
        )

        assertions.assert_booking(booking)
        assert booking["booking_status"] == "HELD"
        assert booking["payment_status"] == "AWAITING_DEPOSIT"
        assert booking["dietary_briefing_ack"] is False
        assert booking["no_show_count"] == 0
        assert booking["checked_in_at"] is None
        assert booking["checked_out_at"] is None
        assert booking["cancelled_at"] is None

        stored_slot = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert stored_slot["slot_status"] == "DRAFT"
        assertions.assert_readiness_posture(stored_slot, "STAFFED_READY")

        stored_staff = validate_success(client.get_staff_member(staff["id"], RANCH_MANAGER))
        assert stored_staff["employment_status"] == "HIRED"

        stored_horse = validate_success(client.get_horse(horse_row["id"], HORSE_PROGRAM_DIRECTOR))
        assert stored_horse["horse_status"] == "IN_SERVICE"

        stored_cabin = validate_success(client.get_cabin(cabin["id"], RANCH_MANAGER))
        assert stored_cabin["cabin_status"] == "READY"

        stored_guest = validate_success(client.get_guest(guest["id"], RESERVATIONS_AGENT))
        assert stored_guest["guest_standing"] == "GOOD"
        assert stored_guest["waiver_status"] == "NONE"


class TestSeasonLifecycle:
    """The season marches forward one declared step at a time."""

    def test_season_advances_planning_to_open_to_in_season(self, client):
        """Two separate advance requests carry the season from planning into season.

        PRD: "A `RanchManager` names the next status in `target_status`, and only four steps exist: `PLANNING → OPEN`, `OPEN → IN_SEASON`, `IN_SEASON → CLOSED` and `CLOSED → OFF_SEASON`."

        Design: Corner/state_machines/season_advances_planning_to_open_to_in_season
        """
        season = build_season(client)
        assert season["season_status"] == "PLANNING"

        opened = validate_success(
            client.advance_season(season["id"], "OPEN", RANCH_MANAGER), 200
        )
        assert opened["season_status"] == "OPEN"

        in_season = validate_success(
            client.advance_season(season["id"], "IN_SEASON", RANCH_MANAGER), 200
        )
        assert in_season["season_status"] == "IN_SEASON"
        assert in_season["version"] == season["version"] + 2


class TestSlotStartGuards:
    """Starting a ride is gated by the slot's own status and by its season."""

    def test_draft_slot_cannot_be_run_before_it_opens(self, client):
        """A fully staffed draft ride past its start instant still refuses to start.

        PRD: "Four conditions gate the start: the slot must be `OPEN`, or `ERR_SLOT_STATE_INVALID`; the season must be `IN_SEASON`, or `ERR_SEASON_NOT_OPEN`; the logical clock must have reached the slot's `starts_at`, or `ERR_SLOT_NOT_STARTED`; and the posture must read `STAFFED_READY` — a shortfall of guides reports `ERR_GUIDE_RATIO_UNMET` and a mounted slot with fewer assigned mounts than confirmed riders reports `ERR_MOUNTS_INCOMPLETE`."

        Design: Corner/state_machines/draft_slot_cannot_be_run_before_it_opens
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        guide = build_active_guide(client, season["id"], full_name="Gus Guide")
        slot = build_activity_slot(client, season["id"], **HIKE_SLOT)
        assign_guide(client, slot["id"], guide["id"])
        set_clock_to(client, "2026-10-12T15:30:00Z")

        validate_error(
            client.run_slot(slot["id"], make_activity_guide_headers(guide["id"])),
            ApiErrorId.ERR_SLOT_STATE_INVALID.value,
            409,
        )

        stored = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert stored["slot_status"] == "DRAFT"
        assert stored["actual_started_at"] is None

    def test_slot_run_while_the_season_is_only_open_is_rejected(self, client):
        """A ready ride under a season that has not yet started cannot depart.

        PRD: "Four conditions gate the start: the slot must be `OPEN`, or `ERR_SLOT_STATE_INVALID`; the season must be `IN_SEASON`, or `ERR_SEASON_NOT_OPEN`; the logical clock must have reached the slot's `starts_at`, or `ERR_SLOT_NOT_STARTED`; and the posture must read `STAFFED_READY` — a shortfall of guides reports `ERR_GUIDE_RATIO_UNMET` and a mounted slot with fewer assigned mounts than confirmed riders reports `ERR_MOUNTS_INCOMPLETE`."

        Design: Corner/state_machines/slot_run_while_the_season_is_only_open_is_rejected
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        guide = build_active_guide(
            client, season["id"], full_name="Gus Guide", certifications=["WILDERNESS_FIRST_AID"]
        )
        slot = build_activity_slot(client, season["id"], **HIKE_SLOT)
        assign_guide(client, slot["id"], guide["id"])

        opened = validate_success(client.open_slot(slot["id"], RANCH_MANAGER))
        assertions.assert_readiness_posture(opened, "STAFFED_READY")

        set_clock_to(client, "2026-10-12T15:30:00Z")
        validate_error(
            client.run_slot(slot["id"], make_activity_guide_headers(guide["id"])),
            ApiErrorId.ERR_SEASON_NOT_OPEN.value,
            409,
        )

        stored = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert stored["slot_status"] == "OPEN"

    def test_slot_open_with_zero_guides_is_rejected(self, client):
        """An unstaffed ride cannot be published even when it needs no guides yet.

        PRD: "Opening requires the governing season to be `OPEN` or `IN_SEASON`, or the request is refused with `ERR_SEASON_NOT_OPEN`; it requires at least one guide already assigned; and it requires `assigned_guide_count` to have reached `required_guide_count`, or the request is refused with `ERR_GUIDE_RATIO_UNMET`."

        Design: Corner/state_machines/slot_open_with_zero_guides_is_rejected
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        slot = build_activity_slot(client, season["id"], **HIKE_SLOT)
        assertions.assert_slot_counters(slot, assigned_guide_count=0, required_guide_count=0)

        validate_error(
            client.open_slot(slot["id"], RANCH_MANAGER),
            ApiErrorId.ERR_GUIDE_RATIO_UNMET.value,
            409,
        )

        stored = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert stored["slot_status"] == "DRAFT"


class TestBookingLifecycleLocks:
    """A stay's occupancy dimension refuses to repeat a step it has taken."""

    def test_second_cancel_on_a_cancelled_booking_is_rejected(self, client):
        """Cancelling twice does not re-run the refund split on a dead stay.

        PRD: "A `ReservationsAgent` or a `RanchManager` cancels with a `reason`, and cancellation is accepted while the booking is `HELD` or `CONFIRMED`; any other state is refused with `ERR_BOOKING_STATE_INVALID`."

        Design: Corner/state_machines/second_cancel_on_a_cancelled_booking_is_rejected
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(guest["id"], "ADULT")],
        )

        first = validate_success(
            client.cancel_booking(booking["id"], "guest changed plans", RESERVATIONS_AGENT)
        )
        assert first["booking_status"] == "CANCELLED"
        assert first["payment_status"] == "FORFEITED"

        validate_error(
            client.cancel_booking(booking["id"], "duplicate cancel attempt", RESERVATIONS_AGENT),
            ApiErrorId.ERR_BOOKING_STATE_INVALID.value,
            409,
        )

        stored = validate_success(client.get_booking(booking["id"], RESERVATIONS_AGENT))
        assert stored["booking_status"] == "CANCELLED"
        assert stored["refunded_cents"] == 0
        assert stored["forfeited_cents"] == 0
        assertions.assert_cancellation_split_is_conservative(stored)

    def test_second_confirm_on_a_confirmed_booking_is_rejected(self, client):
        """Confirming twice is refused, so the season counts the bed-nights once.

        PRD: "The booking must be `HELD`, or the request is refused with `ERR_BOOKING_STATE_INVALID`; the governing season must be `OPEN` or `IN_SEASON`, or the request is refused with `ERR_SEASON_NOT_OPEN`; and `deposit_paid_cents` must have reached `deposit_required_cents`, or the request is refused with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."

        Design: Corner/state_machines/second_confirm_on_a_confirmed_booking_is_rejected
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(guest["id"], "ADULT")],
        )
        assert booking["provisional_package_total_cents"] == 479500
        assert booking["deposit_required_cents"] == 143850

        pay_deposit(client, booking["id"], 143850)
        first = validate_success(client.confirm_booking(booking["id"], RESERVATIONS_AGENT))
        assert first["booking_status"] == "CONFIRMED"

        validate_error(
            client.confirm_booking(booking["id"], RESERVATIONS_AGENT),
            ApiErrorId.ERR_BOOKING_STATE_INVALID.value,
            409,
        )

        stored_season = validate_success(client.get_season(season["id"], RANCH_MANAGER))
        assert stored_season["bed_nights_sold"] == 7

    def test_booking_check_in_applies_every_declared_side_effect(self, client):
        """One arrival request moves the cabin, the dining count and the folio row.

        PRD: "A successful arrival moves `booking_status` from `CONFIRMED` to `CHECKED_IN`, stamps `checked_in_at` from the logical clock, records the `dietary_briefing_ack` flag on the booking, moves the cabin `READY → OCCUPIED`, raises the season's `in_house_guest_count` by the party's size, and increments the booking's, the cabin's and the season's `version` by 1 each."

        Design: Corner/state_machines/booking_check_in_applies_every_declared_side_effect
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        child = build_guest(client, "Cal Child", "2016-05-20", 95)
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [
                party_member(adult_one["id"], "ADULT"),
                party_member(adult_two["id"], "ADULT"),
                party_member(child["id"], "CHILD"),
            ],
        )
        pay_deposit(client, booking["id"], 377607)
        confirm_booking(client, booking["id"])
        set_clock_to(client, "2026-10-11T16:00:00Z")

        arrived = validate_success(
            client.check_in_booking(booking["id"], check_in_payload(True), RESERVATIONS_AGENT)
        )
        assert arrived["booking_status"] == "CHECKED_IN"
        assertions.assert_instant_equals(
            arrived["checked_in_at"], "2026-10-11T16:00:00Z", "checked_in_at"
        )

        stored_booking = validate_success(client.get_booking(booking["id"], RESERVATIONS_AGENT))
        assert stored_booking["dietary_briefing_ack"] is True

        stored_cabin = validate_success(client.get_cabin(cabin["id"], RANCH_MANAGER))
        assert stored_cabin["cabin_status"] == "OCCUPIED"

        stored_season = validate_success(client.get_season(season["id"], RANCH_MANAGER))
        assert stored_season["in_house_guest_count"] == 3
        assert stored_season["bed_nights_sold"] == 21


class TestAbilityAssessmentCycle:
    """The arena verdict may be challenged and re-issued without limit."""

    def test_rider_assessment_loops_evaluated_to_re_evaluation_and_back(self, client):
        """A flagged rider is capped at novice and recovers on the re-ride.

        PRD: "The cycle `EVALUATED → RE_EVALUATION_REQUESTED → EVALUATED` may repeat without limit, and each return to `EVALUATED` lifts the `NOVICE` cap again."

        Design: Corner/state_machines/rider_assessment_loops_evaluated_to_re_evaluation_and_back
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        sign_guest_waiver(client, guest["id"], "2026-08-01", True)
        assessment = open_assessment(client, guest["id"], "INTERMEDIATE")

        first = validate_success(
            client.evaluate_rider_assessment(
                assessment["id"],
                evaluate_assessment_payload(
                    "INTERMEDIATE", "rides a balanced seat at the trot", "2026-08-01T12:00:00Z"
                ),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assert first["assessment_status"] == "EVALUATED"

        flagged = validate_success(
            client.flag_re_evaluation(
                assessment["id"],
                "guide observed loss of control at the canter",
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assert flagged["assessment_status"] == "RE_EVALUATION_REQUESTED"

        # PRD: "among the guest's assessments whose `assessment_status` is
        # `EVALUATED`, the one with the greatest `evaluated_at` is selected ...
        # If the guest has no `EVALUATED` assessment at all,
        # `current_ability_rank` is `UNASSESSED`."  Flagging moved the guest's
        # only assessment out of EVALUATED, so the verdict is withdrawn, and the
        # re-evaluation cap "is lowered to `NOVICE` if it stands above `NOVICE`"
        # can only lower - never raise - the result.
        capped = validate_success(client.get_guest(guest["id"], HORSE_PROGRAM_DIRECTOR))
        assert capped["current_ability_rank"] == "UNASSESSED"
        assert (
            constants.ABILITY_RANKS[capped["effective_ability_rank"]]
            <= constants.ABILITY_RANKS[constants.RE_EVALUATION_CAP]
        )

        looped = validate_success(
            client.evaluate_rider_assessment(
                assessment["id"],
                evaluate_assessment_payload(
                    "INTERMEDIATE", "re-ride clean at the canter", "2026-08-03T12:00:00Z"
                ),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assert looped["assessment_status"] == "EVALUATED"

        stored_assessment = validate_success(
            client.get_rider_assessment(assessment["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert stored_assessment["re_evaluation_reason"] is None

        restored = validate_success(client.get_guest(guest["id"], HORSE_PROGRAM_DIRECTOR))
        assert restored["effective_ability_rank"] == "INTERMEDIATE"
        assert restored["current_ability_rank"] == "INTERMEDIATE"


class TestWaiverRevocationCascade:
    """Withdrawing consent unwinds only the rides that have not left the corral."""

    def test_waiver_revocation_cancels_only_the_future_confirmed_seat(self, client):
        """The departed hike keeps its rider while the evening hike loses the seat.

        PRD: "First, every activity seat of that guest whose `reservation_status` is `CONFIRMED` and whose slot has not yet started — that is, whose slot `starts_at` is strictly later than the current clock instant — becomes `CANCELLED`, with `surcharge_reversed_cents` set to that seat's own `surcharge_cents`."

        Design: Corner/state_machines/waiver_revocation_cancels_only_the_future_confirmed_seat
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        sign_guest_waiver(client, guest["id"], "2026-08-01", True)
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(guest["id"], "ADULT")],
        )
        pay_deposit(client, booking["id"], 143850)
        confirm_booking(client, booking["id"])

        guide = build_active_guide(
            client, season["id"], full_name="Gus Guide", certifications=["WILDERNESS_FIRST_AID"]
        )
        early_slot = build_activity_slot(client, season["id"], **HIKE_SLOT)
        late_slot = build_activity_slot(
            client,
            season["id"],
            **dict(
                HIKE_SLOT,
                starts_at="2026-10-12T18:00:00Z",
                ends_at="2026-10-12T20:00:00Z",
                rider_surcharge_cents=12000,
            ),
        )
        early_seat = take_seat(client, early_slot["id"], booking["id"], guest["id"])
        late_seat = take_seat(client, late_slot["id"], booking["id"], guest["id"])
        assign_guide(client, early_slot["id"], guide["id"])
        assign_guide(client, late_slot["id"], guide["id"])
        open_slot(client, early_slot["id"])
        open_slot(client, late_slot["id"])

        set_clock_to(client, "2026-10-12T15:30:00Z")
        running = validate_success(
            client.run_slot(early_slot["id"], make_activity_guide_headers(guide["id"]))
        )
        assert running["slot_status"] == "RUNNING"

        revoked = validate_success(
            client.revoke_waiver(
                guest["id"], "guest withdrew consent after the safety briefing", RANCH_MANAGER
            )
        )
        assert revoked["waiver_status"] == "REVOKED"
        assertions.assert_instant_equals(
            revoked["waiver_revoked_at"], "2026-10-12T15:30:00Z", "waiver_revoked_at"
        )

        stored_early = validate_success(client.get_reservation(early_seat["id"], RESERVATIONS_AGENT))
        assert stored_early["reservation_status"] == "CONFIRMED"
        assert stored_early["surcharge_reversed_cents"] == 0

        stored_late = validate_success(client.get_reservation(late_seat["id"], RESERVATIONS_AGENT))
        assert stored_late["reservation_status"] == "CANCELLED"
        assert stored_late["surcharge_reversed_cents"] == 12000

        stored_late_slot = validate_success(
            client.get_activity_slot(late_slot["id"], RANCH_MANAGER)
        )
        assertions.assert_slot_counters(
            stored_late_slot, confirmed_rider_count=0, seats_available=4
        )

        stored_booking = validate_success(client.get_booking(booking["id"], RESERVATIONS_AGENT))
        assert stored_booking["activity_surcharge_total_cents"] == 0


class TestSlotCancellationCascade:
    """Calling off a published ride unwinds seats, mounts and guides together."""

    def test_slot_cancel_cascades_down_to_seats_mounts_and_guides(self, client):
        """One cancellation reverses both surcharges, both mounts and the guide.

        PRD: "From `OPEN` and from `HOLD` the reversal is identical and complete: every `CONFIRMED` seat becomes `CANCELLED` with `surcharge_reversed_cents` set to its own `surcharge_cents`, returning each affected booking's `activity_surcharge_total_cents` to its pre-reservation value; every `ASSIGNED` mount becomes `RELEASED` with each horse's `scheduled_load_hours` restored exactly; and every `SCHEDULED` guide assignment becomes `RELEASED`."

        Design: Corner/state_machines/slot_cancel_cascades_down_to_seats_mounts_and_guides
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        rider_one = build_assessed_rider(client, "Ann Adult", "1985-04-02", 165, "INTERMEDIATE")
        rider_two = build_assessed_rider(client, "Ben Adult", "1983-07-11", 190, "INTERMEDIATE")
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [
                party_member(rider_one["id"], "ADULT"),
                party_member(rider_two["id"], "ADULT"),
            ],
        )
        pay_deposit(client, booking["id"], 287700)
        confirm_booking(client, booking["id"])

        comet = build_horse(client, "Comet", "BEGINNER", "ADVANCED", 240)
        dusty = build_horse(client, "Dusty", "BEGINNER", "ADVANCED", 240)
        guide = build_active_guide(client, season["id"], full_name="Gus Guide")
        slot = build_activity_slot(client, season["id"])

        seat_one = take_seat(client, slot["id"], booking["id"], rider_one["id"])
        seat_two = take_seat(client, slot["id"], booking["id"], rider_two["id"])
        attach_mount(client, seat_one["id"], comet["id"])
        attach_mount(client, seat_two["id"], dusty["id"])
        assignment = assign_guide(client, slot["id"], guide["id"])

        opened = validate_success(client.open_slot(slot["id"], RANCH_MANAGER))
        assertions.assert_slot_counters(opened, confirmed_rider_count=2, mount_assigned_count=2)

        cancelled = validate_success(
            client.cancel_slot(slot["id"], "wildfire smoke advisory", RANCH_MANAGER)
        )
        assert cancelled["slot_status"] == "CANCELLED"

        for seat in (seat_one, seat_two):
            stored_seat = validate_success(
                client.get_reservation(seat["id"], RESERVATIONS_AGENT)
            )
            assert stored_seat["reservation_status"] == "CANCELLED"
            assert stored_seat["surcharge_reversed_cents"] == 20000
            assert stored_seat["mount_status"] == "RELEASED"

        for horse_id in (comet["id"], dusty["id"]):
            stored_horse = validate_success(
                client.get_horse(horse_id, HORSE_PROGRAM_DIRECTOR)
            )
            assertions.assert_horse_load(stored_horse, scheduled_load_hours=0.0)

        stored_assignment = validate_success(
            client.get_guide_assignment(assignment["id"], RANCH_MANAGER)
        )
        assert stored_assignment["assignment_status"] == "RELEASED"

        stored_booking = validate_success(client.get_booking(booking["id"], RESERVATIONS_AGENT))
        assert stored_booking["activity_surcharge_total_cents"] == 0


class TestIncidentDrivenHorseStatus:
    """An animal's availability is driven by the incident file it appears in."""

    def test_incident_disposition_returns_the_named_horse_to_service(self, client):
        """Filing benches the horse for review and a clean verdict returns it.

        PRD: "The `CLEARED` branch touches only the animal: a horse sitting in `REVIEW_HOLD` returns to `IN_SERVICE` and re-enters the mount pool immediately, and nothing at all happens to the guest."

        Design: Corner/state_machines/incident_disposition_returns_the_named_horse_to_service
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        rider = build_assessed_rider(client, "Ann Adult", "1985-04-02", 165, "INTERMEDIATE")
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(rider["id"], "ADULT")],
        )
        pay_deposit(client, booking["id"], 143850)
        confirm_booking(client, booking["id"])

        comet = build_horse(client, "Comet", "BEGINNER", "ADVANCED", 240)
        guide = build_active_guide(client, season["id"], full_name="Gus Guide")
        slot = build_activity_slot(client, season["id"])
        seat = take_seat(client, slot["id"], booking["id"], rider["id"])
        attach_mount(client, seat["id"], comet["id"])
        assign_guide(client, slot["id"], guide["id"])
        open_slot(client, slot["id"])

        filed = validate_success(
            client.create_incident_report(
                seat["id"],
                incident_report_payload(
                    "SERIOUS",
                    True,
                    "horse spooked at a grouse and the rider dismounted hard",
                    "2026-10-12T15:40:00Z",
                    comet["id"],
                ),
                make_activity_guide_headers(guide["id"]),
            ),
            201,
        )
        assert filed["incident_status"] == "FILED"
        assert filed["guest_id"] == rider["id"]
        assert filed["reported_by_staff_member_id"] == guide["id"]

        benched = validate_success(client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR))
        assert benched["horse_status"] == "REVIEW_HOLD"

        disposed = validate_success(
            client.dispose_incident_report(
                filed["id"],
                dispose_payload("CLEARED", "vet exam clean; rider error"),
                SAFETY_OFFICER,
            )
        )
        assert disposed["incident_status"] == "CLEARED"
        assert disposed["disposed_by_user_id"] == SAFETY_OFFICER_ONE_USER_ID

        restored = validate_success(client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR))
        assert restored["horse_status"] == "IN_SERVICE"

        stored_guest = validate_success(client.get_guest(rider["id"], HORSE_PROGRAM_DIRECTOR))
        assert stored_guest["guest_standing"] == "GOOD"


class TestSlotCompletionLedgers:
    """Finishing a ride settles the guide, the herd and the folio in one request."""

    def test_slot_completion_syncs_horse_guide_and_booking_ledgers(self, client):
        """Two and a half hours are credited, one rider no-shows, one duty day starts.

        PRD: "Every `SCHEDULED` guide assignment on the slot becomes `COMPLETED` with `credited_hours` set to the slot's `actual_duration_hours`."

        Design: Corner/state_machines/slot_completion_syncs_horse_guide_and_booking_ledgers
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        rider_one = build_assessed_rider(client, "Ann Adult", "1985-04-02", 165, "INTERMEDIATE")
        rider_two = build_assessed_rider(client, "Ben Adult", "1983-07-11", 190, "INTERMEDIATE")
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [
                party_member(rider_one["id"], "ADULT"),
                party_member(rider_two["id"], "ADULT"),
            ],
        )
        pay_deposit(client, booking["id"], 287700)
        confirm_booking(client, booking["id"])

        comet = build_horse(client, "Comet", "BEGINNER", "ADVANCED", 240)
        dusty = build_horse(client, "Dusty", "BEGINNER", "ADVANCED", 240)
        guide = build_active_guide(client, season["id"], full_name="Gus Guide")
        slot = build_activity_slot(client, season["id"])
        assert float(slot["duration_hours"]) == 2.0

        seat_one = take_seat(client, slot["id"], booking["id"], rider_one["id"])
        seat_two = take_seat(client, slot["id"], booking["id"], rider_two["id"])
        attach_mount(client, seat_one["id"], comet["id"])
        attach_mount(client, seat_two["id"], dusty["id"])
        assignment = assign_guide(client, slot["id"], guide["id"])
        open_slot(client, slot["id"])

        guide_headers = make_activity_guide_headers(guide["id"])
        set_clock_to(client, constants.SLOT_STARTS_AT)
        get_success_data(client.run_slot(slot["id"], guide_headers))
        get_success_data(client.check_in_reservation(seat_one["id"], guide_headers))

        completed = validate_success(
            client.complete_slot(slot["id"], complete_slot_payload(2.5), guide_headers)
        )
        assert completed["slot_status"] == "COMPLETED"
        assert float(completed["actual_duration_hours"]) == 2.5

        ridden_seat = validate_success(client.get_reservation(seat_one["id"], RESERVATIONS_AGENT))
        assert ridden_seat["reservation_status"] == "COMPLETED"
        assert ridden_seat["mount_status"] == "COMPLETED"

        absent_seat = validate_success(client.get_reservation(seat_two["id"], RESERVATIONS_AGENT))
        assert absent_seat["reservation_status"] == "NO_SHOW"
        assert absent_seat["mount_status"] == "RELEASED"

        ridden_horse = validate_success(client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR))
        assertions.assert_horse_load(
            ridden_horse,
            scheduled_load_hours=0.0,
            realized_load_hours=2.5,
            consecutive_duty_days=1,
        )
        assert ridden_horse["last_duty_date"] == "2026-10-12"

        idle_horse = validate_success(client.get_horse(dusty["id"], HORSE_PROGRAM_DIRECTOR))
        assertions.assert_horse_load(
            idle_horse, scheduled_load_hours=0.0, realized_load_hours=0.0
        )

        stored_assignment = validate_success(
            client.get_guide_assignment(assignment["id"], RANCH_MANAGER)
        )
        assert stored_assignment["assignment_status"] == "COMPLETED"
        assert float(stored_assignment["credited_hours"]) == 2.5

        stored_booking = validate_success(client.get_booking(booking["id"], RESERVATIONS_AGENT))
        assert stored_booking["no_show_count"] == 1
        assert stored_booking["no_show_penalty_total_cents"] == 4500
