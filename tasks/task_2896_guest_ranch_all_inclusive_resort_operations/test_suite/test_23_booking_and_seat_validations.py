"""Booking, arrival and seat validations — the gates the ranch closes on a
request before any money or any saddle is committed."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    check_in_payload,
    check_out_payload,
    create_activity_slot_payload,
    create_booking_payload,
    create_staff_member_payload,
    guide_assignment_payload,
    onboard_payload,
    party_member,
    payment_payload,
    reservation_payload,
    waiver_signature_payload,
)
from test_helpers.fixtures import (
    assign_guide,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_in_season,
    build_open_season,
    confirm_booking,
    open_slot,
    set_clock_to,
    sign_guest_waiver,
    take_seat,
)
from test_helpers.test_users import (
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
    make_activity_guide_headers,
)

SOLO_CLASSIC_DEPOSIT_CENTS = 143850
PAIR_CLASSIC_DEPOSIT_CENTS = 287700
TRIO_CLASSIC_DEPOSIT_CENTS = 431550
FAMILY_CLASSIC_DEPOSIT_CENTS = 377607


def _hold_booking(client, season_id, cabin_id, lead_guest_id, members, **overrides):
    """Post a booking request exactly as written, without a helper's defaults."""
    return client.create_booking(
        create_booking_payload(season_id, cabin_id, lead_guest_id, members, **overrides),
        RESERVATIONS_AGENT,
    )


def _confirmed_booking(client, season_id, cabin_id, members, deposit_cents, **overrides):
    booking = build_booking(client, season_id, cabin_id, members, **overrides)
    get_success_data(
        client.post_payment(
            booking["id"], payment_payload(deposit_cents), RESERVATIONS_AGENT
        )
    )
    return confirm_booking(client, booking["id"])


def _slot(client, season_id, **overrides):
    return get_success_data(
        client.create_activity_slot(
            season_id, create_activity_slot_payload(**overrides), RANCH_MANAGER
        )
    )


def _read_slot(client, slot_id):
    return get_success_data(client.get_activity_slot(slot_id, RANCH_MANAGER))


