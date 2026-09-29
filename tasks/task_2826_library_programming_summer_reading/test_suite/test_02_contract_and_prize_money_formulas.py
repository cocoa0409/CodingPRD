"""Two multi-input money formulas whose rounding site is externally visible.

A presenter contract combines tiered mileage, a minors escort flat fee, an
insurance rider driven by a date comparison and a weekend premium taken on the
whole pre-premium subtotal.  A prize award applies the same eight per cent
cross-branch surcharge, but rounds it once per award rather than once over the
challenge's committed total.
"""

from typing import Any, Dict

from test_helpers.assertions import (
    assert_award_pricing,
    assert_budget_variance_and_posture,
    assert_contract_fee_breakdown,
    assert_prize_conservation,
    assert_program_status,
)
from test_helpers.fixtures import LibraryWorld


# ==========================================================================
# The seven-step contract total
# ==========================================================================
def _saturday_science_executed(world: LibraryWorld) -> Dict[str, Any]:
    """A Saturday minors program staffed at 75 miles by a lapsing certificate.

    Every one of the four surcharge inputs is engaged at once: the mileage
    straddles the 60-mile band boundary, the age group draws the escort fee, the
    certificate sits inside the thirty-day rider window, and the program starts
    on a Saturday.
    """
    branch = world.branch(per_program_fee_cap_cents=150000)
    program = world.program(
        branch["id"],
        title="Saturday Science",
        age_group="SCHOOL_AGE",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-15T14:00:00.000Z",
        end_utc="2026-08-15T15:00:00.000Z",
        attendance_target=40,
        attendance_cap=40,
        supply_sku="KIT-SCI",
        supply_units_per_attendee=0,
        materials_budget_cents=12000,
        presenter_fee_budget_cents=100000,
    )
    presenter = world.presenter(
        legal_name="Ada Reyes",
        presenter_type="INDIVIDUAL",
        insurance_certificate_expires_on="2026-09-10",
        quoted_fee_cents=90000,
    )
    world.clear_screening(presenter["id"], "NAME_CHECK", "2026-07-01")
    contract = world.contract(presenter["id"], program["id"], 75)
    world.offer(contract["id"], 90000, world.coordinator)
    executed = world.execute(contract["id"], world.manager)
    return {
        "branch": branch,
        "program": world.read_program(program["id"]),
        "presenter": world.read_presenter(presenter["id"]),
        "contract": executed,
    }


class TestContractTotalFee:
    """The payable total, component by component and in order."""

    def test_the_weekend_premium_is_taken_on_the_whole_pre_premium_subtotal(
        self, world: LibraryWorld
    ) -> None:
        """Ten per cent of 99775 is 9978, not ten per cent of the base alone.

        "The weekend premium sits on that whole subtotal, not on the base. When
        the program's `start_utc` falls on a Saturday or a Sunday evaluated in
        UTC, `weekend_premium_cents` is one tenth of the pre-premium subtotal,
        rounded half up to a whole number of cents; on any other weekday it is 0.
        Finally `total_fee_cents` is the pre-premium subtotal plus
        `weekend_premium_cents`."

        Design: Difficulty/combinatorial_formula/contract_total_fee_seven_step_order_with_premium_on_full_subtotal
        """
        contract = _saturday_science_executed(world)["contract"]

        assert_contract_fee_breakdown(
            contract,
            agreed_fee_cents=90000,
            travel_fee_cents=3275,
            escort_fee_cents=4000,
            insurance_rider_fee_cents=2500,
            weekend_premium_cents=9978,
            total_fee_cents=109753,
        )
        assert contract["total_fee_cents"] != 108775, (
            "108775 is the total a premium taken on the base alone would give"
        )
        assert contract["status"] == "EXECUTED"

    def test_the_two_mileage_bands_and_the_two_flat_surcharges_are_published_apart(
        self, world: LibraryWorld
    ) -> None:
        """Seventy-five miles pays 40 miles of band one and 15 of band two.

        "the first band's billable mileage is the round-trip mileage capped at 60
        and then reduced by 20, treated as zero if that would be negative; the
        second band's billable mileage is the round-trip mileage reduced by 60,
        likewise treated as zero if negative; and `travel_fee_cents` is the first
        band's mileage multiplied by 65 plus the second band's mileage multiplied
        by 45."

        Design: Difficulty/combinatorial_formula/contract_total_fee_seven_step_order_with_premium_on_full_subtotal
        """
        contract = _saturday_science_executed(world)["contract"]

        assert contract["round_trip_miles"] == 75
        assert contract["travel_fee_cents"] == 40 * 65 + 15 * 45 == 3275
        assert contract["escort_fee_cents"] == 4000, (
            "`escort_fee_cents` is 4000 when the program's `serves_minors` is true"
        )
        assert contract["insurance_rider_fee_cents"] == 2500, (
            "a certificate lapsing inside the thirty-day window attracts the rider"
        )

    def test_execution_publishes_the_total_onto_the_presenter_and_the_program(
        self, world: LibraryWorld
    ) -> None:
        """The same figure lands on three resources at once.

        "On the presenter, `executed_contract_count` increases by 1 and
        `engagement_status` becomes `ACTIVE`" and "On the program,
        `compliance_status` becomes `CLEARED` (from either `UNVERIFIED` or
        `PENDING_SCREENING`), `presenter_fee_committed_cents` increases by
        `total_fee_cents`, and `budget_variance_cents` and `budget_posture` are
        re-derived".

        Design: Difficulty/combinatorial_formula/contract_total_fee_seven_step_order_with_premium_on_full_subtotal
        """
        scenario = _saturday_science_executed(world)

        assert scenario["presenter"]["engagement_status"] == "ACTIVE"
        assert scenario["presenter"]["executed_contract_count"] == 1

        program = scenario["program"]
        assert_program_status(
            program, operational_status="DRAFT", compliance_status="CLEARED"
        )
        assert program["presenter_fee_committed_cents"] == 109753
        assert_budget_variance_and_posture(program, 2247, "WITHIN_BUDGET")


