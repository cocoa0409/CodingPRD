"""Every published formula probed at the point where it changes its answer.

The interesting value of a rate is the subtotal at which it inverts; the
interesting value of a waterfall is the lot it declines to draw from; the
interesting value of a validity window is the day it lapses.  Each test here
pins one such point and states the arithmetic that produced it.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED,
    ERR_SUPPLY_INVENTORY_INSUFFICIENT,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_award_pricing,
    assert_budget_variance_and_posture,
    assert_contract_fee_breakdown,
    assert_date_equals,
    assert_instant_equals,
    assert_lot_state,
    assert_materials_conservation,
    assert_prize_conservation,
    assert_program_status,
    assert_supply_draw_lines,
)
from test_helpers.factories import log_entry_payload
from test_helpers.fixtures import LibraryWorld


def _scheduled_program_on_its_own_hour(
    world: LibraryWorld,
    branch_id: str,
    room_id: str,
    *,
    title: str,
    start_utc: str,
    end_utc: str,
    attendance_target: int,
    attendance_cap: int = 50,
    **program_kwargs: Any,
) -> Dict[str, Any]:
    """Draft a program, confirm a zero-buffer booking over its window and publish it."""
    program = world.program(
        branch_id,
        title=title,
        start_utc=start_utc,
        end_utc=end_utc,
        attendance_target=attendance_target,
        attendance_cap=attendance_cap,
        **program_kwargs,
    )
    reservation = world.hold(
        program["id"],
        room_id,
        start_utc=start_utc,
        end_utc=end_utc,
        setup_minutes=0,
        teardown_minutes=0,
    )
    world.confirm_reservation(reservation["id"])
    world.schedule(program["id"])
    return {"program": program, "reservation": reservation}


class TestMaterialsCommitmentAndSupplyDraw:
    """The contingency inversion, the two-bucket waterfall and the invisible lot."""

    def test_the_larger_draw_commits_less_because_the_rate_inverts(
        self, world: LibraryWorld
    ) -> None:
        """Nineteen thousand five hundred commits 21450; twenty thousand commits 21000.

        "a draw subtotal *below* 20000 cents carries a 10 percent contingency,
        while a subtotal of 20000 cents or more carries only 5 percent, because
        small kits are the ones whose costs move unpredictably."

        Design: Corner/calculations/materials_contingency_rate_flips_at_a_draw_subtotal_of_exactly_twenty_thousand
        """
        branch = world.branch()
        room = world.room(
            branch["id"], min_setup_minutes=0, min_teardown_minutes=0
        )
        lot = world.supply_lot(
            branch["id"], unit_cost_cents=500, quantity_procured=100
        )
        below = _scheduled_program_on_its_own_hour(
            world,
            branch["id"],
            room["id"],
            title="Afternoon Craft",
            start_utc="2026-08-12T14:00:00.000Z",
            end_utc="2026-08-12T15:00:00.000Z",
            attendance_target=39,
        )
        at_threshold = _scheduled_program_on_its_own_hour(
            world,
            branch["id"],
            room["id"],
            title="Evening Craft",
            start_utc="2026-08-12T16:00:00.000Z",
            end_utc="2026-08-12T17:00:00.000Z",
            attendance_target=40,
        )

        first = world.confirm_program(below["program"]["id"])
        second = world.confirm_program(at_threshold["program"]["id"])

        assert first["materials_committed_cents"] == 21450
        assert first["materials_available_cents"] == 28550
        assert_materials_conservation(first)
        assert_supply_draw_lines(
            first, [{"units": 39, "line_total_cents": 19500, "surcharge_cents": 0}]
        )

        assert second["materials_committed_cents"] == 21000
        assert second["materials_available_cents"] == 29000
        assert_materials_conservation(second)
        assert_supply_draw_lines(
            second, [{"units": 40, "line_total_cents": 20000, "surcharge_cents": 0}]
        )

        assert_lot_state(
            world.read_lot(lot["id"]), available=21, reserved=79, issued=0
        )

    def test_the_draw_empties_the_home_lot_before_touching_a_shareable_one(
        self, world: LibraryWorld
    ) -> None:
        """Two lines in bucket order, and the surcharge rounded on the second alone.

        "Those units are drawn from `SUPPLY` lots whose `sku` equals the program's
        `supply_sku` and whose `status` is `ACTIVE`, considered in a strict
        two-bucket order: first the lots belonging to the program's own
        `branch_id`, oldest `created_at` first; then the lots of *other* branches
        whose `reuse_pool` is true, again oldest `created_at` first."

        Design: Corner/calculations/supply_draw_walks_home_branch_lots_before_cross_branch_reuse_lots
        """
        home = world.branch(name="Central Library", branch_code="CEN")
        other = world.branch(name="East Library", branch_code="EAST")
        room = world.room(home["id"], min_setup_minutes=0, min_teardown_minutes=0)
        home_lot = world.supply_lot(
            home["id"], unit_cost_cents=250, quantity_procured=15, reuse_pool=False
        )
        shareable_lot = world.supply_lot(
            other["id"], unit_cost_cents=300, quantity_procured=25, reuse_pool=True
        )
        hoarded_lot = world.supply_lot(
            other["id"], unit_cost_cents=100, quantity_procured=100, reuse_pool=False
        )
        scheduled = _scheduled_program_on_its_own_hour(
            world,
            home["id"],
            room["id"],
            title="Craft Hour",
            start_utc="2026-08-12T14:00:00.000Z",
            end_utc="2026-08-12T15:00:00.000Z",
            attendance_target=40,
        )

        confirmed = world.confirm_program(scheduled["program"]["id"])

        assert_supply_draw_lines(
            confirmed,
            [
                {
                    "lot_id": home_lot["id"],
                    "units": 15,
                    "unit_cost_cents": 250,
                    "surcharge_cents": 0,
                    "line_total_cents": 3750,
                },
                {
                    "lot_id": shareable_lot["id"],
                    "units": 25,
                    "unit_cost_cents": 300,
                    "surcharge_cents": 600,
                    "line_total_cents": 8100,
                },
            ],
        )
        assert confirmed["materials_committed_cents"] == 13035
        assert confirmed["materials_available_cents"] == 36965
        assert_materials_conservation(confirmed)

        assert_lot_state(
            world.read_lot(home_lot["id"]),
            available=0,
            reserved=15,
            issued=0,
            status="DEPLETED",
        )
        assert_lot_state(
            world.read_lot(shareable_lot["id"]),
            available=0,
            reserved=25,
            issued=0,
            status="DEPLETED",
        )
        assert_lot_state(
            world.read_lot(hoarded_lot["id"]), available=100, reserved=0, issued=0
        )

    def test_a_cheaper_unshared_lot_at_another_branch_cannot_rescue_the_draw(
        self, world: LibraryWorld
    ) -> None:
        """A hundred units exist and none of them are candidates, so nothing is drawn.

        "A lot at another branch whose `reuse_pool` is false is never a candidate
        no matter how much stock it holds." "the confirmation is refused with
        `ERR_SUPPLY_INVENTORY_INSUFFICIENT` and **nothing is allocated**".

        Design: Corner/calculations/cross_branch_non_reuse_lots_are_invisible_to_the_supply_draw
        """
        home = world.branch(name="Central Library", branch_code="CEN")
        other = world.branch(name="East Library", branch_code="EAST")
        room = world.room(home["id"], min_setup_minutes=0, min_teardown_minutes=0)
        hoarded_lot = world.supply_lot(
            other["id"], unit_cost_cents=100, quantity_procured=100, reuse_pool=False
        )
        scheduled = _scheduled_program_on_its_own_hour(
            world,
            home["id"],
            room["id"],
            title="Craft Hour",
            start_utc="2026-08-12T14:00:00.000Z",
            end_utc="2026-08-12T15:00:00.000Z",
            attendance_target=10,
        )

        response = world.api.confirm_program(
            scheduled["program"]["id"], world.manager
        )
        validate_error(
            response,
            ERR_SUPPLY_INVENTORY_INSUFFICIENT,
            ERROR_HTTP_STATUS[ERR_SUPPLY_INVENTORY_INSUFFICIENT],
        )

        program = world.read_program(scheduled["program"]["id"])
        assert_program_status(program, operational_status="SCHEDULED")
        assert_supply_draw_lines(program, [])
        assert program["materials_committed_cents"] == 0

        assert_lot_state(
            world.read_lot(hoarded_lot["id"]), available=100, reserved=0, issued=0
        )


class TestContractPricingBoundaries:
    """The mileage bands, the rider window and the posture that follows the total."""

    def test_sixty_one_miles_splits_across_the_bands_and_twenty_miles_pays_nothing(
        self, world: LibraryWorld
    ) -> None:
        """Forty miles at 65 plus one mile at 45, against a free allowance of twenty.

        "the first band's billable mileage is the round-trip mileage capped at 60
        and then reduced by 20, treated as zero if that would be negative; the
        second band's billable mileage is the round-trip mileage reduced by 60,
        likewise treated as zero if negative; and `travel_fee_cents` is the first
        band's mileage multiplied by 65 plus the second band's mileage multiplied
        by 45. A 20-mile round trip reimburses nothing, 21 miles reimburses 65, 60
        miles reimburses 2600, and 61 miles reimburses 2645."

        Design: Corner/calculations/travel_fee_straddles_the_sixty_mile_tier_and_is_zero_at_exactly_twenty_miles
        """
        branch = world.branch()
        program = world.program(
            branch["id"],
            title="Adult Book Club",
            age_group="ADULT",
            start_utc="2026-08-12T18:00:00.000Z",
            end_utc="2026-08-12T19:00:00.000Z",
            attendance_target=20,
            attendance_cap=25,
        )
        far = world.presenter(legal_name="Fen Alvarez")
        near = world.presenter(legal_name="Nia Bellamy")
        far_contract = world.contract(far["id"], program["id"], 61)
        near_contract = world.contract(near["id"], program["id"], 20)
        world.offer(far_contract["id"], 50000, world.manager)
        world.offer(near_contract["id"], 50000, world.manager)

        executed_far = world.execute(far_contract["id"], world.second_manager)
        executed_near = world.execute(near_contract["id"], world.second_manager)

        assert_contract_fee_breakdown(
            executed_far,
            agreed_fee_cents=50000,
            travel_fee_cents=2645,
            escort_fee_cents=0,
            insurance_rider_fee_cents=0,
            weekend_premium_cents=0,
            total_fee_cents=52645,
        )
        assert_contract_fee_breakdown(
            executed_near,
            agreed_fee_cents=50000,
            travel_fee_cents=0,
            escort_fee_cents=0,
            insurance_rider_fee_cents=0,
            weekend_premium_cents=0,
            total_fee_cents=50000,
        )
        assert executed_far["status"] == "EXECUTED"
        assert executed_near["status"] == "EXECUTED"

        after = world.read_program(program["id"])
        assert after["presenter_fee_committed_cents"] == 102645
        assert_budget_variance_and_posture(after, 147355, "WITHIN_BUDGET")

    def test_the_rider_fires_one_day_inside_the_window_and_not_on_its_edge(
        self, world: LibraryWorld
    ) -> None:
        """Both certificates outlive the program; only one lapses inside the window.

        "`insurance_rider_fee_cents` is 2500 when the presenter's
        `insurance_certificate_expires_on` falls strictly earlier than the calendar
        date 30 days after the program's end date — that is, when the certificate
        will lapse inside a 30-day window following the program — and 0 otherwise."

        Design: Corner/calculations/insurance_rider_fires_one_day_inside_the_thirty_day_window
        """
        branch = world.branch()
        program = world.program(
            branch["id"],
            title="Adult Book Club",
            age_group="ADULT",
            start_utc="2026-08-12T14:00:00.000Z",
            end_utc="2026-08-12T15:00:00.000Z",
            attendance_target=20,
            attendance_cap=25,
        )
        inside = world.presenter(
            legal_name="Ines Duarte",
            insurance_certificate_expires_on="2026-09-10",
        )
        on_edge = world.presenter(
            legal_name="Otto Grimaldi",
            insurance_certificate_expires_on="2026-09-11",
        )
        inside_contract = world.contract(inside["id"], program["id"], 20)
        edge_contract = world.contract(on_edge["id"], program["id"], 20)
        world.offer(inside_contract["id"], 50000, world.manager)
        world.offer(edge_contract["id"], 50000, world.manager)

        executed_inside = world.execute(inside_contract["id"], world.second_manager)
        executed_edge = world.execute(edge_contract["id"], world.second_manager)

        assert_contract_fee_breakdown(
            executed_inside,
            agreed_fee_cents=50000,
            travel_fee_cents=0,
            escort_fee_cents=0,
            insurance_rider_fee_cents=2500,
            weekend_premium_cents=0,
            total_fee_cents=52500,
        )
        assert_contract_fee_breakdown(
            executed_edge,
            agreed_fee_cents=50000,
            travel_fee_cents=0,
            escort_fee_cents=0,
            insurance_rider_fee_cents=0,
            weekend_premium_cents=0,
            total_fee_cents=50000,
        )

        assert world.read_program(program["id"])[
            "presenter_fee_committed_cents"
        ] == 102500

    def test_an_overrun_inside_the_fee_cap_is_recorded_rather_than_refused(
        self, world: LibraryWorld
    ) -> None:
        """The posture flips, the branch counter rises and the execution still succeeds.

        "if that re-derivation flips the posture from `WITHIN_BUDGET` to
        `OVER_BUDGET`, the owning branch's `programs_over_budget_count` increases
        by 1." "`total_fee_cents` is compared against a ceiling that is the smaller
        of a system-wide cap of 250000 cents and the owning branch's
        `per_program_fee_cap_cents`".

        Design: Corner/calculations/budget_posture_flips_over_budget_and_increments_the_branch_counter
        """
        branch = world.branch(per_program_fee_cap_cents=150000)
        program = world.program(
            branch["id"],
            title="Adult Book Club",
            age_group="ADULT",
            start_utc="2026-08-12T18:00:00.000Z",
            end_utc="2026-08-12T19:00:00.000Z",
            attendance_target=20,
            attendance_cap=25,
            materials_budget_cents=12000,
            presenter_fee_budget_cents=100000,
        )
        presenter = world.presenter()
        contract = world.contract(presenter["id"], program["id"], 21)
        world.offer(contract["id"], 120000, world.manager)

        executed = get_success_data(
            world.api.execute_contract(contract["id"], world.second_manager), 200
        )

        assert_contract_fee_breakdown(
            executed,
            agreed_fee_cents=120000,
            travel_fee_cents=65,
            escort_fee_cents=0,
            insurance_rider_fee_cents=0,
            weekend_premium_cents=0,
            total_fee_cents=120065,
        )

        after = world.read_program(program["id"])
        assert after["presenter_fee_committed_cents"] == 120065
        assert_budget_variance_and_posture(after, -8065, "OVER_BUDGET")

        assert world.read_branch(branch["id"])["programs_over_budget_count"] == 1


class TestPrizeAllocationAndTheProgressLedger:
    """The prize waterfall keyed on the reader's home branch, and the daily cap."""

    def test_the_first_reader_takes_the_dearer_home_lot_and_the_second_pays_a_surcharge(
        self, world: LibraryWorld
    ) -> None:
        """Home stock comes first even when a cheaper shareable lot exists elsewhere.

        "The candidates are ordered in two buckets exactly as the supply draw is:
        first the lots belonging to the participant's `home_branch_id`, oldest
        `created_at` first, then the lots of other branches whose `reuse_pool` is
        true, oldest `created_at` first. Other branches' non-reuse lots are never
        candidates."

        Design: Corner/calculations/prize_award_prefers_the_home_branch_lot_over_a_cheaper_cross_branch_reuse_lot
        """
        home = world.branch(name="Central Library", branch_code="CEN")
        other = world.branch(name="East Library", branch_code="EAST")
        home_lot = world.prize_lot(
            home["id"],
            sku="MEDAL",
            unit_cost_cents=500,
            quantity_procured=1,
            reuse_pool=False,
        )
        far_lot = world.prize_lot(
            other["id"],
            sku="MEDAL",
            unit_cost_cents=400,
            quantity_procured=5,
            reuse_pool=True,
        )
        opened = world.opened_challenge(
            tiers=[
                {
                    "tier_index": 1,
                    "threshold_units": 5,
                    "prize_sku": "MEDAL",
                    "prize_units_per_participant": 1,
                }
            ],
            logging_method="BOOKS",
            unit_label="books",
        )
        challenge_id = opened["challenge"]["id"]
        first_reader = world.participant(
            challenge_id, home["id"], display_name="Ada L.", age_band="AGE_5_11"
        )
        second_reader = world.participant(
            challenge_id, home["id"], display_name="Ben O.", age_band="AGE_5_11"
        )

        world.log_entry(first_reader["id"], 5, "2026-08-01")
        world.log_entry(second_reader["id"], 5, "2026-08-01")

        _, meta = validate_paginated(world.api.list_tier_awards(world.manager))
        assert meta["total_count"] == 2

        first_awards = world.awards_for_participant(first_reader["id"])
        assert len(first_awards) == 1
        assert_award_pricing(
            first_awards[0],
            units=1,
            unit_cost_cents=500,
            transfer_surcharge_cents=0,
            status="RESERVED",
            lot_id=home_lot["id"],
        )

        second_awards = world.awards_for_participant(second_reader["id"])
        assert len(second_awards) == 1
        assert_award_pricing(
            second_awards[0],
            units=1,
            unit_cost_cents=400,
            transfer_surcharge_cents=32,
            status="RESERVED",
            lot_id=far_lot["id"],
        )

        assert_lot_state(
            world.read_lot(home_lot["id"]),
            available=0,
            reserved=1,
            issued=0,
            status="DEPLETED",
        )
        assert_lot_state(
            world.read_lot(far_lot["id"]), available=4, reserved=1, issued=0
        )

        challenge = world.read_challenge(challenge_id)
        assert challenge["prize_committed_cents"] == 932
        assert challenge["prize_available_cents"] == 9068
        assert_prize_conservation(challenge)

        tier = world.read_tier(opened["tiers"][0]["id"])
        assert tier["award_count"] == 2
        assert tier["deferred_count"] == 0

    def test_a_backdated_entry_raises_the_total_without_spending_another_day_s_allowance(
        self, world: LibraryWorld
    ) -> None:
        """Thirty minutes filed later but dated earlier leaves 2026-08-05 untouched.

        "The cap is per date, not per entry and not per challenge: three separate
        100-minute entries on one date are fine, a fourth is not, and the same
        three entries spread across three dates are never in tension."

        Design: Corner/calculations/progress_ledger_sums_backdated_entries_and_caps_per_logged_on_date
        """
        world.set_clock("2026-08-10T12:00:00.000Z")
        branch = world.branch()
        opened = world.opened_challenge(
            tiers=[
                {
                    "tier_index": 1,
                    "threshold_units": 5000,
                    "prize_sku": "MEDAL",
                    "prize_units_per_participant": 1,
                }
            ]
        )
        participant = world.participant(
            opened["challenge"]["id"],
            branch["id"],
            display_name="Ada L.",
            age_band="AGE_5_11",
        )
        world.log_entry(participant["id"], 20, "2026-08-05")
        world.log_entry(participant["id"], 30, "2026-07-20")

        before = world.read_participant(participant["id"])
        assert before["cumulative_units"] == 50
        assert before["entry_count"] == 2
        assert before["eligible_tier_index"] == 0
        assert before["awarded_tier_index"] == 0

        third = get_success_data(
            world.api.create_log_entry(
                participant["id"],
                log_entry_payload(280, "2026-08-05", "STAFF_DESK"),
                world.coordinator,
            ),
            201,
        )
        assert third["entry_type"] == "LOG"
        assert third["units"] == 280
        assert_date_equals(third["logged_on"], "2026-08-05", "logged_on")

        after = world.read_participant(participant["id"])
        assert after["cumulative_units"] == 330
        assert after["entry_count"] == 3

        _, meta = validate_paginated(
            world.api.list_log_entries(
                world.coordinator, participant_id=participant["id"]
            )
        )
        assert meta["total_count"] == 3


