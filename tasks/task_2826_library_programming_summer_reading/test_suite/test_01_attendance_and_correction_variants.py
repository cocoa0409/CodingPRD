"""Two published measurements computed from one and the same dataset.

The first family is the pair of attendance attainment percentages, which differ
only in their denominator.  The second is the pair of correction policies, which
are handed byte-identical log and correction data and publish divergent award
state from it.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.assertions import (
    assert_one_decimal_pct,
    assert_program_status,
)
from test_helpers.fixtures import LibraryWorld
from test_helpers.test_users import MANAGER_HEADERS


# ==========================================================================
# The attendance attainment pair
# ==========================================================================
def _storytime_closed_out(world: LibraryWorld) -> Dict[str, Any]:
    """A 60-seat wheelchair-accessible room, 39 seats sold, then a close-out.

    The program promises ``WHEELCHAIR_LAYOUT``, so the room's 60 nominal seats
    become 51 effective ones, and the two attainment denominators part company.
    """
    branch = world.branch()
    room = world.room(
        branch["id"],
        room_name="Community Room",
        capacity_seats=60,
        min_setup_minutes=15,
        min_teardown_minutes=15,
        accessibility_features=["WHEELCHAIR_ACCESSIBLE", "HEARING_LOOP"],
        status="AVAILABLE",
    )
    program = world.program(
        branch["id"],
        title="Family Storytime",
        age_group="SCHOOL_AGE",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-15T14:00:00.000Z",
        end_utc="2026-08-15T15:00:00.000Z",
        attendance_target=55,
        attendance_cap=55,
        supply_sku="KIT-STORY",
        supply_units_per_attendee=0,
        materials_budget_cents=12000,
        presenter_fee_budget_cents=100000,
        accessibility_accommodations=["WHEELCHAIR_LAYOUT"],
    )
    reservation = world.hold(
        program["id"],
        room["id"],
        start_utc="2026-08-15T13:30:00.000Z",
        end_utc="2026-08-15T15:15:00.000Z",
        setup_minutes=30,
        teardown_minutes=15,
    )
    world.confirm_reservation(reservation["id"])
    world.schedule(program["id"])
    world.register(program["id"], registrant_reference="FAMILY-BLOCK-1", seats=39)
    world.confirm_program(program["id"])
    world.set_clock("2026-08-15T16:00:00.000Z")
    closed = world.close_out(program["id"], 33, 0, 12)
    return {
        "branch": branch,
        "room": room,
        "reservation": world.read_reservation(reservation["id"]),
        "program": closed,
    }


class TestAttendanceAttainmentDenominators:
    """One close-out, two attainment figures, one deliberate divergence."""

    def test_funder_and_internal_figures_diverge_on_their_denominator(
        self, world: LibraryWorld
    ) -> None:
        """The funder figure divides by the target, the internal one by the seats.

        "`attendance_attainment_funder_pct` divides `gross_attendance` by
        `attendance_target` — the number promised in the grant application —
        because that is what the funder was told to expect.
        `attendance_attainment_internal_pct` divides `gross_attendance` by the
        seats that actually existed: `confirmed_room_capacity` when that value is
        greater than 0, and `attendance_target` when it is 0."

        Design: Difficulty/dual_variant_calc/attendance_attainment_funder_vs_internal_denominator_divergence
        """
        program = _storytime_closed_out(world)["program"]

        assert program["gross_attendance"] == 33
        assert_one_decimal_pct(
            program["attendance_attainment_funder_pct"],
            60.0,
            "attendance_attainment_funder_pct",
        )
        assert_one_decimal_pct(
            program["attendance_attainment_internal_pct"],
            64.7,
            "attendance_attainment_internal_pct",
        )
        divergence = (
            program["attendance_attainment_internal_pct"]
            - program["attendance_attainment_funder_pct"]
        )
        assert round(divergence, 1) == 4.7, (
            "the two attainment figures must diverge by 4.7 points on this data, "
            f"got {divergence}"
        )
        assert_program_status(program, operational_status="CLOSED_OUT")

    def test_wheelchair_layout_floors_the_seats_the_internal_figure_divides_by(
        self, world: LibraryWorld
    ) -> None:
        """Sixty nominal seats become fifty-one, and the program publishes them.

        "When `WHEELCHAIR_LAYOUT` is among the program's accommodations, a
        fifteen-hundredths seat-loss rate applies: the effective figure is the
        room's `capacity_seats` multiplied by the remaining eighty-five
        hundredths, then taken down to the next whole seat by flooring — a
        60-seat room yields 51 effective seats, and so does a 61-seat room."

        Design: Difficulty/dual_variant_calc/attendance_attainment_funder_vs_internal_denominator_divergence
        """
        scenario = _storytime_closed_out(world)

        assert scenario["room"]["capacity_seats"] == 60
        assert scenario["reservation"]["effective_capacity_seats"] == 51
        assert scenario["program"]["confirmed_room_capacity"] == 51

    def test_no_show_and_survey_rate_come_from_the_same_three_inputs(
        self, world: LibraryWorld
    ) -> None:
        """The other three outcome figures ride on the identical close-out body.

        "`no_show_count` is `registered_count` less
        `verified_registrant_attendance`, with a floor of 0" and
        "`survey_response_rate_pct` is 0.0 when `gross_attendance` is 0, and
        otherwise 100 multiplied by `surveys_collected` divided by
        `gross_attendance`, rounded half up to one decimal place."

        Design: Difficulty/dual_variant_calc/attendance_attainment_funder_vs_internal_denominator_divergence
        """
        program = _storytime_closed_out(world)["program"]

        assert program["registered_count"] == 39
        assert program["verified_registrant_attendance"] == 33
        assert program["drop_in_headcount"] == 0
        assert program["surveys_collected"] == 12
        assert program["no_show_count"] == 6
        assert_one_decimal_pct(
            program["survey_response_rate_pct"], 36.4, "survey_response_rate_pct"
        )


# ==========================================================================
# The correction policy pair
# ==========================================================================
def _twin_challenges_after_a_correction(world: LibraryWorld) -> Dict[str, Any]:
    """Two readers, identical ledgers, opposite correction policies.

    Each reader logs 100 units and then 80, holds both tier awards, and is then
    corrected by minus 50 against the first entry.
    """
    branch = world.branch()
    lots = {
        sku: world.prize_lot(
            branch["id"],
            sku=sku,
            unit_cost_cents=cost,
            quantity_procured=100,
            reuse_pool=False,
        )
        for sku, cost in (
            ("PRIZE-A1", 100),
            ("PRIZE-A2", 469),
            ("PRIZE-B1", 100),
            ("PRIZE-B2", 469),
        )
    }
    ladder = [
        {"tier_index": 1, "threshold_units": 60, "prize_units_per_participant": 1},
        {"tier_index": 2, "threshold_units": 150, "prize_units_per_participant": 1},
    ]
    scenario: Dict[str, Any] = {"branch": branch, "lots": lots}
    for key, name, policy, skus, reader in (
        ("a", "Summer A", "LEDGER_TRUTH", ("PRIZE-A1", "PRIZE-A2"), "Reader A"),
        ("b", "Summer B", "HIGH_WATER", ("PRIZE-B1", "PRIZE-B2"), "Reader B"),
    ):
        tiers = [
            dict(spec, prize_sku=sku) for spec, sku in zip(ladder, skus)
        ]
        opened = world.opened_challenge(
            tiers=tiers,
            name=name,
            logging_method="MINUTES",
            unit_label="minute",
            start_on="2026-06-01",
            end_on="2026-08-31",
            correction_policy=policy,
            prize_budget_cents=100000,
        )
        participant = world.participant(
            opened["challenge"]["id"], branch["id"], display_name=reader
        )
        first = world.log_entry(participant["id"], 100, "2026-06-10")
        world.log_entry(participant["id"], 80, "2026-06-11")
        world.correction(
            participant["id"], first["id"], -50, note="double-counted session"
        )
        scenario[key] = {
            "challenge": world.read_challenge(opened["challenge"]["id"]),
            "tiers": opened["tiers"],
            "participant": world.read_participant(participant["id"]),
        }
    return scenario


class TestCorrectionPolicyDivergence:
    """Identical ledger data, opposite published award state."""

    def test_both_policies_agree_on_the_replayed_ledger(
        self, world: LibraryWorld
    ) -> None:
        """Cumulative units and eligibility fall under either policy.

        "a subsequent correction of minus 50 leaves `cumulative_units` at 130 and
        `eligible_tier_index` at 1 under both policies".

        Design: Difficulty/dual_variant_calc/correction_policy_ledger_truth_revokes_where_high_water_retains
        """
        scenario = _twin_challenges_after_a_correction(world)

        for key in ("a", "b"):
            participant = scenario[key]["participant"]
            assert participant["cumulative_units"] == 130, (
                f"reader {key} must replay to 130 units, "
                f"got {participant['cumulative_units']}"
            )
            assert participant["eligible_tier_index"] == 1, (
                f"reader {key} must be eligible for tier 1 only, "
                f"got {participant['eligible_tier_index']}"
            )

    def test_ledger_truth_revokes_the_tier_two_award(
        self, world: LibraryWorld
    ) -> None:
        """The awarded index falls back and the tier-two award is taken away.

        "Every `TierAward` of this participant for a tier whose `threshold_units`
        now exceeds the recomputed `cumulative_units` becomes `REVOKED`, and
        `awarded_tier_index` falls back to the highest tier still met."

        Design: Difficulty/dual_variant_calc/correction_policy_ledger_truth_revokes_where_high_water_retains
        """
        scenario = _twin_challenges_after_a_correction(world)
        side = scenario["a"]

        assert side["participant"]["awarded_tier_index"] == 1
        revoked, _ = validate_paginated(
            world.api.list_tier_awards(
                MANAGER_HEADERS,
                participant_id=side["participant"]["id"],
                status="REVOKED",
                limit=100,
            )
        )
        assert len(revoked) == 1, (
            f"expected exactly one revoked award, got {len(revoked)}"
        )
        tier_two_id = next(
            tier["id"] for tier in side["tiers"] if tier["tier_index"] == 2
        )
        assert revoked[0]["tier_id"] == tier_two_id, (
            "the revoked award must be the one held against the tier-two threshold"
        )

    def test_high_water_retains_the_tier_two_award(
        self, world: LibraryWorld
    ) -> None:
        """The awarded index is monotone and both awards keep their status.

        "Under `HIGH_WATER`, an award once granted is never retracted.
        `cumulative_units` still falls and `eligible_tier_index` still falls with
        it, but `awarded_tier_index` is monotone non-decreasing and stays where
        it was, every `TierAward` keeps its existing status, no inventory unit is
        released, no prize budget is released, and no deferred award is
        promoted."

        Design: Difficulty/dual_variant_calc/correction_policy_ledger_truth_revokes_where_high_water_retains
        """
        scenario = _twin_challenges_after_a_correction(world)
        side = scenario["b"]

        assert side["participant"]["awarded_tier_index"] == 2
        reserved, _ = validate_paginated(
            world.api.list_tier_awards(
                MANAGER_HEADERS,
                participant_id=side["participant"]["id"],
                status="RESERVED",
                limit=100,
            )
        )
        assert len(reserved) == 2, (
            f"expected both awards to stay reserved, got {len(reserved)}"
        )

    def test_the_prize_ledger_and_the_stock_diverge_with_the_policy(
        self, world: LibraryWorld
    ) -> None:
        """The revoked award releases its cents and its unit; the retained one does not.

        "A revoked award that had been `RESERVED` returns its `units` from its
        lot's `quantity_reserved` to `quantity_available`" and "decreases the
        challenge's `prize_committed_cents` by that award's `award_total_cents`,
        with `prize_available_cents` and `prize_inventory_posture` re-derived."

        Design: Difficulty/dual_variant_calc/correction_policy_ledger_truth_revokes_where_high_water_retains
        """
        scenario = _twin_challenges_after_a_correction(world)

        assert scenario["a"]["challenge"]["prize_committed_cents"] == 100
        assert scenario["b"]["challenge"]["prize_committed_cents"] == 569

        released = world.read_lot(scenario["lots"]["PRIZE-A2"]["id"])
        assert released["quantity_reserved"] == 0
        assert released["quantity_available"] == 100

        retained = world.read_lot(scenario["lots"]["PRIZE-B2"]["id"])
        assert retained["quantity_reserved"] == 1
        assert retained["quantity_available"] == 99
