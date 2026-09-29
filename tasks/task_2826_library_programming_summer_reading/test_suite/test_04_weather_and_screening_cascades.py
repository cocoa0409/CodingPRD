"""Two four-link cascades whose terminal link nothing in the request mentions.

A weather closure prices a kill fee, rewrites the program's committed fee,
re-derives the posture and only then touches the branch roll-up.  A flagged
screening result starts on the presenter and ends by handing supply units back
to two lots and un-confirming a room.
"""

from typing import Any, Dict

from test_helpers.assertions import (
    assert_budget_variance_and_posture,
    assert_lot_state,
    assert_materials_conservation,
    assert_program_status,
    assert_supply_draw_lines,
)
from test_helpers.fixtures import LibraryWorld

ICE_STORM_REASON = "Ice storm — all branches closed"


# ==========================================================================
# The weather-closure money cascade
# ==========================================================================
def _over_budget_scheduled_program(world: LibraryWorld) -> Dict[str, Any]:
    """A scheduled Saturday program whose executed contract put it over budget.

    The branch budget is 72000 cents against a 109753-cent contract, so the
    program's posture has already flipped and the branch counter reads 1.
    """
    branch = world.branch()
    room = world.room(
        branch["id"],
        room_name="Program Room A",
        capacity_seats=40,
        min_setup_minutes=15,
        min_teardown_minutes=15,
    )
    program = world.program(
        branch["id"],
        title="Saturday Science",
        age_group="SCHOOL_AGE",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-15T14:00:00.000Z",
        end_utc="2026-08-15T15:00:00.000Z",
        attendance_target=35,
        attendance_cap=35,
        supply_sku="KIT-SCI",
        supply_units_per_attendee=0,
        materials_budget_cents=12000,
        presenter_fee_budget_cents=60000,
    )
    reservation = world.hold(
        program["id"],
        room["id"],
        start_utc="2026-08-15T13:45:00.000Z",
        end_utc="2026-08-15T15:15:00.000Z",
        setup_minutes=15,
        teardown_minutes=15,
    )
    world.schedule(program["id"])
    presenter = world.presenter(
        legal_name="Ada Reyes",
        insurance_certificate_expires_on="2026-09-10",
        quoted_fee_cents=90000,
    )
    world.clear_screening(presenter["id"], "NAME_CHECK", "2026-07-01")
    contract = world.contract(presenter["id"], program["id"], 75)
    world.offer(contract["id"], 90000, world.coordinator)
    world.execute(contract["id"], world.manager)
    return {
        "branch": branch,
        "room": room,
        "program": world.read_program(program["id"]),
        "reservation": reservation,
        "presenter": presenter,
        "contract": world.read_contract(contract["id"]),
    }


class TestWeatherClosureCascade:
    """From a kill fee to a branch counter in four caused steps."""

    def test_the_program_is_over_budget_before_the_closure(
        self, world: LibraryWorld
    ) -> None:
        """A 109753-cent contract against a 72000-cent budget flips the posture.

        "`budget_posture` is `OVER_BUDGET` when the variance is strictly negative
        and `WITHIN_BUDGET` otherwise, so a variance of exactly 0 is
        `WITHIN_BUDGET`. The owning branch's `programs_over_budget_count` is a
        roll-up of that posture and is adjusted **only when the posture actually
        flips**".

        Design: Difficulty/transitive_cascade/weather_close_cascade_four_links_from_contract_kill_fee_to_branch_counter
        """
        scenario = _over_budget_scheduled_program(world)

        assert_budget_variance_and_posture(scenario["program"], -37753, "OVER_BUDGET")
        assert world.read_branch(scenario["branch"]["id"])[
            "programs_over_budget_count"
        ] == 1

    def test_the_closure_prices_the_kill_fee_at_half_the_executed_total(
        self, world: LibraryWorld
    ) -> None:
        """Thirty-six hours of notice charges half of 109753, rounded half up.

        "When that notice is 48 hours or less, `kill_fee_cents` is one half of
        `total_fee_cents` rounded half up to whole cents; when it is more than 48
        hours, `kill_fee_cents` is 0."

        Design: Difficulty/transitive_cascade/weather_close_cascade_four_links_from_contract_kill_fee_to_branch_counter
        """
        scenario = _over_budget_scheduled_program(world)
        world.set_clock("2026-08-14T02:00:00.000Z")

        closed = world.weather_close(scenario["program"]["id"], ICE_STORM_REASON)
        assert_program_status(closed, operational_status="WEATHER_CLOSED")
        assert closed["closure_reason"] == ICE_STORM_REASON

        contract = world.read_contract(scenario["contract"]["id"])
        assert contract["status"] == "CANCELLED_WEATHER"
        assert contract["kill_fee_cents"] == 54877
        assert contract["total_fee_cents"] == 109753, (
            "the executed total stays on the contract as history"
        )

    def test_the_kill_fee_replaces_the_committed_fee_and_unwinds_the_branch_counter(
        self, world: LibraryWorld
    ) -> None:
        """Links two, three and four run off the single kill fee.

        "Second, caused by the first, the program's
        `presenter_fee_committed_cents` is replaced by — not increased by — the
        sum of the `kill_fee_cents` of the contracts just cancelled" and "Third,
        caused by the second, `budget_variance_cents` and `budget_posture` are
        re-derived. Fourth, caused by the third, the branch's
        `programs_over_budget_count` is decremented when that re-derivation
        flipped the posture from `OVER_BUDGET` back to `WITHIN_BUDGET`."

        Design: Difficulty/transitive_cascade/weather_close_cascade_four_links_from_contract_kill_fee_to_branch_counter
        """
        scenario = _over_budget_scheduled_program(world)
        world.set_clock("2026-08-14T02:00:00.000Z")
        world.weather_close(scenario["program"]["id"], ICE_STORM_REASON)

        program = world.read_program(scenario["program"]["id"])
        assert program["presenter_fee_committed_cents"] == 54877
        assert_budget_variance_and_posture(program, 17123, "WITHIN_BUDGET")
        assert world.read_branch(scenario["branch"]["id"])[
            "programs_over_budget_count"
        ] == 0

    def test_the_closure_releases_the_room_and_the_materials_budget(
        self, world: LibraryWorld
    ) -> None:
        """The room and the money go back independently of the fee cascade.

        "Independently of that money cascade, every reservation of the program in
        `HELD` or `CONFIRMED` status becomes `RELEASED` and
        `confirmed_room_capacity` returns to 0".

        Design: Difficulty/transitive_cascade/weather_close_cascade_four_links_from_contract_kill_fee_to_branch_counter
        """
        scenario = _over_budget_scheduled_program(world)
        world.set_clock("2026-08-14T02:00:00.000Z")
        world.weather_close(scenario["program"]["id"], ICE_STORM_REASON)

        assert world.read_reservation(scenario["reservation"]["id"])["status"] == "RELEASED"
        program = world.read_program(scenario["program"]["id"])
        assert program["confirmed_room_capacity"] == 0
        assert program["materials_committed_cents"] == 0
        assert program["materials_available_cents"] == 12000
        assert_materials_conservation(program)


