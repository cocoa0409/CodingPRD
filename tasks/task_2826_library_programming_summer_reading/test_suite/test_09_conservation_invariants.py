"""Three-way accounting identities that must survive a compensating transition.

A reading correction that unearns a prize has to hand the unit back to
availability and the cents back to the prize budget.  A weather closure has to
hand the supply draw back to availability rather than to issued, which is the
distinction that separates a closure from a settlement.
"""

from typing import Any, Dict

from test_helpers.assertions import (
    assert_budget_variance_and_posture,
    assert_lot_conservation,
    assert_lot_state,
    assert_materials_conservation,
    assert_prize_conservation,
    assert_program_status,
    assert_supply_draw_lines,
)
from test_helpers.fixtures import LibraryWorld

FLOOD_REASON = "Regional flood warning"


# ==========================================================================
# The prize ledger under a revocation
# ==========================================================================
def _award_revoked_by_a_ledger_truth_correction(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """One reader earns a prize at 60 units, then a correction drops them to 50.

    The lot is the reader's own branch stock and is not a reuse pool, so the
    award is exactly one unit at 100 cents with no surcharge.
    """
    branch = world.branch()
    lot = world.prize_lot(
        branch["id"],
        sku="PRIZE-C1",
        unit_cost_cents=100,
        quantity_procured=50,
        reuse_pool=False,
    )
    opened = world.opened_challenge(
        tiers=[
            {
                "tier_index": 1,
                "threshold_units": 60,
                "prize_sku": "PRIZE-C1",
                "prize_units_per_participant": 1,
            }
        ],
        name="Ledger Truth Summer",
        logging_method="MINUTES",
        unit_label="minute",
        start_on="2026-06-01",
        end_on="2026-08-31",
        correction_policy="LEDGER_TRUTH",
        prize_budget_cents=100000,
    )
    challenge_id = opened["challenge"]["id"]
    participant = world.participant(
        challenge_id,
        branch["id"],
        display_name="Careful Reader",
        age_band="AGE_5_11",
    )
    entry = world.log_entry(participant["id"], 60, "2026-06-10")
    after_log = {
        "lot": world.read_lot(lot["id"]),
        "challenge": world.read_challenge(challenge_id),
    }
    version = world.participant_version(participant["id"])
    world.correction(
        participant["id"],
        entry["id"],
        -10,
        note="miscounted ten minutes",
        expected_participant_version=version,
    )
    return {
        "branch": branch,
        "lot_id": lot["id"],
        "challenge_id": challenge_id,
        "tier_id": opened["tiers"][0]["id"],
        "participant_id": participant["id"],
        "after_log": after_log,
    }


class TestPrizeConservationAcrossARevocation:
    """Fifty units and one hundred thousand cents, both fully accounted for."""

    def test_the_award_had_held_one_unit_and_one_hundred_cents(
        self, world: LibraryWorld
    ) -> None:
        """The starting position: a real reservation the revocation has to undo.

        "the lot moves the award's `units` from `quantity_available` to
        `quantity_reserved`".

        Design: Difficulty/compensating_invariant/prize_unit_and_cents_conservation_survives_an_award_revocation
        """
        after_log = _award_revoked_by_a_ledger_truth_correction(world)["after_log"]

        assert_lot_state(after_log["lot"], available=49, reserved=1, issued=0)
        assert after_log["challenge"]["prize_committed_cents"] == 100

    def test_the_correction_revokes_the_award_and_lowers_the_ledger(
        self, world: LibraryWorld
    ) -> None:
        """Fifty units no longer meets the sixty-unit tier, so the award is taken back.

        "Under `LEDGER_TRUTH`, the ledger is the truth and an award that is no
        longer earned is taken back. Every `TierAward` of this participant for a
        tier whose `threshold_units` now exceeds the recomputed `cumulative_units`
        becomes `REVOKED`, and `awarded_tier_index` falls back to the highest tier
        still met."

        Design: Difficulty/compensating_invariant/prize_unit_and_cents_conservation_survives_an_award_revocation
        """
        scenario = _award_revoked_by_a_ledger_truth_correction(world)

        participant = world.read_participant(scenario["participant_id"])
        assert participant["cumulative_units"] == 50
        assert participant["eligible_tier_index"] == 0
        assert participant["awarded_tier_index"] == 0
        assert participant["entry_count"] == 2

        awards = world.awards_for_participant(scenario["participant_id"])
        assert len(awards) == 1, f"expected exactly one award, got {len(awards)}"
        assert awards[0]["status"] == "REVOKED"

        tier = world.read_tier(scenario["tier_id"])
        assert tier["award_count"] == 0
        assert tier["deferred_count"] == 0

    def test_the_unit_returns_to_availability_and_the_cents_to_the_budget(
        self, world: LibraryWorld
    ) -> None:
        """Both three-way identities close again with nothing stranded.

        "For a reading challenge, `prize_budget_cents` equals
        `prize_available_cents` plus `prize_committed_cents` plus
        `prize_spent_cents`. For an inventory lot, `quantity_procured` equals
        `quantity_available` plus `quantity_reserved` plus `quantity_issued`".

        Design: Difficulty/compensating_invariant/prize_unit_and_cents_conservation_survives_an_award_revocation
        """
        scenario = _award_revoked_by_a_ledger_truth_correction(world)

        lot = world.read_lot(scenario["lot_id"])
        assert_lot_state(lot, available=50, reserved=0, issued=0, status="ACTIVE")
        assert lot["quantity_procured"] == 50
        assert_lot_conservation(lot)

        challenge = world.read_challenge(scenario["challenge_id"])
        assert challenge["prize_committed_cents"] == 0
        assert challenge["prize_spent_cents"] == 0
        assert challenge["prize_available_cents"] == 100000
        assert challenge["prize_budget_cents"] == 100000
        assert_prize_conservation(challenge)


# ==========================================================================
# The materials ledger under a weather closure
# ==========================================================================
def _confirmed_draw_then_weather_closed(world: LibraryWorld) -> Dict[str, Any]:
    """A confirmed program drawing 49 units across two lots, then closed for weather.

    The program carries no contracts at all, so materials are the only money in
    play and the closure's return path is the only thing under observation.
    """
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
        title="Maker Saturday",
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
        presenter_fee_budget_cents=0,
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
    confirmed = world.confirm_program(program["id"])
    after_confirm = {
        "program": confirmed,
        "local_lot": world.read_lot(local_lot["id"]),
        "reuse_lot": world.read_lot(reuse_lot["id"]),
    }
    world.set_clock("2026-08-14T02:00:00.000Z")
    closed = world.weather_close(program["id"], FLOOD_REASON)
    return {
        "home": home,
        "other": other,
        "local_lot_id": local_lot["id"],
        "reuse_lot_id": reuse_lot["id"],
        "program_id": program["id"],
        "reservation_id": reservation["id"],
        "after_confirm": after_confirm,
        "closed": closed,
    }


class TestMaterialsConservationAcrossAWeatherClosure:
    """Twelve thousand cents and fifty-five units, before and after the closure."""

    def test_the_confirmation_committed_the_draw_and_depleted_the_local_lot(
        self, world: LibraryWorld
    ) -> None:
        """The starting position: 9986 committed and 2014 left of the budget.

        "An accepted confirmation stores `supply_draw_lines`, moves each drawn
        lot's units from `quantity_available` to `quantity_reserved` (re-deriving
        `quantity_available` and setting the lot's `status` to `DEPLETED` when it
        reaches 0), stores `materials_committed_cents` and
        `materials_available_cents`".

        Design: Difficulty/compensating_invariant/materials_cents_and_supply_units_conservation_across_confirm_then_weather_close
        """
        after_confirm = _confirmed_draw_then_weather_closed(world)["after_confirm"]

        program = after_confirm["program"]
        assert program["materials_committed_cents"] == 9986
        assert program["materials_available_cents"] == 2014
        assert_materials_conservation(program)

        assert_lot_state(
            after_confirm["local_lot"],
            available=0,
            reserved=30,
            issued=0,
            status="DEPLETED",
        )
        assert_lot_state(
            after_confirm["reuse_lot"], available=6, reserved=19, issued=0
        )

    def test_the_closure_empties_the_draw_and_restores_the_whole_budget(
        self, world: LibraryWorld
    ) -> None:
        """The cents identity reads 12000 == 12000 + 0 + 0 with nothing spent.

        "the supply draw is returned to its lots: each entry in
        `supply_draw_lines` gives its `units` back from `quantity_reserved` to
        `quantity_available`, a lot whose availability rises above 0 returns from
        `DEPLETED` to `ACTIVE`, `supply_draw_lines` is emptied,
        `materials_committed_cents` drops to 0 and `materials_available_cents` is
        re-derived."

        Design: Difficulty/compensating_invariant/materials_cents_and_supply_units_conservation_across_confirm_then_weather_close
        """
        scenario = _confirmed_draw_then_weather_closed(world)

        closed = scenario["closed"]
        assert_program_status(closed, operational_status="WEATHER_CLOSED")
        assert closed["closure_reason"] == FLOOD_REASON

        program = world.read_program(scenario["program_id"])
        assert_supply_draw_lines(program, [])
        assert program["materials_committed_cents"] == 0
        assert program["materials_spent_cents"] == 0
        assert program["materials_available_cents"] == 12000
        assert program["materials_budget_cents"] == 12000
        assert_materials_conservation(program)

    def test_the_units_go_back_to_availability_and_never_to_issued(
        self, world: LibraryWorld
    ) -> None:
        """Both lots stand at their full procured quantity and are active again.

        "Units move from available to reserved when a program's supply draw or a
        prize award holds them, and from reserved to issued when that hold is
        settled permanently."

        Design: Difficulty/compensating_invariant/materials_cents_and_supply_units_conservation_across_confirm_then_weather_close
        """
        scenario = _confirmed_draw_then_weather_closed(world)

        local_lot = world.read_lot(scenario["local_lot_id"])
        assert_lot_state(
            local_lot, available=30, reserved=0, issued=0, status="ACTIVE"
        )
        assert_lot_conservation(local_lot)

        reuse_lot = world.read_lot(scenario["reuse_lot_id"])
        assert_lot_state(
            reuse_lot, available=25, reserved=0, issued=0, status="ACTIVE"
        )
        assert_lot_conservation(reuse_lot)

    def test_the_closure_releases_the_room_and_leaves_the_posture_healthy(
        self, world: LibraryWorld
    ) -> None:
        """No contract existed, so the whole budget is free and no counter moved.

        "When the owning program becomes `WEATHER_CLOSED` or `CANCELLED`, every
        reservation of that program in `HELD` or `CONFIRMED` status moves to
        `RELEASED` and the program's `confirmed_room_capacity` returns to 0."

        Design: Difficulty/compensating_invariant/materials_cents_and_supply_units_conservation_across_confirm_then_weather_close
        """
        scenario = _confirmed_draw_then_weather_closed(world)

        assert (
            world.read_reservation(scenario["reservation_id"])["status"] == "RELEASED"
        )
        program = world.read_program(scenario["program_id"])
        assert program["confirmed_room_capacity"] == 0
        assert program["presenter_fee_committed_cents"] == 0
        assert_budget_variance_and_posture(program, 12000, "WITHIN_BUDGET")
        assert world.read_branch(scenario["home"]["id"])[
            "programs_over_budget_count"
        ] == 0