class TestWeeklyCadenceGates:
    """The season's calendar cadence, party shape and cabin capacity."""

    def test_calendar_gates_each_report_their_own_refusal(self, client):
        """A Monday arrival, a five-night stay and a departure past season end are each refused.

        PRD: "The `arrival_date` must fall on the weekday the season names in `arrival_weekday`, and an arrival on any other weekday is refused with `ERR_ARRIVAL_DAY_INVALID`."

        Design: Corner/validations/booking_calendar_gates_reject_wrong_weekday_short_stay_and_overrun
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        members = [party_member(guest["id"])]

        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                guest["id"],
                members,
                arrival_date="2026-10-12",
                departure_date="2026-10-19",
            ),
            ApiErrorId.ERR_ARRIVAL_DAY_INVALID.value,
            422,
        )
        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                guest["id"],
                members,
                arrival_date="2026-10-11",
                departure_date="2026-10-16",
            ),
            ApiErrorId.ERR_STAY_LENGTH_INVALID.value,
            422,
        )
        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                guest["id"],
                members,
                arrival_date="2026-11-15",
                departure_date="2026-11-22",
            ),
            ApiErrorId.ERR_STAY_OUTSIDE_SEASON.value,
            422,
        )

        accepted = validate_success(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                guest["id"],
                members,
                arrival_date="2026-10-11",
                departure_date="2026-10-18",
            ),
            201,
        )
        assertions.assert_booking(accepted)
        assert accepted["booking_status"] == "HELD"
        assert accepted["nights"] == 7

        held, meta = validate_paginated(
            client.list_bookings(RESERVATIONS_AGENT, {"season_id": season["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in held] == [accepted["id"]]

    def test_party_shape_defects_each_report_their_own_refusal(self, client):
        """A mis-typed member, a repeated guest, an outside lead and an unknown tier each refuse.

        PRD: "Each element's `member_type` must agree with the referenced guest's `age_years`: an `ADULT` element requires the guest to be at least 18 years old and a `CHILD` element requires the guest to be under 18, and a disagreement is refused with `ERR_MEMBER_TYPE_MISMATCH`."

        Design: Corner/validations/booking_party_composition_rules_each_return_their_own_error
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        child = build_guest(client, "Cal Child", "2016-05-20", 95)
        assert child["age_years"] == 10

        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                adult_one["id"],
                [party_member(adult_one["id"]), party_member(child["id"], "ADULT")],
            ),
            ApiErrorId.ERR_MEMBER_TYPE_MISMATCH.value,
            422,
        )
        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                adult_one["id"],
                [party_member(adult_one["id"]), party_member(adult_one["id"])],
            ),
            ApiErrorId.ERR_DUPLICATE_PARTY_MEMBER.value,
            422,
        )
        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                child["id"],
                [party_member(adult_one["id"]), party_member(adult_two["id"])],
            ),
            ApiErrorId.ERR_LEAD_GUEST_NOT_IN_PARTY.value,
            422,
        )
        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                adult_one["id"],
                [party_member(adult_one["id"])],
                package_tier_code="SIGNATURE",
            ),
            ApiErrorId.ERR_PACKAGE_TIER_UNKNOWN.value,
            422,
        )

        untouched = get_success_data(client.get_season(season["id"], RANCH_MANAGER))
        assert untouched["bed_nights_sold"] == 0

    def test_party_of_four_fits_the_four_bed_cabin_but_five_does_not(self, client):
        """Five bodies overflow a four-bed cabin while exactly four are accepted.

        PRD: "And the computed `party_size` may not exceed the cabin's `bed_capacity`, or the request is refused with `ERR_CABIN_CAPACITY_EXCEEDED`."

        Design: Corner/validations/party_of_exactly_four_fits_the_four_bed_cabin_and_five_does_not
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adults = [
            build_guest(client, "Ann Adult", "1985-04-02", 165),
            build_guest(client, "Ben Adult", "1983-07-11", 190),
            build_guest(client, "Cy Adult", "1979-02-09", 175),
            build_guest(client, "Dee Adult", "1990-01-15", 175),
        ]
        child = build_guest(client, "Fay Child", "2015-03-03", 90)
        four_adults = [party_member(guest["id"]) for guest in adults]

        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin["id"],
                adults[0]["id"],
                four_adults + [party_member(child["id"], "CHILD")],
            ),
            ApiErrorId.ERR_CABIN_CAPACITY_EXCEEDED.value,
            422,
        )

        accepted = validate_success(
            _hold_booking(
                client, season["id"], cabin["id"], adults[0]["id"], four_adults
            ),
            201,
        )
        assert accepted["party_size"] == 4
        assert accepted["booking_status"] == "HELD"
        assert accepted["provisional_package_total_cents"] == 1918000


class TestSingleSeatingDiningRoom:
    """The one dining room the whole ranch shares at arrival time."""

    def test_dining_capacity_is_counted_across_every_cabin(self, client):
        """A four-seat dining room admits a party of three and then turns away a pair.

        PRD: "The season's current `in_house_guest_count` plus this booking's `party_size` may not exceed the season's `dining_seat_capacity`, and a party that would overfill the seating is refused with `ERR_DINING_CAPACITY_EXCEEDED` — this is a hard ranch-wide aggregate, not a per-cabin one."

        Design: Corner/validations/single_seating_dining_capacity_is_a_season_wide_aggregate
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client, dining_seat_capacity=4)
        cabin_a = build_cabin(client, name="Aspen", bed_capacity=4)
        cabin_b = build_cabin(client, name="Birch", bed_capacity=4)
        guests = [
            build_guest(client, "Ann Adult", "1985-04-02", 165),
            build_guest(client, "Ben Adult", "1983-07-11", 190),
            build_guest(client, "Cy Adult", "1979-02-09", 175),
            build_guest(client, "Dee Adult", "1990-01-15", 175),
            build_guest(client, "Eve Adult", "1988-06-30", 150),
        ]
        booking_a = _confirmed_booking(
            client,
            season["id"],
            cabin_a["id"],
            [party_member(guest["id"]) for guest in guests[:3]],
            TRIO_CLASSIC_DEPOSIT_CENTS,
        )
        booking_b = _confirmed_booking(
            client,
            season["id"],
            cabin_b["id"],
            [party_member(guest["id"]) for guest in guests[3:]],
            PAIR_CLASSIC_DEPOSIT_CENTS,
        )

        set_clock_to(client, "2026-10-11T12:00:00Z")
        arrived = validate_success(
            client.check_in_booking(
                booking_a["id"], check_in_payload(True), RESERVATIONS_AGENT
            )
        )
        assert arrived["booking_status"] == "CHECKED_IN"

        seated = get_success_data(client.get_season(season["id"], RANCH_MANAGER))
        assert seated["in_house_guest_count"] == 3

        validate_error(
            client.check_in_booking(
                booking_b["id"], check_in_payload(True), RESERVATIONS_AGENT
            ),
            ApiErrorId.ERR_DINING_CAPACITY_EXCEEDED.value,
            409,
        )

        unchanged = get_success_data(client.get_season(season["id"], RANCH_MANAGER))
        assert unchanged["in_house_guest_count"] == 3

        turned_away = get_success_data(client.get_booking(booking_b["id"], RESERVATIONS_AGENT))
        assert turned_away["booking_status"] == "CONFIRMED"
        assert turned_away["checked_in_at"] is None

    def test_dietary_briefing_is_demanded_only_from_the_party_that_declared_one(self, client):
        """A gluten-free party must acknowledge the kitchen briefing; a party with no restriction need not.

        PRD: "Finally, whenever any element of the party roster declares a `dietary_restrictions` value other than `NONE`, `dietary_briefing_ack` must be supplied as true, since a single seating cannot absorb an unannounced allergy; an unacknowledged briefing is refused with `ERR_DIETARY_BRIEFING_REQUIRED`."

        Design: Corner/validations/dietary_briefing_ack_is_demanded_only_when_a_restriction_is_declared
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin_a = build_cabin(client, name="Aspen", bed_capacity=4)
        cabin_b = build_cabin(client, name="Birch", bed_capacity=4)
        restricted_guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ordinary_guest = build_guest(client, "Ben Adult", "1983-07-11", 190)

        restricted_booking = _confirmed_booking(
            client,
            season["id"],
            cabin_a["id"],
            [party_member(restricted_guest["id"], "ADULT", ["GLUTEN_FREE"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
        )
        ordinary_booking = _confirmed_booking(
            client,
            season["id"],
            cabin_b["id"],
            [party_member(ordinary_guest["id"], "ADULT", ["NONE"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
        )

        set_clock_to(client, "2026-10-11T12:00:00Z")
        validate_error(
            client.check_in_booking(
                restricted_booking["id"], check_in_payload(False), RESERVATIONS_AGENT
            ),
            ApiErrorId.ERR_DIETARY_BRIEFING_REQUIRED.value,
            422,
        )

        unrestricted = validate_success(
            client.check_in_booking(
                ordinary_booking["id"], check_in_payload(False), RESERVATIONS_AGENT
            )
        )
        assert unrestricted["booking_status"] == "CHECKED_IN"
        assert unrestricted["dietary_briefing_ack"] is False

        acknowledged = validate_success(
            client.check_in_booking(
                restricted_booking["id"], check_in_payload(True), RESERVATIONS_AGENT
            )
        )
        assert acknowledged["booking_status"] == "CHECKED_IN"
        assert acknowledged["dietary_briefing_ack"] is True


class TestSeatEligibilityGates:
    """Who may hold a seat on a slot, and how many seats they may hold."""

    def test_suspended_guest_regains_a_seat_only_after_reinstatement(self, client):
        """A suspended guest is refused a hike seat and takes one once reinstated.

        PRD: "In priority order the seat is refused when the booking and the slot belong to different seasons or the named guest does not appear in the booking's `party_members` (`ERR_SEASON_MISMATCH`); when `expected_slot_version` does not match (`ERR_STALE_SLOT_VERSION`); when the slot is not `DRAFT`, `OPEN` or `HOLD` (`ERR_SLOT_STATE_INVALID`); when the guest's `guest_standing` is `SUSPENDED` (`ERR_GUEST_SUSPENDED`); when the guest's resolved `waiver_status` is not `SIGNED` (`ERR_WAIVER_NOT_SIGNED`); when the slot requires a mount and the guest's `equine_statute_ack` is not true (`ERR_EQUINE_STATUTE_ACK_REQUIRED`); when the guest's `effective_ability_rank` sits below the slot's `min_ability_rank` (`ERR_RIDER_ABILITY_INSUFFICIENT`); when the guest already holds a `CONFIRMED` or `CHECKED_IN` seat on another slot whose half-open interval overlaps this one (`ERR_GUEST_SLOT_CONFLICT`); when the slot is on `HOLD` (`ERR_SLOT_ON_HOLD`); when `seats_available` has fallen below 1 (`ERR_SLOT_FULL`); and finally when the guest already holds a `CONFIRMED` or `CHECKED_IN` seat on this very slot (`ERR_DUPLICATE_RESERVATION`)."

        Design: Corner/validations/suspended_guest_cannot_take_a_seat_until_reinstated
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        sign_guest_waiver(client, guest["id"])
        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(guest["id"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
        )
        slot = _slot(
            client,
            season["id"],
            activity_type="HIKE",
            starts_at="2026-10-13T15:00:00Z",
            ends_at="2026-10-13T17:00:00Z",
            terrain_grade="ROLLING",
            min_ability_rank="UNASSESSED",
            capacity=4,
            rider_surcharge_cents=0,
            mount_required=False,
        )

        suspended = get_success_data(
            client.suspend_guest(
                guest["id"],
                "SUSPENDED",
                "repeated refusal to follow guide instructions",
                RANCH_MANAGER,
            )
        )
        assert suspended["guest_standing"] == "SUSPENDED"

        before = _read_slot(client, slot["id"])
        validate_error(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], guest["id"], before["version"]),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_GUEST_SUSPENDED.value,
            409,
        )

        reinstated = get_success_data(
            client.reinstate_guest(
                guest["id"],
                "written apology accepted by the ranch manager",
                RANCH_MANAGER,
            )
        )
        assert reinstated["guest_standing"] == "GOOD"

        after = _read_slot(client, slot["id"])
        assert after["version"] == before["version"]

        seat = validate_success(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], guest["id"], after["version"]),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        assertions.assert_activity_reservation(seat)
        assert seat["reservation_status"] == "CONFIRMED"

        seated_slot = _read_slot(client, slot["id"])
        assertions.assert_slot_counters(seated_slot, confirmed_rider_count=1)

    def test_guest_cannot_hold_two_seats_on_the_same_slot(self, client):
        """A second seat for the same guest on the same hike is refused as a duplicate.

        PRD: "In priority order the seat is refused when the booking and the slot belong to different seasons or the named guest does not appear in the booking's `party_members` (`ERR_SEASON_MISMATCH`); when `expected_slot_version` does not match (`ERR_STALE_SLOT_VERSION`); when the slot is not `DRAFT`, `OPEN` or `HOLD` (`ERR_SLOT_STATE_INVALID`); when the guest's `guest_standing` is `SUSPENDED` (`ERR_GUEST_SUSPENDED`); when the guest's resolved `waiver_status` is not `SIGNED` (`ERR_WAIVER_NOT_SIGNED`); when the slot requires a mount and the guest's `equine_statute_ack` is not true (`ERR_EQUINE_STATUTE_ACK_REQUIRED`); when the guest's `effective_ability_rank` sits below the slot's `min_ability_rank` (`ERR_RIDER_ABILITY_INSUFFICIENT`); when the guest already holds a `CONFIRMED` or `CHECKED_IN` seat on another slot whose half-open interval overlaps this one (`ERR_GUEST_SLOT_CONFLICT`); when the slot is on `HOLD` (`ERR_SLOT_ON_HOLD`); when `seats_available` has fallen below 1 (`ERR_SLOT_FULL`); and finally when the guest already holds a `CONFIRMED` or `CHECKED_IN` seat on this very slot (`ERR_DUPLICATE_RESERVATION`)."

        Design: Corner/validations/guest_cannot_hold_two_seats_on_the_same_slot
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        sign_guest_waiver(client, guest["id"])
        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(guest["id"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
        )
        slot = _slot(
            client,
            season["id"],
            activity_type="HIKE",
            starts_at="2026-10-13T15:00:00Z",
            ends_at="2026-10-13T17:00:00Z",
            terrain_grade="ROLLING",
            min_ability_rank="UNASSESSED",
            capacity=4,
            rider_surcharge_cents=0,
            mount_required=False,
        )

        first_seat = take_seat(client, slot["id"], booking["id"], guest["id"])
        assert first_seat["reservation_status"] == "CONFIRMED"

        seated_slot = _read_slot(client, slot["id"])
        validate_error(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], guest["id"], seated_slot["version"]),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_DUPLICATE_RESERVATION.value,
            409,
        )

        unchanged = _read_slot(client, slot["id"])
        assertions.assert_slot_counters(
            unchanged, confirmed_rider_count=1, seats_available=3
        )

        surviving = get_success_data(
            client.get_reservation(first_seat["id"], RESERVATIONS_AGENT)
        )
        assert surviving["reservation_status"] == "CONFIRMED"

        seats, meta = validate_paginated(
            client.list_reservations(
                RESERVATIONS_AGENT, {"slot_id": slot["id"], "guest_id": guest["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in seats] == [first_seat["id"]]


class TestGuideStaffingAndStartGates:
    """The certification a slot demands and the clock a slot waits for."""

    def test_guide_certification_must_match_the_activity_demanded(self, client):
        """A fly-casting guide cannot lead a trail ride but staffs the river session.

        PRD: "The named staff member must be `ACTIVE`, must belong to the slot's own season, and must hold the certification the activity demands: `EQUINE_HANDLER` for a `TRAIL_RIDE` or an `ARENA_LESSON`, `FLY_CASTING` for `FLY_FISHING`, `CHILD_PROGRAM` for a `KIDS_PROGRAM`, and `WILDERNESS_FIRST_AID` for a `HIKE`."

        Design: Corner/validations/guide_certification_must_match_the_activity_type
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        hired = get_success_data(
            client.create_staff_member(
                season["id"],
                create_staff_member_payload(
                    "Fin Fisher",
                    "GUIDE",
                    ["FLY_CASTING"],
                    hired_on="2026-08-01",
                    contract_end_date="2026-11-15",
                ),
                RANCH_MANAGER,
            )
        )
        guide = get_success_data(
            client.onboard_staff_member(
                hired["id"], onboard_payload("BUNKHOUSE-B", 1), RANCH_MANAGER
            )
        )
        assertions.assert_staff_member(guide)
        assert guide["employment_status"] == "ACTIVE"

        ride_slot = _slot(
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
        fishing_slot = _slot(
            client,
            season["id"],
            activity_type="FLY_FISHING",
            starts_at="2026-10-13T08:00:00Z",
            ends_at="2026-10-13T10:00:00Z",
            terrain_grade="RIVER_CROSSING",
            min_ability_rank="UNASSESSED",
            capacity=4,
            rider_surcharge_cents=5000,
            mount_required=False,
        )

        validate_error(
            client.create_guide_assignment(
                ride_slot["id"], guide_assignment_payload(guide["id"]), RANCH_MANAGER
            ),
            ApiErrorId.ERR_CERTIFICATION_MISSING.value,
            422,
        )

        assignment = validate_success(
            client.create_guide_assignment(
                fishing_slot["id"], guide_assignment_payload(guide["id"]), RANCH_MANAGER
            ),
            201,
        )
        assertions.assert_guide_assignment(assignment)
        assert assignment["assignment_status"] == "SCHEDULED"

        assertions.assert_slot_counters(
            _read_slot(client, ride_slot["id"]), assigned_guide_count=0
        )
        assertions.assert_slot_counters(
            _read_slot(client, fishing_slot["id"]), assigned_guide_count=1
        )

        credited = get_success_data(client.get_staff_member(guide["id"], RANCH_MANAGER))
        assert float(credited["scheduled_guide_hours"]) == 2.0

    def test_slot_cannot_run_one_minute_before_its_scheduled_start(self, client):
        """A guide who calls the hike a minute early is refused and succeeds on the hour.

        PRD: "Four conditions gate the start: the slot must be `OPEN`, or `ERR_SLOT_STATE_INVALID`; the season must be `IN_SEASON`, or `ERR_SEASON_NOT_OPEN`; the logical clock must have reached the slot's `starts_at`, or `ERR_SLOT_NOT_STARTED`; and the posture must read `STAFFED_READY` — a shortfall of guides reports `ERR_GUIDE_RATIO_UNMET` and a mounted slot with fewer assigned mounts than confirmed riders reports `ERR_MOUNTS_INCOMPLETE`."

        Design: Corner/validations/slot_cannot_run_one_minute_before_its_scheduled_start
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        guide = build_active_guide(
            client,
            season["id"],
            full_name="Gus Guide",
            certifications=["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"],
        )
        slot = _slot(
            client,
            season["id"],
            activity_type="HIKE",
            starts_at="2026-10-13T15:00:00Z",
            ends_at="2026-10-13T17:00:00Z",
            terrain_grade="ROLLING",
            min_ability_rank="UNASSESSED",
            capacity=4,
            rider_surcharge_cents=0,
            mount_required=False,
        )
        assign_guide(client, slot["id"], guide["id"], "LEAD")
        opened = open_slot(client, slot["id"])
        assert opened["slot_status"] == "OPEN"

        guide_headers = make_activity_guide_headers(guide["id"])
        set_clock_to(client, "2026-10-13T14:59:00Z")
        validate_error(
            client.run_slot(slot["id"], guide_headers),
            ApiErrorId.ERR_SLOT_NOT_STARTED.value,
            409,
        )

        waiting = _read_slot(client, slot["id"])
        assert waiting["slot_status"] == "OPEN"
        assert waiting["actual_started_at"] is None

        set_clock_to(client, "2026-10-13T15:00:00Z")
        running = validate_success(client.run_slot(slot["id"], guide_headers))
        assert running["slot_status"] == "RUNNING"
        assertions.assert_instant_equals(
            running["actual_started_at"], "2026-10-13T15:00:00Z", "actual_started_at"
        )


class TestWaiversBuyoutsAndDeparture:
    """Guardianship, whole-ranch exclusivity and the last cent at the desk."""

    def test_minor_waiver_needs_an_adult_guardian_with_a_live_waiver(self, client):
        """A child's waiver is refused unsigned and refused behind an unsigned adult, then accepted.

        PRD: "A guest whose `age_years` is below 18 may not sign for themself: the request must name a guardian in `waiver_signed_by_guardian_guest_id` that references another guest whose own `age_years` is at least 18 and whose own waiver resolves to `SIGNED`, and a minor's signature that names no such guardian is refused with `ERR_GUARDIAN_SIGNATURE_REQUIRED`."

        Design: Corner/validations/minor_waiver_needs_an_adult_guardian_whose_own_waiver_is_live
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        signed_adult = build_guest(client, "Ann Adult", "1985-04-02", 165)
        unsigned_adult = build_guest(client, "Ben Adult", "1983-07-11", 190)
        child = build_guest(client, "Cal Child", "2016-05-20", 95)
        assert child["age_years"] == 10

        adult_waiver = sign_guest_waiver(client, signed_adult["id"])
        assert adult_waiver["waiver_status"] == "SIGNED"
        assert adult_waiver["waiver_signed_by_guardian_guest_id"] is None

        validate_error(
            client.sign_waiver(
                child["id"],
                waiver_signature_payload("2026-08-01", True, None),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_GUARDIAN_SIGNATURE_REQUIRED.value,
            422,
        )
        validate_error(
            client.sign_waiver(
                child["id"],
                waiver_signature_payload("2026-08-01", True, unsigned_adult["id"]),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_GUARDIAN_SIGNATURE_REQUIRED.value,
            422,
        )

        countersigned = validate_success(
            client.sign_waiver(
                child["id"],
                waiver_signature_payload("2026-08-01", True, signed_adult["id"]),
                RESERVATIONS_AGENT,
            )
        )
        assertions.assert_guest(countersigned)
        assert countersigned["waiver_status"] == "SIGNED"
        assert countersigned["waiver_signed_by_guardian_guest_id"] == signed_adult["id"]
        assert countersigned["waiver_expires_on"] == "2027-08-01"

    def test_buyout_week_locks_every_cabin_not_just_its_own(self, client):
        """A buyout of one cabin blocks a booking in another cabin that same week.

        PRD: "Buyout exclusivity is tested over the same half-open interval but against **every** cabin in the season rather than the requested one: a booking with `is_buyout` true is refused if any live booking touches any cabin over its interval, and any ordinary booking is refused if its interval falls inside a live buyout's interval."

        Design: Corner/validations/buyout_week_locks_every_cabin_not_just_its_own
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin_a = build_cabin(client, name="Aspen", bed_capacity=4)
        cabin_b = build_cabin(client, name="Birch", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        adult_three = build_guest(client, "Cy Adult", "1979-02-09", 175)

        buyout = validate_success(
            _hold_booking(
                client,
                season["id"],
                cabin_a["id"],
                adult_one["id"],
                [party_member(adult_one["id"]), party_member(adult_two["id"])],
                arrival_date="2026-10-11",
                departure_date="2026-10-18",
                is_buyout=True,
            ),
            201,
        )
        assert buyout["is_buyout"] is True
        assert buyout["provisional_package_total_cents"] == 1102850
        assert buyout["deposit_required_cents"] == 330855

        validate_error(
            _hold_booking(
                client,
                season["id"],
                cabin_b["id"],
                adult_three["id"],
                [party_member(adult_three["id"])],
                arrival_date="2026-10-11",
                departure_date="2026-10-18",
            ),
            ApiErrorId.ERR_BUYOUT_CONFLICT.value,
            409,
        )

        following_week = validate_success(
            _hold_booking(
                client,
                season["id"],
                cabin_b["id"],
                adult_three["id"],
                [party_member(adult_three["id"])],
                arrival_date="2026-10-18",
                departure_date="2026-10-25",
            ),
            201,
        )
        assert following_week["booking_status"] == "HELD"
        assert following_week["arrival_date"] == "2026-10-18"

    def test_check_out_refuses_a_folio_that_is_one_cent_short(self, client):
        """A settlement a single cent light leaves the party checked in and the folio open.

        PRD: "If the resulting `folio_balance_cents` is not exactly zero — whether the party has underpaid or overpaid — the check-out is refused with `ERR_FOLIO_BALANCE_OUTSTANDING` (HTTP 402) and nothing is written."

        Design: Corner/validations/check_out_refuses_a_folio_that_is_one_cent_short
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
                party_member(adult_one["id"]),
                party_member(adult_two["id"]),
                party_member(child["id"], "CHILD"),
            ],
        )
        assert booking["provisional_package_total_cents"] == 1258691
        assert booking["deposit_required_cents"] == FAMILY_CLASSIC_DEPOSIT_CENTS

        get_success_data(
            client.post_payment(
                booking["id"],
                payment_payload(FAMILY_CLASSIC_DEPOSIT_CENTS),
                RESERVATIONS_AGENT,
            )
        )
        confirm_booking(client, booking["id"])

        set_clock_to(client, "2026-10-11T12:00:00Z")
        get_success_data(
            client.check_in_booking(
                booking["id"], check_in_payload(True), RESERVATIONS_AGENT
            )
        )

        set_clock_to(client, "2026-10-18T10:00:00Z")
        validate_error(
            client.check_out_booking(
                booking["id"], check_out_payload(1107647), RESERVATIONS_AGENT
            ),
            ApiErrorId.ERR_FOLIO_BALANCE_OUTSTANDING.value,
            402,
        )

        still_in_house = get_success_data(
            client.get_booking(booking["id"], RESERVATIONS_AGENT)
        )
        assert still_in_house["booking_status"] == "CHECKED_IN"
        assert still_in_house["deposit_paid_cents"] == FAMILY_CLASSIC_DEPOSIT_CENTS
        assert still_in_house["payments_applied_cents"] == 0

        departed = validate_success(
            client.check_out_booking(
                booking["id"], check_out_payload(1107648), RESERVATIONS_AGENT
            )
        )
        assert departed["booking_status"] == "CHECKED_OUT"
        assert departed["realized_nights"] == 7
        assert departed["gratuity_cents"] == 226564
        assert departed["final_folio_total_cents"] == 1485255
        assert departed["folio_balance_cents"] == 0
        assertions.assert_folio_waterfall_consistent(departed)
        assertions.assert_folio_balance_consistent(departed)
