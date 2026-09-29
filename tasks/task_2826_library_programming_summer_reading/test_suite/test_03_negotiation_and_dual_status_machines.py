"""Two state machines whose shape is not a straight line.

The negotiation loop cycles between offered and countered and terminates on a
count of offers alone.  A program's two status dimensions run in parallel and
advance on triggers that are inadmissible in the other machine.
"""

from typing import Any, Dict

from test_helpers.api_errors import (
    ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_budget_variance_and_posture,
    assert_contract_fee_breakdown,
    assert_date_equals,
    assert_program_status,
)
from test_helpers.factories import offer_payload
from test_helpers.fixtures import LibraryWorld
from prd_bench_local_runner.testing import validate_error


# ==========================================================================
# The bounded negotiation loop
# ==========================================================================
def _three_full_negotiation_passes(world: LibraryWorld) -> Dict[str, Any]:
    """Three offers and three counters, leaving the contract countered at round 3."""
    branch = world.branch()
    program = world.program(
        branch["id"],
        title="Author Talk",
        age_group="ADULT",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-12T18:00:00.000Z",
        end_utc="2026-08-12T19:00:00.000Z",
        attendance_target=40,
        attendance_cap=40,
        supply_sku="KIT-TALK",
        supply_units_per_attendee=0,
        materials_budget_cents=5000,
        presenter_fee_budget_cents=120000,
    )
    presenter = world.presenter(
        legal_name="Noor Haddad",
        presenter_type="AGENCY",
        insurance_certificate_expires_on="2027-06-30",
        quoted_fee_cents=96000,
    )
    contract = world.contract(presenter["id"], program["id"], 10)
    for offered, countered in ((90000, 96000), (92000, 95000), (93000, 94000)):
        world.offer(contract["id"], offered, world.coordinator)
        world.counter(contract["id"], countered)
    return {
        "branch": branch,
        "program": program,
        "presenter": presenter,
        "contract": world.read_contract(contract["id"]),
    }


class TestNegotiationCycleTermination:
    """Only offers consume the budget; counters cycle freely."""

    def test_three_offers_and_three_counters_are_all_accepted(
        self, world: LibraryWorld
    ) -> None:
        """The loop runs three full passes and stops at round three.

        "The library may then offer again, and the `OFFERED → COUNTERED →
        OFFERED` cycle is the negotiation." "A presenter's reply is recorded as a
        counter, which requires the contract to be `OFFERED`, requires the
        presenter not to be `SUSPENDED`, stores `countered_fee_cents`, and moves
        the contract to `COUNTERED` while leaving `negotiation_round`
        untouched."

        Design: Difficulty/non_linear_state_machine/negotiation_cycle_terminates_on_the_fourth_offer_not_the_fourth_counter
        """
        contract = _three_full_negotiation_passes(world)["contract"]

        assert contract["status"] == "COUNTERED"
        assert contract["negotiation_round"] == 3
        assert contract["offered_fee_cents"] == 93000
        assert contract["countered_fee_cents"] == 94000

    def test_the_fourth_offer_is_refused_and_stores_nothing(
        self, world: LibraryWorld
    ) -> None:
        """A fourth offer exhausts the ceiling and leaves the contract untouched.

        "Its termination condition is a hard ceiling of three offers: the fourth
        offer on a contract that has already consumed three rounds is rejected
        with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/negotiation_cycle_terminates_on_the_fourth_offer_not_the_fourth_counter
        """
        scenario = _three_full_negotiation_passes(world)
        contract_id = scenario["contract"]["id"]

        response = world.api.offer_contract(
            contract_id, offer_payload(93500), world.coordinator
        )
        validate_error(
            response,
            ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
            ERROR_HTTP_STATUS[ERR_NEGOTIATION_ROUNDS_EXHAUSTED],
        )

        after = world.read_contract(contract_id)
        assert after["status"] == "COUNTERED"
        assert after["negotiation_round"] == 3
        assert after["offered_fee_cents"] == 93000, (
            "the rejected 93500 must not have been stored"
        )
        assert after["countered_fee_cents"] == 94000
        assert after["total_fee_cents"] == 0
        assert after["agreed_fee_cents"] is None