# ==========================================================================
# The suspension cascade
# ==========================================================================
def _confirmed_program_with_two_lot_draw(world: LibraryWorld) -> Dict[str, Any]:
    """A confirmed adult program drawing 49 units across a local and a reuse lot."""
    home = world.branch(name="Hill Branch", branch_code="HIL")
    other = world.branch(name="Oak Branch", branch_code="OAK")
    room = world.room(
        home["id"],
        room_name="Program Room A",
        capacity_seats=60,
        min_setup_minutes=15,
        min_teardown_minutes=15,
    )
    local_lot = world.supply_lot(
        home["id"],
        sku="KIT-SCI",
        unit_cost_cents=200,
        quantity_procured=30,
        reuse_pool=False,
    )
    reuse_lot = world.supply_lot(
        other["id"],
        sku="KIT-SCI",
        unit_cost_cents=150,
        quantity_procured=25,
        reuse_pool=True,
    )
    program = world.program(
        home["id"],
        title="Adult Science Cafe",
        age_group="ADULT",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-15T14:00:00.000Z",
        end_utc="2026-08-15T15:00:00.000Z",
        attendance_target=49,
        attendance_cap=49,
        supply_sku="KIT-SCI",
        supply_units_per_attendee=1,
        materials_budget_cents=12000,
        presenter_fee_budget_cents=100000,
    )
    reservation = world.hold(
        program["id"],
        room["id"],
        start_utc="2026-08-15T13:45:00.000Z",
        end_utc="2026-08-15T15:15:00.000Z",
        setup_minutes=15,
        teardown_minutes=15,
    )
    world.confirm_reservation(reservation["id"])
    world.schedule(program["id"])
    presenter = world.presenter(
        legal_name="Ada Reyes",
        insurance_certificate_expires_on="2026-09-10",
        quoted_fee_cents=90000,
    )
    contract = world.contract(presenter["id"], program["id"], 75)
    world.offer(contract["id"], 90000, world.coordinator)
    world.execute(contract["id"], world.manager)
    confirmed = world.confirm_program(program["id"])
    world.request_screening(presenter["id"], "NAME_CHECK")
    return {
        "home": home,
        "other": other,
        "room": room,
        "local_lot": local_lot,
        "reuse_lot": reuse_lot,
        "program": confirmed,
        "reservation": reservation,
        "presenter": presenter,
        "contract": contract,
    }


