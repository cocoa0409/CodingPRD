"""Two boundaries where one unit either way changes the published state.

The reading ladder compares a tier threshold inclusively, so a reader sitting
exactly on it holds the tier and a reader one unit short holds nothing.  The
close-out gate admits a clock resting exactly on the program's end instant, and
a zero-attendance close-out publishes literal zeroes rather than nulls.
"""

from typing import Any, Dict

from test_helpers.assertions import (
    assert_lot_state,
    assert_one_decimal_pct,
    assert_prize_conservation,
    assert_program_status,
)
from test_helpers.fixtures import LibraryWorld


# ==========================================================================
# The inclusive tier threshold
# ==========================================================================
def _two_readers_at_sixty_and_fifty_nine(world: LibraryWorld) -> Dict[str, Any]:
    """One reader driven to exactly 60 units and one to 59, through one endpoint.

    The lot is the readers' own branch stock and is not a reuse pool, so no
    cross-branch surcharge can blur the money.
    """
    branch = world.branch()
    lot = world.prize_lot(
        branch["id"],
        sku="PRIZE-T1",
        unit_cost_cents=100,
        quantity_procured=10,
        reuse_pool=False,
    )
    opened = world.opened_challenge(
        tiers=[
            {
                "tier_index": 1,
                "threshold_units": 60,
                "prize_sku": "PRIZE-T1",
                "prize_units_per_participant": 1,
            }
        ],
        name="Minutes Matter",
        logging_method="MINUTES",
        unit_label="minute",
        start_on="2026-06-01",
        end_on="2026-08-31",
        correction_policy="HIGH_WATER",
        prize_budget_cents=100000,
    )
    challenge_id = opened["challenge"]["id"]
    at_threshold = world.participant(
        challenge_id, branch["id"], display_name="Reader At", age_band="AGE_5_11"
    )
    below_threshold = world.participant(
        challenge_id, branch["id"], display_name="Reader Below", age_band="AGE_5_11"
    )
    world.log_entry(at_threshold["id"], 60, "2026-07-15")
    world.log_entry(below_threshold["id"], 59, "2026-07-15")
    return {
        "branch": branch,
        "lot": world.read_lot(lot["id"]),
        "challenge": world.read_challenge(challenge_id),
        "tier": world.read_tier(opened["tiers"][0]["id"]),
        "at_threshold": world.read_participant(at_threshold["id"]),
        "below_threshold": world.read_participant(below_threshold["id"]),
        "at_threshold_awards": world.awards_for_participant(at_threshold["id"]),
        "below_threshold_awards": world.awards_for_participant(
            below_threshold["id"]
        ),
    }


class TestTierThresholdInclusiveBoundary:
    """Sixty units earns the tier; fifty-nine earns nothing."""

    def test_exactly_the_threshold_holds_the_tier_and_one_short_holds_nothing(
        self, world: LibraryWorld
    ) -> None:
        """The comparison is less-than-or-equal, so 60 against 60 is a match.

        "`eligible_tier_index` is then the highest `tier_index` among the
        challenge's tiers whose `threshold_units` is less than or equal to
        `cumulative_units`, and 0 when no tier is met; because the comparison is
        "less than or equal", a participant sitting at exactly a tier's threshold
        holds that tier, and one unit short holds nothing."

        Design: Difficulty/boundary_precision_check/tier_threshold_grants_at_exactly_sixty_units_and_withholds_at_fifty_nine
        """
        scenario = _two_readers_at_sixty_and_fifty_nine(world)

        at_threshold = scenario["at_threshold"]
        assert at_threshold["cumulative_units"] == 60
        assert at_threshold["eligible_tier_index"] == 1
        assert at_threshold["awarded_tier_index"] == 1

        below_threshold = scenario["below_threshold"]
        assert below_threshold["cumulative_units"] == 59
        assert below_threshold["eligible_tier_index"] == 0
        assert below_threshold["awarded_tier_index"] == 0

    def test_only_the_reader_on_the_threshold_receives_an_award(
        self, world: LibraryWorld
    ) -> None:
        """One award of 100 cents exists; the reader one unit short has none.

        "Whenever a log entry raises `eligible_tier_index` above the
        participant's `awarded_tier_index`, one `TierAward` is created for *every*
        tier index in between".

        Design: Difficulty/boundary_precision_check/tier_threshold_grants_at_exactly_sixty_units_and_withholds_at_fifty_nine
        """
        scenario = _two_readers_at_sixty_and_fifty_nine(world)

        awards = scenario["at_threshold_awards"]
        assert len(awards) == 1, f"expected exactly one award, got {len(awards)}"
        assert awards[0]["status"] == "RESERVED"
        assert awards[0]["award_total_cents"] == 100

        assert scenario["below_threshold_awards"] == []
        assert scenario["tier"]["award_count"] == 1

    def test_the_single_award_moves_one_unit_and_one_hundred_cents(
        self, world: LibraryWorld
    ) -> None:
        """A strict comparison would leave both the ledger and the lot untouched.

        "the lot moves the award's `units` from `quantity_available` to
        `quantity_reserved`".

        Design: Difficulty/boundary_precision_check/tier_threshold_grants_at_exactly_sixty_units_and_withholds_at_fifty_nine
        """
        scenario = _two_readers_at_sixty_and_fifty_nine(world)

        challenge = scenario["challenge"]
        assert challenge["prize_committed_cents"] == 100
        assert challenge["prize_available_cents"] == 99900
        assert_prize_conservation(challenge)

        assert_lot_state(scenario["lot"], available=9, reserved=1, issued=0)