class TestDateAndIntervalArithmetic:
    """Calendar spans and interval endpoints, each read at its exact edge."""

    def test_a_fingerprint_decision_stays_active_through_its_final_day(
        self, world: LibraryWorld
    ) -> None:
        """Seven hundred thirty days from 2026-07-01 lands on 2028-06-30.

        "a `NAME_CHECK` decision is good for 365 days and a `FINGERPRINT`
        decision for 730 days, counted forward from `screening_decided_on` as whole
        calendar days, and the result is stored as the ISO date
        `screening_valid_until`."

        Design: Corner/calculations/fingerprint_screening_validity_spans_seven_hundred_thirty_days_across_a_leap_day
        """
        presenter = world.presenter()
        world.request_screening(presenter["id"], screening_tier="FINGERPRINT")
        decided = world.screening_result(presenter["id"], "CLEAR", "2026-07-01")

        assert decided["screening_decision"] == "CLEAR"
        assert_date_equals(
            decided["screening_valid_until"], "2028-06-30", "screening_valid_until"
        )

        world.set_clock("2028-06-30T23:59:59.000Z")
        on_the_last_day = world.read_presenter(presenter["id"])
        assert on_the_last_day["screening_status"] == "ACTIVE"
        assert on_the_last_day["screening_decision"] == "CLEAR"

        world.set_clock("2028-07-01T00:00:00.000Z")
        the_day_after = world.read_presenter(presenter["id"])
        assert the_day_after["screening_status"] == "EXPIRED"
        assert the_day_after["screening_decision"] == "CLEAR"

    def test_a_peer_that_only_touches_the_boundary_instant_still_consumes_staff(
        self, world: LibraryWorld
    ) -> None:
        """One program ending at 15:00 blocks a second one starting at 15:00.

        "The load is computed over the program's **public window**, which runs
        from `start_utc` to `end_utc` with no setup or teardown buffers at all and,
        as section 2.11 records, is **closed** at both ends."

        Design: Corner/calculations/branch_overlap_load_counts_a_peer_that_only_touches_at_the_boundary_instant
        """
        branch = world.branch(overlapping_program_capacity=1)
        room = world.room(
            branch["id"],
            room_name="Story Room",
            capacity_seats=60,
            min_setup_minutes=0,
            min_teardown_minutes=0,
        )
        lot = world.supply_lot(
            branch["id"],
            sku="CRAFT-KIT",
            unit_cost_cents=250,
            quantity_procured=100,
            reuse_pool=False,
        )
        early = _scheduled_program_on_its_own_hour(
            world,
            branch["id"],
            room["id"],
            title="Craft Hour",
            start_utc="2026-08-12T14:00:00.000Z",
            end_utc="2026-08-12T15:00:00.000Z",
            attendance_target=10,
        )
        confirmed_early = world.confirm_program(early["program"]["id"])
        assert confirmed_early["materials_committed_cents"] == 2750

        late = _scheduled_program_on_its_own_hour(
            world,
            branch["id"],
            room["id"],
            title="Craft Hour Encore",
            start_utc="2026-08-12T15:00:00.000Z",
            end_utc="2026-08-12T16:00:00.000Z",
            attendance_target=10,
        )

        error = validate_error(
            world.api.confirm_program(late["program"]["id"], world.manager),
            ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED,
            ERROR_HTTP_STATUS[ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED],
        )
        assert error["error_id"] == ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED

        first_booking = world.read_reservation(early["reservation"]["id"])
        assert first_booking["status"] == "CONFIRMED"
        assert_instant_equals(
            first_booking["occupancy_start_utc"],
            "2026-08-12T14:00:00.000Z",
            "occupancy_start_utc",
        )
        assert_instant_equals(
            first_booking["occupancy_end_utc"],
            "2026-08-12T15:00:00.000Z",
            "occupancy_end_utc",
        )

        second_booking = world.read_reservation(late["reservation"]["id"])
        assert second_booking["status"] == "CONFIRMED"
        assert_instant_equals(
            second_booking["occupancy_start_utc"],
            "2026-08-12T15:00:00.000Z",
            "occupancy_start_utc",
        )
        assert_instant_equals(
            second_booking["occupancy_end_utc"],
            "2026-08-12T16:00:00.000Z",
            "occupancy_end_utc",
        )

        refused = world.read_program(late["program"]["id"])
        assert_program_status(refused, operational_status="SCHEDULED")
        assert_supply_draw_lines(refused, [])
        assert refused["materials_committed_cents"] == 0
        assert_materials_conservation(refused)

        assert world.read_lot(lot["id"])["quantity_reserved"] == 10

    def test_a_wheelchair_layout_floors_sixty_one_seats_down_to_fifty_one(
        self, world: LibraryWorld
    ) -> None:
        """Eighty-five hundredths of 61 is 51.85, which floors to 51.

        "the effective figure is the room's `capacity_seats` multiplied by the
        remaining eighty-five hundredths, then taken down to the next whole seat by
        flooring — a 60-seat room yields 51 effective seats, and so does a 61-seat
        room."

        Design: Corner/calculations/wheelchair_layout_floors_effective_capacity_at_fifty_one_of_sixty_one_seats
        """
        branch = world.branch()
        room = world.room(
            branch["id"],
            room_name="Accessible Hall",
            capacity_seats=61,
            min_setup_minutes=15,
            min_teardown_minutes=15,
            accessibility_features=["WHEELCHAIR_ACCESSIBLE"],
        )
        program = world.program(
            branch["id"],
            title="Wheelchair Story Time",
            attendance_target=10,
            attendance_cap=55,
            accessibility_accommodations=["WHEELCHAIR_LAYOUT"],
        )
        reservation = world.hold(
            program["id"], room["id"], setup_minutes=30, teardown_minutes=15
        )

        assert reservation["effective_capacity_seats"] == 51
        assert_instant_equals(
            reservation["occupancy_start_utc"],
            "2026-08-12T13:30:00.000Z",
            "occupancy_start_utc",
        )
        assert_instant_equals(
            reservation["occupancy_end_utc"],
            "2026-08-12T15:15:00.000Z",
            "occupancy_end_utc",
        )

        confirmed = world.confirm_reservation(reservation["id"])
        assert confirmed["effective_capacity_seats"] == 51
        assert world.read_program(program["id"])["confirmed_room_capacity"] == 51
        assert world.read_room(room["id"])["capacity_seats"] == 61