# ==========================================================================
# The two parallel program dimensions
# ==========================================================================
def _partner_site_program_with_unscreened_contract(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """A minors partner-site program whose presenter is unscreened at draft time."""
    branch = world.branch()
    program = world.program(
        branch["id"],
        title="Playground Story Hour",
        age_group="SCHOOL_AGE",
        delivery_mode="PARTNER_SITE",
        partner_type="SCHOOL",
        partner_org_name="Maple Elementary",
        partner_insurance_expires_on="2027-05-31",
        registration_policy="DROP_IN",
        start_utc="2026-08-12T14:00:00.000Z",
        end_utc="2026-08-12T15:00:00.000Z",
        attendance_target=30,
        attendance_cap=30,
        supply_sku="KIT-OUT",
        supply_units_per_attendee=0,
        materials_budget_cents=5000,
        presenter_fee_budget_cents=60000,
    )
    presenter = world.presenter(
        legal_name="Sam Oyelaran",
        presenter_type="INDIVIDUAL",
        insurance_certificate_expires_on="2027-06-30",
        quoted_fee_cents=50000,
    )
    contract = world.contract(presenter["id"], program["id"], 0)
    after_draft = world.read_program(program["id"])
    world.clear_screening(presenter["id"], "NAME_CHECK", "2026-07-01")
    world.offer(contract["id"], 50000, world.coordinator)
    return {
        "branch": branch,
        "program": program,
        "presenter": presenter,
        "contract": contract,
        "after_draft": after_draft,
    }


class TestProgramDualStatusDimensions:
    """Two dimensions, three triggers, and no trigger touching both."""

    def test_drafting_a_contract_moves_only_the_compliance_dimension(
        self, world: LibraryWorld
    ) -> None:
        """Compliance leaves ``UNVERIFIED`` while the operational status stays drafted.

        "Drafting a contract is also the event that pulls the program's
        compliance dimension into motion, and it does so without touching the
        operational dimension at all — the two dimensions advance on disjoint
        triggers. If the program's `compliance_status` is `UNVERIFIED`, the
        program's `serves_minors` is true, and the contracted presenter's
        `screening_status` is not `ACTIVE`, then `compliance_status` becomes
        `PENDING_SCREENING`".

        Design: Difficulty/non_linear_state_machine/program_operational_and_compliance_dimensions_advance_on_disjoint_triggers
        """
        scenario = _partner_site_program_with_unscreened_contract(world)

        assert scenario["program"]["serves_minors"] is True
        assert_program_status(
            scenario["after_draft"],
            operational_status="DRAFT",
            compliance_status="PENDING_SCREENING",
        )

    def test_publishing_moves_only_the_operational_dimension(
        self, world: LibraryWorld
    ) -> None:
        """Scheduling advances the operational status and leaves compliance behind.

        "Publishing moves `DRAFT` to `SCHEDULED`, and either a
        `ProgramCoordinator` or a `ProgramManager` may do it."

        Design: Difficulty/non_linear_state_machine/program_operational_and_compliance_dimensions_advance_on_disjoint_triggers
        """
        scenario = _partner_site_program_with_unscreened_contract(world)

        scheduled = world.schedule(scenario["program"]["id"])
        assert_program_status(
            scheduled,
            operational_status="SCHEDULED",
            compliance_status="PENDING_SCREENING",
        )

    def test_execution_clears_compliance_without_moving_the_operational_status(
        self, world: LibraryWorld
    ) -> None:
        """The combined state is reachable only by running both machines.

        "On the program, `compliance_status` becomes `CLEARED` (from either
        `UNVERIFIED` or `PENDING_SCREENING`), `presenter_fee_committed_cents`
        increases by `total_fee_cents`".

        Design: Difficulty/non_linear_state_machine/program_operational_and_compliance_dimensions_advance_on_disjoint_triggers
        """
        scenario = _partner_site_program_with_unscreened_contract(world)
        world.schedule(scenario["program"]["id"])

        executed = world.execute(scenario["contract"]["id"], world.manager)
        assert executed["status"] == "EXECUTED"
        assert_contract_fee_breakdown(
            executed,
            agreed_fee_cents=50000,
            travel_fee_cents=0,
            escort_fee_cents=4000,
            insurance_rider_fee_cents=0,
            weekend_premium_cents=0,
            total_fee_cents=54000,
        )

        program = world.read_program(scenario["program"]["id"])
        assert_program_status(
            program, operational_status="SCHEDULED", compliance_status="CLEARED"
        )
        assert program["presenter_fee_committed_cents"] == 54000
        assert_budget_variance_and_posture(program, 11000, "WITHIN_BUDGET")
        assert program["confirmed_room_capacity"] == 0, (
            "a partner-site program never holds a room reservation at all"
        )

    def test_the_screening_clearance_dates_out_to_three_hundred_and_sixty_five_days(
        self, world: LibraryWorld
    ) -> None:
        """A name check decided 2026-07-01 is active until 2027-07-01.

        "a `NAME_CHECK` decision is good for 365 days and a `FINGERPRINT`
        decision for 730 days, counted forward from `screening_decided_on` as
        whole calendar days, and the result is stored as the ISO date
        `screening_valid_until`."

        Design: Difficulty/non_linear_state_machine/program_operational_and_compliance_dimensions_advance_on_disjoint_triggers
        """
        scenario = _partner_site_program_with_unscreened_contract(world)

        presenter = world.read_presenter(scenario["presenter"]["id"])
        assert presenter["screening_status"] == "ACTIVE"
        assert_date_equals(
            presenter["screening_valid_until"], "2027-07-01", "screening_valid_until"
        )
