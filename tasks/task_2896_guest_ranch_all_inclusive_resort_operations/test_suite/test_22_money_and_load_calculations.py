"""Package pricing, folio settlement, season rollup, herd load and staffing
projections — the arithmetic the ranch performs on money, hours and ranks."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions, constants
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    check_in_payload,
    check_out_payload,
    complete_slot_payload,
    create_activity_slot_payload,
    create_booking_payload,
    evaluate_assessment_payload,
    guide_assignment_payload,
    health_event_payload,
    mount_assignment_payload,
    party_member,
    payment_payload,
    reservation_payload,
    rider_assessment_payload,
)
from test_helpers.fixtures import (
    assign_guide,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_in_season,
    build_open_season,
    build_ready_rider,
    confirm_booking,
    open_slot,
    set_clock_to,
    sign_guest_waiver,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
    make_activity_guide_headers,
)

SOLO_CLASSIC_DEPOSIT_CENTS = 143850
FAMILY_CLASSIC_DEPOSIT_CENTS = 377607


def _pay_exact_deposit(client, booking_id, amount_cents):
    """Post the deposit the recipe names, rather than a recomputed figure."""
    return get_success_data(
        client.post_payment(booking_id, payment_payload(amount_cents), RESERVATIONS_AGENT)
    )


def _confirmed_booking(client, season_id, cabin_id, members, deposit_cents, **overrides):
    booking = build_booking(client, season_id, cabin_id, members, **overrides)
    _pay_exact_deposit(client, booking["id"], deposit_cents)
    return confirm_booking(client, booking["id"])


def _slot(client, season_id, **overrides):
    return get_success_data(
        client.create_activity_slot(
            season_id, create_activity_slot_payload(**overrides), RANCH_MANAGER
        )
    )


def _read_slot(client, slot_id):
    return get_success_data(client.get_activity_slot(slot_id, RANCH_MANAGER))


def _read_horse(client, horse_id):
    return get_success_data(client.get_horse(horse_id, HORSE_PROGRAM_DIRECTOR))


class TestWeeklyPackagePricing:
    """The hold-time price list: member lines, buyout premium and deposit."""

    def test_buyout_week_for_six_on_the_signature_tier(self, client):
        """A six-person SIGNATURE buyout week adds the premium and takes 30 percent as deposit.

        PRD: "When `is_buyout` is true, a buyout premium equal to the subtotal multiplied by the season's `buyout_premium_pct`, rounded half up to whole cents, is added to the subtotal; when it is false the premium is zero."

        Design: Corner/calculations/buyout_package_total_and_deposit_for_a_six_person_signature_week
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(
            client,
            package_tiers=[dict(constants.TIER_CLASSIC), dict(constants.TIER_SIGNATURE)],
        )
        cabin = build_cabin(client, name="Lodge", bed_capacity=6)

        adults = [
            build_guest(client, "Ann Adult", "1985-04-02", 165),
            build_guest(client, "Ben Adult", "1983-07-11", 190),
            build_guest(client, "Cy Adult", "1979-02-09", 175),
            build_guest(client, "Dee Adult", "1990-01-15", 175),
        ]
        children = [
            build_guest(client, "Cal Child", "2016-05-20", 95),
            build_guest(client, "Fay Child", "2015-03-03", 90),
        ]
        members = [party_member(guest["id"]) for guest in adults] + [
            party_member(guest["id"], "CHILD") for guest in children
        ]

        booking = validate_success(
            client.create_booking(
                create_booking_payload(
                    season["id"],
                    cabin["id"],
                    adults[0]["id"],
                    members,
                    package_tier_code="SIGNATURE",
                    arrival_date=constants.ARRIVAL_DATE,
                    departure_date=constants.DEPARTURE_DATE,
                    is_buyout=True,
                ),
                RESERVATIONS_AGENT,
            ),
            201,
        )

        assertions.assert_booking(booking)
        assert booking["party_size"] == 6
        assert booking["adult_count"] == 4
        assert booking["child_count"] == 2
        assert booking["nights"] == 7
        assert booking["is_buyout"] is True
        assert booking["provisional_package_total_cents"] == 4073300
        assert booking["deposit_required_cents"] == 1221990

    def test_fourteen_night_stay_lands_in_the_deepest_discount_band(self, client):
        """A fourteen-night family stay earns the deepest length-of-stay discount.

        PRD: "The length-of-stay discount band is chosen from the same `nights` figure used everywhere else in the calculation: a stay of seven nights or fewer earns no discount, a stay of eight through thirteen nights earns a 5 percent discount, and a stay of fourteen nights or more earns an 8 percent discount."

        Design: Corner/calculations/fourteen_night_stay_lands_in_the_deepest_length_of_stay_band
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        child = build_guest(client, "Cal Child", "2016-05-20", 95)
        members = [
            party_member(adult_one["id"]),
            party_member(adult_two["id"]),
            party_member(child["id"], "CHILD"),
        ]

        booking = validate_success(
            client.create_booking(
                create_booking_payload(
                    season["id"],
                    cabin["id"],
                    adult_one["id"],
                    members,
                    package_tier_code="CLASSIC",
                    arrival_date="2026-10-11",
                    departure_date="2026-10-25",
                ),
                RESERVATIONS_AGENT,
            ),
            201,
        )

        assert booking["nights"] == 14
        assert booking["provisional_package_total_cents"] == 2315991
        assert booking["deposit_required_cents"] == 694797


class TestFolioSettlementAndSeasonRollup:
    """Departure re-prices the stay, and the annual close reserves capital."""

    def test_folio_caps_the_activity_credit_and_charges_the_no_show(self, client):
        """A hiker who never reached the trailhead is billed a no-show and capped credit.

        PRD: "`activity_credit_applied_cents` becomes the smaller of that ceiling and `activity_surcharge_total_cents`, so the credit never pays out more than the party actually incurred."

        Design: Corner/calculations/folio_waterfall_caps_the_credit_and_charges_the_no_show
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        child = build_guest(client, "Cal Child", "2016-05-20", 95)
        sign_guest_waiver(client, adult_one["id"])

        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [
                party_member(adult_one["id"]),
                party_member(adult_two["id"]),
                party_member(child["id"], "CHILD"),
            ],
            FAMILY_CLASSIC_DEPOSIT_CENTS,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )

        guide = build_active_guide(
            client,
            season["id"],
            full_name="Gus Guide",
            certifications=["WILDERNESS_FIRST_AID"],
            housing_unit_code="BUNKHOUSE-A",
            housing_bunk_number=3,
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
            rider_surcharge_cents=20000,
            mount_required=False,
        )
        seat = take_seat(client, slot["id"], booking["id"], adult_one["id"])
        assign_guide(client, slot["id"], guide["id"], "LEAD")
        open_slot(client, slot["id"])

        set_clock_to(client, "2026-10-11T16:00:00Z")
        get_success_data(
            client.check_in_booking(booking["id"], check_in_payload(True), RESERVATIONS_AGENT)
        )

        guide_headers = make_activity_guide_headers(guide["id"])
        set_clock_to(client, "2026-10-13T15:00:00Z")
        get_success_data(client.run_slot(slot["id"], guide_headers))
        get_success_data(
            client.complete_slot(slot["id"], complete_slot_payload(2.0), guide_headers)
        )

        set_clock_to(client, "2026-10-18T10:00:00Z")
        settled = validate_success(
            client.check_out_booking(
                booking["id"], check_out_payload(1112148), RESERVATIONS_AGENT
            )
        )

        assert settled["booking_status"] == "CHECKED_OUT"
        assert settled["payment_status"] == "PAID_IN_FULL"
        assert settled["realized_nights"] == 7
        assert settled["realized_subtotal_cents"] == 1258691
        assert settled["activity_surcharge_total_cents"] == 20000
        assert settled["activity_credit_applied_cents"] == 20000
        assert settled["no_show_count"] == 1
        assert settled["no_show_penalty_total_cents"] == 4500
        assert settled["gratuity_cents"] == 226564
        assert settled["final_folio_total_cents"] == 1489755
        assert settled["folio_balance_cents"] == 0
        assertions.assert_folio_waterfall_consistent(settled)
        assertions.assert_folio_balance_consistent(settled)

        absent_seat = get_success_data(client.get_reservation(seat["id"], RESERVATIONS_AGENT))
        assert absent_seat["reservation_status"] == "NO_SHOW"

    def test_season_close_reserves_a_quarter_of_the_net_surplus(self, client):
        """Closing the books reserves one quarter of the season's net surplus.

        PRD: "`capital_reserve_cents` becomes one quarter of the net surplus, rounded half up to the nearest cent, where a negative net surplus is first floored at zero so the reserve is never negative."

        Design: Corner/calculations/season_rollup_applies_the_capital_reserve_percentage
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        child = build_guest(client, "Cal Child", "2016-05-20", 95)

        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [
                party_member(adult_one["id"]),
                party_member(adult_two["id"]),
                party_member(child["id"], "CHILD"),
            ],
            FAMILY_CLASSIC_DEPOSIT_CENTS,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )

        set_clock_to(client, "2026-10-11T16:00:00Z")
        get_success_data(
            client.check_in_booking(booking["id"], check_in_payload(True), RESERVATIONS_AGENT)
        )
        set_clock_to(client, "2026-10-18T10:00:00Z")
        settled = get_success_data(
            client.check_out_booking(
                booking["id"], check_out_payload(1107648), RESERVATIONS_AGENT
            )
        )
        assert settled["final_folio_total_cents"] == 1485255

        closed = validate_success(client.advance_season(season["id"], "CLOSED", RANCH_MANAGER))

        assertions.assert_season(closed)
        assert closed["season_status"] == "CLOSED"
        assert closed["gross_package_revenue_cents"] == 1485255
        assert closed["retention_bonus_liability_cents"] == 0
        assert closed["capital_committed_cents"] == 0
        assert closed["net_surplus_cents"] == 1485255
        assert closed["capital_reserve_cents"] == 371314


class TestGuideRequirementInputs:
    """The staffing ratio reads the confirmed seat mix, minors included."""

    def test_cancelling_the_minor_seat_drops_the_two_guide_minimum(self, client):
        """Cancelling the only child's seat lowers the slot's guide requirement.

        PRD: "The third is the minors requirement: a slot carrying at least one rider under 12 years of age demands at least 2 guides, and a slot with no such rider adds nothing on this account."

        Design: Corner/calculations/cancelled_minor_seat_leaves_the_guide_requirement_input_set
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        child = build_guest(client, "Cal Child", "2016-05-20", 95)
        sign_guest_waiver(client, adult_one["id"])
        sign_guest_waiver(client, adult_two["id"])
        sign_guest_waiver(client, child["id"], guardian_guest_id=adult_one["id"])

        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [
                party_member(adult_one["id"]),
                party_member(adult_two["id"]),
                party_member(child["id"], "CHILD"),
            ],
            FAMILY_CLASSIC_DEPOSIT_CENTS,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
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
        take_seat(client, slot["id"], booking["id"], adult_one["id"])
        take_seat(client, slot["id"], booking["id"], adult_two["id"])
        child_seat = take_seat(client, slot["id"], booking["id"], child["id"])

        before = _read_slot(client, slot["id"])
        assertions.assert_slot_counters(
            before, confirmed_rider_count=3, minor_rider_count=1, required_guide_count=2
        )

        cancelled = validate_success(
            client.cancel_reservation(
                child_seat["id"], "the child is unwell", RESERVATIONS_AGENT
            )
        )
        assert cancelled["reservation_status"] == "CANCELLED"

        after = _read_slot(client, slot["id"])
        assertions.assert_slot_counters(
            after, confirmed_rider_count=2, minor_rider_count=0, required_guide_count=1
        )

        child_row = get_success_data(client.get_guest(child["id"], RESERVATIONS_AGENT))
        assert child_row["waiver_signed_by_guardian_guest_id"] == adult_one["id"]