# ==========================================================================
# The per-award prize surcharge
# ==========================================================================
def _two_cross_branch_prizes(world: LibraryWorld) -> Dict[str, Any]:
    """Two readers at branch H each draw one 469-cent unit from branch O.

    Branch H holds no ``PRIZE-X`` stock at all, so both awards fall through to
    the cross-branch reuse bucket and each pays the eight per cent surcharge.
    """
    home = world.branch(name="Hill Branch", branch_code="HIL")
    other = world.branch(name="Oak Branch", branch_code="OAK")
    lot = world.prize_lot(
        other["id"],
        sku="PRIZE-X",
        unit_cost_cents=469,
        quantity_procured=10,
        reuse_pool=True,
        description="shared telescope kits",
    )
    opened = world.opened_challenge(
        tiers=[
            {
                "tier_index": 1,
                "threshold_units": 60,
                "prize_sku": "PRIZE-X",
                "prize_units_per_participant": 1,
            }
        ],
        name="Summer Minutes",
        logging_method="MINUTES",
        unit_label="minute",
        start_on="2026-06-01",
        end_on="2026-08-31",
        correction_policy="HIGH_WATER",
        prize_budget_cents=100000,
    )
    challenge_id = opened["challenge"]["id"]
    first = world.participant(
        challenge_id, home["id"], display_name="Reader One"
    )
    second = world.participant(
        challenge_id, home["id"], display_name="Reader Two"
    )
    world.log_entry(first["id"], 60, "2026-07-15")
    world.log_entry(second["id"], 60, "2026-07-15")
    return {
        "home": home,
        "other": other,
        "lot": world.read_lot(lot["id"]),
        "challenge": world.read_challenge(challenge_id),
        "tier": world.read_tier(opened["tiers"][0]["id"]),
        "participants": [
            world.read_participant(first["id"]),
            world.read_participant(second["id"]),
        ],
        "awards": world.awards_for_tier(opened["tiers"][0]["id"]),
    }


class TestPrizeSurchargeRoundingSite:
    """Eight per cent rounded twice at 38 cents, never once at 75."""

    def test_each_award_rounds_its_own_transfer_surcharge(
        self, world: LibraryWorld
    ) -> None:
        """Both awards carry 38 cents of surcharge on a 469-cent line.

        "`transfer_surcharge_cents` is 8 percent of `line_cost_cents` rounded
        half up when the lot belongs to a branch other than the participant's
        `home_branch_id` and exactly 0 when it is the home branch's own lot, and
        `award_total_cents` is the line cost plus the surcharge."

        Design: Difficulty/combinatorial_formula/prize_surcharge_rounded_per_award_never_over_the_challenge_total
        """
        scenario = _two_cross_branch_prizes(world)
        awards = scenario["awards"]

        assert len(awards) == 2, f"expected two awards, got {len(awards)}"
        for award in awards:
            assert_award_pricing(
                award,
                units=1,
                unit_cost_cents=469,
                transfer_surcharge_cents=38,
                status="RESERVED",
                lot_id=scenario["lot"]["id"],
            )
            assert award["award_total_cents"] == 507

    def test_the_challenge_ledger_sums_the_two_rounded_awards(
        self, world: LibraryWorld
    ) -> None:
        """1014 cents committed, one cent above a single rounding over 938.

        "**That surcharge is rounded once per award and never once over the
        challenge's committed total**: two readers each earning a one-unit prize
        from a cross-branch lot costing 469 cents each attract 38 cents of
        surcharge apiece for 507 each and 1014 committed in total, where rounding
        8 percent over the combined base of 938 would have given 1013".

        Design: Difficulty/combinatorial_formula/prize_surcharge_rounded_per_award_never_over_the_challenge_total
        """
        challenge = _two_cross_branch_prizes(world)["challenge"]

        assert challenge["prize_committed_cents"] == 1014
        assert challenge["prize_committed_cents"] != 1013, (
            "1013 is the total a single rounding over the combined base would give"
        )
        assert challenge["prize_available_cents"] == 98986
        assert challenge["prize_spent_cents"] == 0
        assert_prize_conservation(challenge)

    def test_the_cross_branch_lot_reserves_one_unit_for_each_reader(
        self, world: LibraryWorld
    ) -> None:
        """Two units move to reserved and the lot keeps eight available.

        "the lot moves the award's `units` from `quantity_available` to
        `quantity_reserved`".

        Design: Difficulty/combinatorial_formula/prize_surcharge_rounded_per_award_never_over_the_challenge_total
        """
        scenario = _two_cross_branch_prizes(world)

        lot = scenario["lot"]
        assert lot["quantity_reserved"] == 2
        assert lot["quantity_available"] == 8
        assert lot["status"] == "ACTIVE"

        tier = scenario["tier"]
        assert tier["award_count"] == 2
        assert tier["deferred_count"] == 0
        for participant in scenario["participants"]:
            assert participant["awarded_tier_index"] == 1