class TestFlaggedScreeningCascade:
    """From one screening result to two lots, a room and a branch counter."""

    def test_the_draw_and_the_posture_before_the_flag(
        self, world: LibraryWorld
    ) -> None:
        """Two draw lines, one surcharged, and an over-budget program.

        "a program needing 49 units whose own branch holds a lot with 30
        available at 200 cents each draws a line of 6000 with no surcharge, then
        takes the remaining 19 from a cross-branch reuse lot at 150 cents each:
        base 2850, surcharge 8 percent of 2850 rounded half up which is 228, line
        total 3078 — a draw subtotal of 9078."

        Design: Difficulty/transitive_cascade/flagged_screening_cascade_blocks_contract_program_and_returns_the_supply_draw
        """
        scenario = _confirmed_program_with_two_lot_draw(world)
        program = scenario["program"]

        assert_supply_draw_lines(
            program,
            [
                {
                    "lot_id": scenario["local_lot"]["id"],
                    "units": 30,
                    "unit_cost_cents": 200,
                    "surcharge_cents": 0,
                    "line_total_cents": 6000,
                },
                {
                    "lot_id": scenario["reuse_lot"]["id"],
                    "units": 19,
                    "unit_cost_cents": 150,
                    "surcharge_cents": 228,
                    "line_total_cents": 3078,
                },
            ],
        )
        assert program["materials_committed_cents"] == 9986
        assert_budget_variance_and_posture(program, -3339, "OVER_BUDGET")
        assert world.read_branch(scenario["home"]["id"])[
            "programs_over_budget_count"
        ] == 1

    def test_the_flag_suspends_the_presenter_and_blocks_the_contract(
        self, world: LibraryWorld
    ) -> None:
        """Links one and two: the presenter is suspended and the contract blocked.

        "Its first cascade link sets the presenter's `engagement_status` to
        `SUSPENDED`" and "The second link, caused by the first, moves every
        contract of this presenter whose `status` is `OFFERED`, `COUNTERED` or
        `EXECUTED` to `BLOCKED`".

        Design: Difficulty/transitive_cascade/flagged_screening_cascade_blocks_contract_program_and_returns_the_supply_draw
        """
        scenario = _confirmed_program_with_two_lot_draw(world)

        flagged = world.screening_result(
            scenario["presenter"]["id"], "FLAGGED", "2026-08-01"
        )
        assert flagged["engagement_status"] == "SUSPENDED"
        assert flagged["screening_decision"] == "FLAGGED"
        assert flagged["screening_status"] == "PENDING_ADJUDICATION"
        assert flagged["screening_valid_until"] is None

        assert world.read_contract(scenario["contract"]["id"])["status"] == "BLOCKED"

    def test_the_flag_reverts_the_confirmation_and_returns_both_lots(
        self, world: LibraryWorld
    ) -> None:
        """Links three and four: compliance blocks and the draw goes back.

        "The fourth link, caused by the third, reverts each such program whose
        `operational_status` was `CONFIRMED` back to `SCHEDULED`: for every entry
        in that program's `supply_draw_lines` the drawn units are returned from
        the lot's `quantity_reserved` to its `quantity_available`, any lot that
        had gone `DEPLETED` returns to `ACTIVE` now that it has stock again,
        `supply_draw_lines` is emptied and `materials_committed_cents` drops to 0
        with `materials_available_cents` re-derived".

        Design: Difficulty/transitive_cascade/flagged_screening_cascade_blocks_contract_program_and_returns_the_supply_draw
        """
        scenario = _confirmed_program_with_two_lot_draw(world)
        world.screening_result(scenario["presenter"]["id"], "FLAGGED", "2026-08-01")

        program = world.read_program(scenario["program"]["id"])
        assert_program_status(
            program, operational_status="SCHEDULED", compliance_status="BLOCKED"
        )
        assert program["supply_draw_lines"] == []
        assert program["materials_committed_cents"] == 0
        assert program["materials_available_cents"] == 12000
        assert_materials_conservation(program)

        assert_lot_state(
            world.read_lot(scenario["local_lot"]["id"]),
            available=30,
            reserved=0,
            issued=0,
            status="ACTIVE",
        )
        assert_lot_state(
            world.read_lot(scenario["reuse_lot"]["id"]),
            available=25,
            reserved=0,
            issued=0,
            status="ACTIVE",
        )

    def test_the_revert_drops_the_room_and_unwinds_the_whole_budget(
        self, world: LibraryWorld
    ) -> None:
        """The confirmed reservation falls back to held and the money is freed.

        "the program's `CONFIRMED` reservation falls back to `HELD` and
        `confirmed_room_capacity` returns to 0, and the program's
        `budget_variance_cents` and `budget_posture` are re-derived with the
        branch's `programs_over_budget_count` adjusted only if the posture
        actually flipped."

        Design: Difficulty/transitive_cascade/flagged_screening_cascade_blocks_contract_program_and_returns_the_supply_draw
        """
        scenario = _confirmed_program_with_two_lot_draw(world)
        world.screening_result(scenario["presenter"]["id"], "FLAGGED", "2026-08-01")

        assert world.read_reservation(scenario["reservation"]["id"])["status"] == "HELD"
        program = world.read_program(scenario["program"]["id"])
        assert program["confirmed_room_capacity"] == 0
        assert program["presenter_fee_committed_cents"] == 0
        assert_budget_variance_and_posture(program, 112000, "WITHIN_BUDGET")
        assert world.read_branch(scenario["home"]["id"])[
            "programs_over_budget_count"
        ] == 0