class TestHerdLoadAndAbilityProjection:
    """Scheduled hours, realized hours, duty days and the rank ladder."""

    def test_horse_load_moves_from_the_scheduled_to_the_realized_figure(self, client):
        """A ride that overran contributes its planned hours before and its real hours after.

        PRD: "The two load figures are therefore measures of different things and will legitimately disagree for the same seat: `scheduled_load_hours` sums the planned `duration_hours` over seats currently `ASSIGNED`, while `realized_load_hours` sums the `actual_duration_hours` over seats that reached `COMPLETED`."

        Design: Corner/calculations/horse_load_uses_the_scheduled_variant_before_the_ride_and_realized_after
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        rider = build_ready_rider(
            client, "Ann Adult", "1985-04-02", 165, ability="INTERMEDIATE"
        )

        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(rider["id"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )

        mount = build_horse(client, name="Comet")
        guide = build_active_guide(
            client,
            season["id"],
            full_name="Gus Guide",
            certifications=["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"],
            housing_unit_code="BUNKHOUSE-A",
            housing_bunk_number=3,
        )
        slot = _slot(
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
        seat = take_seat(client, slot["id"], booking["id"], rider["id"])

        horse_row = _read_horse(client, mount["id"])
        get_success_data(
            client.assign_mount(
                seat["id"],
                mount_assignment_payload(mount["id"], horse_row["version"]),
                HORSE_PROGRAM_DIRECTOR,
            )
        )

        before_ride = _read_horse(client, mount["id"])
        assertions.assert_horse_load(
            before_ride, scheduled_load_hours=2.0, realized_load_hours=0.0
        )

        assign_guide(client, slot["id"], guide["id"], "LEAD")
        open_slot(client, slot["id"])

        guide_headers = make_activity_guide_headers(guide["id"])
        set_clock_to(client, "2026-10-12T15:00:00Z")
        get_success_data(client.run_slot(slot["id"], guide_headers))
        get_success_data(client.check_in_reservation(seat["id"], guide_headers))

        validate_success(
            client.complete_slot(slot["id"], complete_slot_payload(2.5), guide_headers)
        )

        after_ride = _read_horse(client, mount["id"])
        assertions.assert_horse_load(
            after_ride, scheduled_load_hours=0.0, realized_load_hours=2.5
        )

        ridden_seat = get_success_data(client.get_reservation(seat["id"], RESERVATIONS_AGENT))
        assert ridden_seat["mount_status"] == "COMPLETED"

    def test_back_dated_verdict_still_wins_once_the_older_ones_are_superseded(self, client):
        """A back-dated third verdict governs because opening it superseded the others.

        PRD: "The starting point is the guest's most recent verdict: among the guest's assessments whose `assessment_status` is `EVALUATED`, the one with the greatest `evaluated_at` is selected, ties being broken by the earlier `created_at`; its `assessed_ability` becomes `current_ability_rank`."

        Design: Corner/calculations/ability_projection_ignores_superseded_assessments_even_when_newer
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        sign_guest_waiver(client, guest["id"])

        def open_and_evaluate(requested, evaluated_at, note):
            current = get_success_data(client.get_guest(guest["id"], RESERVATIONS_AGENT))
            assessment = get_success_data(
                client.create_rider_assessment(
                    guest["id"],
                    rider_assessment_payload(requested, current["version"]),
                    HORSE_PROGRAM_DIRECTOR,
                )
            )
            return assessment, client.evaluate_rider_assessment(
                assessment["id"],
                evaluate_assessment_payload(requested, note, evaluated_at),
                HORSE_PROGRAM_DIRECTOR,
            )

        first, first_response = open_and_evaluate(
            "BEGINNER", "2026-08-01T12:00:00Z", "first ride of the season"
        )
        validate_success(first_response)
        after_first = get_success_data(client.get_guest(guest["id"], RESERVATIONS_AGENT))
        assert after_first["current_ability_rank"] == "BEGINNER"

        second, second_response = open_and_evaluate(
            "ADVANCED", "2026-08-05T12:00:00Z", "rides the steep country cleanly"
        )
        validate_success(second_response)
        after_second = get_success_data(client.get_guest(guest["id"], RESERVATIONS_AGENT))
        assert after_second["current_ability_rank"] == "ADVANCED"

        third, third_response = open_and_evaluate(
            "NOVICE", "2026-08-03T12:00:00Z", "back-dated re-ride after a fall"
        )
        third_row = validate_success(third_response)
        assert third_row["assessment_status"] == "EVALUATED"

        after_third = get_success_data(client.get_guest(guest["id"], RESERVATIONS_AGENT))
        assert after_third["current_ability_rank"] == "NOVICE"
        assert after_third["effective_ability_rank"] == "NOVICE"

        first_row = get_success_data(client.get_rider_assessment(first["id"], RANCH_MANAGER))
        second_row = get_success_data(client.get_rider_assessment(second["id"], RANCH_MANAGER))
        assert first_row["assessment_status"] == "SUPERSEDED"
        assert second_row["assessment_status"] == "SUPERSEDED"
        assert third_row["id"] == third["id"]

    def test_third_same_day_mount_crosses_the_daily_hours_ceiling(self, client):
        """Two rides fill a horse's day, and the third is refused on hours.

        PRD: "A `HorseProgramDirector` attaches a specific animal to a seat by supplying `horse_id` and `expected_horse_version`, and the request is subject to the fullest safety screen in the system, in this order: the version pin must match (`ERR_STALE_HORSE_VERSION`); the seat's `mount_status` must be `PENDING` or `RELEASED` (`ERR_RESERVATION_STATE_INVALID`); the horse's `horse_status` must be `IN_SERVICE` (`ERR_HORSE_NOT_IN_SERVICE`); the guest's `weight_lb` must not exceed the horse's `weight_limit_lb` (`ERR_RIDER_WEIGHT_EXCEEDS_MOUNT`); the rider's `effective_ability_rank` must fall within the band from the horse's `min_rider_ability` to its `max_rider_ability` inclusive (`ERR_MOUNT_ABILITY_MISMATCH`); the horse's `consecutive_duty_days` must be below 5 (`ERR_MOUNT_DUTY_LIMIT`); the horse's already-scheduled hours on the slot's calendar date plus this slot's `duration_hours` must not exceed 4.0 hours (`ERR_MOUNT_DAILY_HOURS_EXCEEDED`); and the animal must clear the recovery-buffer test against each of its other `ASSIGNED` seats (`ERR_MOUNT_INTERVAL_CONFLICT`)."

        Design: Corner/calculations/third_same_day_mount_crosses_the_daily_hours_ceiling
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        rider = build_ready_rider(
            client, "Ann Adult", "1985-04-02", 165, ability="INTERMEDIATE"
        )

        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(rider["id"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )

        mount = build_horse(client, name="Comet")

        windows = [
            ("2026-10-12T08:00:00Z", "2026-10-12T10:00:00Z"),
            ("2026-10-12T11:00:00Z", "2026-10-12T13:00:00Z"),
            ("2026-10-12T14:00:00Z", "2026-10-12T16:00:00Z"),
        ]
        seats = []
        for starts_at, ends_at in windows:
            slot = _slot(
                client,
                season["id"],
                activity_type="TRAIL_RIDE",
                starts_at=starts_at,
                ends_at=ends_at,
                terrain_grade="MEADOW",
                min_ability_rank="BEGINNER",
                capacity=4,
                rider_surcharge_cents=20000,
                mount_required=True,
            )
            seats.append(take_seat(client, slot["id"], booking["id"], rider["id"]))

        first_version = _read_horse(client, mount["id"])["version"]
        first_mount = get_success_data(
            client.assign_mount(
                seats[0]["id"],
                mount_assignment_payload(mount["id"], first_version),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assert first_mount["mount_status"] == "ASSIGNED"
        assertions.assert_horse_load(
            _read_horse(client, mount["id"]), scheduled_load_hours=2.0
        )

        second_version = _read_horse(client, mount["id"])["version"]
        get_success_data(
            client.assign_mount(
                seats[1]["id"],
                mount_assignment_payload(mount["id"], second_version),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assertions.assert_horse_load(
            _read_horse(client, mount["id"]), scheduled_load_hours=4.0
        )

        third_version = _read_horse(client, mount["id"])["version"]
        validate_error(
            client.assign_mount(
                seats[2]["id"],
                mount_assignment_payload(mount["id"], third_version),
                HORSE_PROGRAM_DIRECTOR,
            ),
            ApiErrorId.ERR_MOUNT_DAILY_HOURS_EXCEEDED.value,
            422,
        )

        assertions.assert_horse_load(
            _read_horse(client, mount["id"]), scheduled_load_hours=4.0
        )
        refused_seat = get_success_data(client.get_reservation(seats[2]["id"], RESERVATIONS_AGENT))
        assert refused_seat["mount_status"] == "PENDING"
        assert refused_seat["assigned_horse_id"] is None

    def test_rest_start_resets_the_duty_day_run(self, client):
        """A scheduled rest day zeroes the horse's unbroken run of duty days.

        PRD: "A `REST_START` or `VET_CLEARANCE` event additionally resets `consecutive_duty_days` to 0, because a rested or newly cleared animal begins a fresh run."

        Design: Corner/calculations/rest_start_health_event_resets_the_duty_day_run_to_zero
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_in_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        rider = build_ready_rider(
            client, "Ann Adult", "1985-04-02", 165, ability="INTERMEDIATE"
        )

        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(rider["id"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )

        mount = build_horse(client, name="Comet")
        assert mount["consecutive_duty_days"] == 0

        guide = build_active_guide(
            client,
            season["id"],
            full_name="Gus Guide",
            certifications=["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"],
            housing_unit_code="BUNKHOUSE-A",
            housing_bunk_number=3,
        )
        slot = _slot(
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
        seat = take_seat(client, slot["id"], booking["id"], rider["id"])

        horse_version = _read_horse(client, mount["id"])["version"]
        get_success_data(
            client.assign_mount(
                seat["id"],
                mount_assignment_payload(mount["id"], horse_version),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assign_guide(client, slot["id"], guide["id"], "LEAD")
        open_slot(client, slot["id"])

        guide_headers = make_activity_guide_headers(guide["id"])
        set_clock_to(client, "2026-10-12T15:00:00Z")
        get_success_data(client.run_slot(slot["id"], guide_headers))
        get_success_data(client.check_in_reservation(seat["id"], guide_headers))
        get_success_data(
            client.complete_slot(slot["id"], complete_slot_payload(2.0), guide_headers)
        )

        worked = _read_horse(client, mount["id"])
        assert worked["consecutive_duty_days"] == 1
        assert worked["last_duty_date"] == "2026-10-12"
        assert worked["horse_status"] == "IN_SERVICE"

        event = validate_success(
            client.create_health_event(
                mount["id"],
                health_event_payload("REST_START", "2026-10-13", "scheduled rest day"),
                HORSE_PROGRAM_DIRECTOR,
            ),
            201,
        )
        assertions.assert_horse_health_event(event)
        assert event["event_type"] == "REST_START"

        rested = _read_horse(client, mount["id"])
        assert rested["consecutive_duty_days"] == 0
        assert rested["last_rest_started_on"] == "2026-10-13"
        assert rested["last_duty_date"] == "2026-10-12"
        assert rested["horse_status"] == "REST"


class TestSeasonBedNightsAndReadinessPropagation:
    """Season-wide counters and the slot's derived readiness gate."""

    def test_bed_nights_accumulate_on_confirmation_and_reverse_on_cancellation(self, client):
        """Two confirmations add their bed-nights and a cancellation removes its own.

        PRD: "The season's `bed_nights_sold` counts every booking whose `booking_status` is `CONFIRMED`, `CHECKED_IN` or `CHECKED_OUT`, so a cancellation after confirmation removes the same bed-night figure it added."

        Design: Corner/calculations/season_bed_nights_accumulate_then_reverse_on_cancellation
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        adult_one = build_guest(client, "Ann Adult", "1985-04-02", 165)
        adult_two = build_guest(client, "Ben Adult", "1983-07-11", 190)
        adult_three = build_guest(client, "Cy Adult", "1979-02-09", 175)
        for guest in (adult_one, adult_two, adult_three):
            sign_guest_waiver(client, guest["id"])

        opened = get_success_data(client.get_season(season["id"], RANCH_MANAGER))
        assert opened["bed_nights_sold"] == 0

        booking_a = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(adult_one["id"])],
            264684,
            package_tier_code="CLASSIC",
            arrival_date="2026-09-06",
            departure_date="2026-09-20",
        )
        after_a = get_success_data(client.get_season(season["id"], RANCH_MANAGER))
        assert after_a["bed_nights_sold"] == 14

        booking_b = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(adult_two["id"]), party_member(adult_three["id"])],
            287700,
            package_tier_code="CLASSIC",
            arrival_date="2026-09-20",
            departure_date="2026-09-27",
        )
        after_b = get_success_data(client.get_season(season["id"], RANCH_MANAGER))
        assert after_b["bed_nights_sold"] == 28

        cancelled = validate_success(
            client.cancel_booking(
                booking_b["id"], "the second family called off the trip", RESERVATIONS_AGENT
            )
        )
        assert cancelled["booking_status"] == "CANCELLED"
        assertions.assert_cancellation_split_is_conservative(cancelled)

        after_cancel = get_success_data(client.get_season(season["id"], RANCH_MANAGER))
        assert after_cancel["bed_nights_sold"] == 14

        surviving = get_success_data(client.get_booking(booking_a["id"], RESERVATIONS_AGENT))
        assert surviving["booking_status"] == "CONFIRMED"

    def test_readiness_posture_walks_from_mount_short_to_staffed_ready(self, client):
        """Seating, mounting and staffing a ride walk the posture to its fixed point.

        PRD: "`readiness_posture` is recomputed on every seat, mount or guide change touching the slot, and it takes the first matching value in this precedence order: `FROZEN` whenever the governing season is in any status other than `OPEN` or `IN_SEASON`; otherwise `MOUNT_SHORT` when the slot requires mounts and `mount_assigned_count` is below `confirmed_rider_count`; otherwise `UNDERSTAFFED` when `assigned_guide_count` is below `required_guide_count`; otherwise `STAFFED_READY`."

        Design: Corner/calculations/readiness_posture_propagates_through_mount_then_guide_to_a_fixed_point
        """
        set_clock_to(client, constants.CLOCK_STARTUP_DEFAULT)
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        rider = build_ready_rider(
            client, "Ann Adult", "1985-04-02", 165, ability="INTERMEDIATE"
        )

        booking = _confirmed_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(rider["id"])],
            SOLO_CLASSIC_DEPOSIT_CENTS,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )

        mount = build_horse(client, name="Comet")
        lead = build_active_guide(
            client,
            season["id"],
            full_name="Gus Guide",
            certifications=["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"],
            housing_unit_code="BUNKHOUSE-A",
            housing_bunk_number=3,
        )
        assistant = build_active_guide(
            client,
            season["id"],
            full_name="Hal Wrangler",
            certifications=["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"],
            housing_unit_code="BUNKHOUSE-A",
            housing_bunk_number=4,
        )

        slot = _slot(
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
        assertions.assert_readiness_posture(slot, "STAFFED_READY")
        assertions.assert_slot_counters(slot, seats_available=4)

        seat = validate_success(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], rider["id"], slot["version"]),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        seated = _read_slot(client, slot["id"])
        assertions.assert_readiness_posture(seated, "MOUNT_SHORT")
        assertions.assert_slot_counters(seated, seats_available=3, required_guide_count=1)

        horse_version = _read_horse(client, mount["id"])["version"]
        get_success_data(
            client.assign_mount(
                seat["id"],
                mount_assignment_payload(mount["id"], horse_version),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        mounted = _read_slot(client, slot["id"])
        assertions.assert_readiness_posture(mounted, "UNDERSTAFFED")
        assertions.assert_slot_counters(mounted, mount_assigned_count=1)

        validate_success(
            client.create_guide_assignment(
                slot["id"], guide_assignment_payload(lead["id"], "LEAD"), RANCH_MANAGER
            ),
            201,
        )
        staffed = _read_slot(client, slot["id"])
        assertions.assert_readiness_posture(staffed, "STAFFED_READY")
        assertions.assert_slot_counters(staffed, assigned_guide_count=1)

        validate_success(
            client.create_guide_assignment(
                slot["id"],
                guide_assignment_payload(assistant["id"], "ASSISTANT"),
                RANCH_MANAGER,
            ),
            201,
        )
        over_staffed = _read_slot(client, slot["id"])
        assertions.assert_readiness_posture(over_staffed, "STAFFED_READY")
        assertions.assert_slot_counters(over_staffed, assigned_guide_count=2)