# ==========================================================================
# The close-out gate exactly at end_utc
# ==========================================================================
def _confirmed_program_closed_out_with_no_attendance(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """Five registered seats, nobody present, and the clock exactly at end_utc."""
    branch = world.branch()
    room = world.room(
        branch["id"],
        room_name="Meeting Room",
        capacity_seats=25,
        min_setup_minutes=15,
        min_teardown_minutes=15,
    )
    program = world.program(
        branch["id"],
        title="Rainy Night Poetry",
        age_group="ADULT",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-12T14:00:00.000Z",
        end_utc="2026-08-12T15:00:00.000Z",
        attendance_target=5,
        attendance_cap=5,
        supply_sku="KIT-POEM",
        supply_units_per_attendee=0,
        materials_budget_cents=5000,
        presenter_fee_budget_cents=0,
    )
    reservation = world.hold(
        program["id"],
        room["id"],
        start_utc="2026-08-12T13:45:00.000Z",
        end_utc="2026-08-12T15:15:00.000Z",
        setup_minutes=15,
        teardown_minutes=15,
    )
    world.confirm_reservation(reservation["id"])
    world.schedule(program["id"])
    world.register(program["id"], registrant_reference="WALKUP-LIST", seats=5)
    world.confirm_program(program["id"])
    world.set_clock("2026-08-12T15:00:00.000Z")
    closed = world.close_out(program["id"], 0, 0, 0)
    return {
        "branch": branch,
        "room": room,
        "program": closed,
        "reservation": reservation,
    }


class TestZeroAttendanceCloseOutAtTheEndInstant:
    """A clock resting on end_utc is admissible, and every rate reads 0.0."""

    def test_a_clock_exactly_at_the_end_instant_admits_the_close_out(
        self, world: LibraryWorld
    ) -> None:
        """The gate is at or after the end instant, so that instant is inside it.

        "it requires the logical clock to be at or after the program's `end_utc`;
        a clock still inside the program's window reports
        `ERR_PROGRAM_NOT_YET_ENDED`, and a clock exactly at `end_utc` is
        admissible."

        Design: Difficulty/boundary_precision_check/close_out_at_exactly_end_utc_with_zero_attendance_yields_zero_point_zero_rates
        """
        program = _confirmed_program_closed_out_with_no_attendance(world)["program"]

        assert_program_status(program, operational_status="CLOSED_OUT")
        assert program["gross_attendance"] == 0

    def test_zero_gross_attendance_publishes_three_literal_zero_rates(
        self, world: LibraryWorld
    ) -> None:
        """No division error and no null: all three percentages read 0.0.

        "A close-out with `gross_attendance` of 0 reports 0.0 for all three
        percentages and never a division error."

        Design: Difficulty/boundary_precision_check/close_out_at_exactly_end_utc_with_zero_attendance_yields_zero_point_zero_rates
        """
        program = _confirmed_program_closed_out_with_no_attendance(world)["program"]

        assert_one_decimal_pct(
            program["attendance_attainment_funder_pct"],
            0.0,
            "attendance_attainment_funder_pct",
        )
        assert_one_decimal_pct(
            program["attendance_attainment_internal_pct"],
            0.0,
            "attendance_attainment_internal_pct",
        )
        assert_one_decimal_pct(
            program["survey_response_rate_pct"], 0.0, "survey_response_rate_pct"
        )

    def test_the_whole_registered_count_becomes_the_no_show_count(
        self, world: LibraryWorld
    ) -> None:
        """Nobody verified means all five registrants are no-shows.

        "`no_show_count` is `registered_count` less
        `verified_registrant_attendance`, with a floor of 0".

        Design: Difficulty/boundary_precision_check/close_out_at_exactly_end_utc_with_zero_attendance_yields_zero_point_zero_rates
        """
        program = _confirmed_program_closed_out_with_no_attendance(world)["program"]

        assert program["registered_count"] == 5
        assert program["verified_registrant_attendance"] == 0
        assert program["no_show_count"] == 5
        assert program["confirmed_room_capacity"] == 25
        assert program["materials_spent_cents"] == 0
        assert program["materials_available_cents"] == 5000
