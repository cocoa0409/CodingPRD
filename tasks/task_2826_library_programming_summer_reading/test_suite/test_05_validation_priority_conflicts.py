"""Requests that violate two rules at once and must report only the earlier one.

The first pair sets child-safety screening against the fee cap on a contract
execution; the second sets the confirmed-room gate against the branch staffing
ceiling on a program confirmation.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED,
    ERR_FEE_CAP_EXCEEDED,
    ERR_NO_CONFIRMED_ROOM,
    ERR_PRESENTER_SCREENING_REQUIRED,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import assert_program_status
from test_helpers.fixtures import LibraryWorld


# ==========================================================================
# Screening before the fee cap
# ==========================================================================
def _unscreened_over_cap_offer(world: LibraryWorld) -> Dict[str, Any]:
    """An unscreened presenter on a minors program, offered above the branch cap.

    The computed total would be 230753 cents against a binding branch cap of
    150000, so the execution violates both the screening rule and the fee cap.
    """
    branch = world.branch(per_program_fee_cap_cents=150000)
    program = world.program(
        branch["id"],
        title="Teen Robotics",
        age_group="TEEN",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-15T14:00:00.000Z",
        end_utc="2026-08-15T15:00:00.000Z",
        attendance_target=24,
        attendance_cap=24,
        supply_sku="KIT-BOT",
        supply_units_per_attendee=0,
        materials_budget_cents=12000,
        presenter_fee_budget_cents=250000,
    )
    presenter = world.presenter(
        legal_name="Ada Reyes",
        insurance_certificate_expires_on="2026-09-10",
        quoted_fee_cents=200000,
    )
    contract = world.contract(presenter["id"], program["id"], 75)
    world.offer(contract["id"], 200000, world.coordinator)
    return {
        "branch": branch,
        "program": program,
        "presenter": presenter,
        "contract": contract,
    }


class TestScreeningOutranksTheFeeCap:
    """Priority 19 decides, and priority 45 never gets a turn."""

    def test_the_unscreened_presenter_decides_the_response(
        self, world: LibraryWorld
    ) -> None:
        """Child safety is checked before the money is even computed.

        "Rules are evaluated in strictly ascending priority order and the
        **first** violated rule decides the response; no later rule can mask an
        earlier one." "Screening is active where the program serves minors —
        `ERR_PRESENTER_SCREENING_REQUIRED`".

        Design: Difficulty/priority_pair_validation_conflict/child_safety_screening_priority_19_outranks_fee_cap_priority_45
        """
        scenario = _unscreened_over_cap_offer(world)

        response = world.api.execute_contract(
            scenario["contract"]["id"], world.manager
        )
        body = validate_error(
            response,
            ERR_PRESENTER_SCREENING_REQUIRED,
            ERROR_HTTP_STATUS[ERR_PRESENTER_SCREENING_REQUIRED],
        )
        assert body["error_id"] != ERR_FEE_CAP_EXCEEDED, (
            "the fee cap is priority 45 and must not mask priority 19"
        )

    def test_the_rejected_execution_persists_no_fee_component(
        self, world: LibraryWorld
    ) -> None:
        """Nothing is stored: not the total, not a single component.

        "a total above that ceiling is rejected outright with
        `ERR_FEE_CAP_EXCEEDED` — the contract stays `OFFERED` and nothing is
        stored."

        Design: Difficulty/priority_pair_validation_conflict/child_safety_screening_priority_19_outranks_fee_cap_priority_45
        """
        scenario = _unscreened_over_cap_offer(world)
        world.api.execute_contract(scenario["contract"]["id"], world.manager)

        contract = world.read_contract(scenario["contract"]["id"])
        assert contract["status"] == "OFFERED"
        assert contract["total_fee_cents"] == 0
        assert contract["agreed_fee_cents"] is None
        assert contract["travel_fee_cents"] == 0
        assert contract["escort_fee_cents"] == 0
        assert contract["insurance_rider_fee_cents"] == 0
        assert contract["weekend_premium_cents"] == 0

        program = world.read_program(scenario["program"]["id"])
        assert_program_status(program, compliance_status="PENDING_SCREENING")
        assert program["presenter_fee_committed_cents"] == 0

        presenter = world.read_presenter(scenario["presenter"]["id"])
        assert presenter["engagement_status"] == "PROSPECT"
        assert presenter["executed_contract_count"] == 0


# ==========================================================================
# The room gate before the staffing ceiling
# ==========================================================================
def _two_overlapping_programs_one_staffing_slot(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """One confirmed program spends the branch's single slot; a second is held only."""
    branch = world.branch(overlapping_program_capacity=1)
    first_room = world.room(
        branch["id"],
        room_name="Room One",
        capacity_seats=40,
        min_setup_minutes=15,
        min_teardown_minutes=15,
    )
    second_room = world.room(
        branch["id"],
        room_name="Room Two",
        capacity_seats=30,
        min_setup_minutes=15,
        min_teardown_minutes=15,
    )
    first = world.program(
        branch["id"],
        title="Afternoon Book Club",
        age_group="ADULT",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-12T14:00:00.000Z",
        end_utc="2026-08-12T15:00:00.000Z",
        attendance_target=20,
        attendance_cap=20,
        supply_sku="KIT-BOOK",
        supply_units_per_attendee=0,
        materials_budget_cents=5000,
        presenter_fee_budget_cents=0,
    )
    first_reservation = world.hold(
        first["id"],
        first_room["id"],
        start_utc="2026-08-12T13:45:00.000Z",
        end_utc="2026-08-12T15:15:00.000Z",
        setup_minutes=15,
        teardown_minutes=15,
    )
    world.confirm_reservation(first_reservation["id"])
    world.schedule(first["id"])
    world.confirm_program(first["id"])

    second = world.program(
        branch["id"],
        title="Poetry Salon",
        age_group="ADULT",
        delivery_mode="IN_BRANCH",
        registration_policy="REGISTRATION",
        start_utc="2026-08-12T14:30:00.000Z",
        end_utc="2026-08-12T15:30:00.000Z",
        attendance_target=15,
        attendance_cap=15,
        supply_sku="KIT-POEM",
        supply_units_per_attendee=0,
        materials_budget_cents=5000,
        presenter_fee_budget_cents=0,
    )
    second_reservation = world.hold(
        second["id"],
        second_room["id"],
        start_utc="2026-08-12T14:15:00.000Z",
        end_utc="2026-08-12T15:45:00.000Z",
        setup_minutes=15,
        teardown_minutes=15,
    )
    world.schedule(second["id"])
    return {
        "branch": branch,
        "first": first,
        "second": second,
        "first_reservation": first_reservation,
        "second_reservation": second_reservation,
    }


class TestRoomGateOutranksStaffingCeiling:
    """Priority 26 decides, two steps ahead of priority 28."""

    def test_the_missing_confirmed_room_decides_the_response(
        self, world: LibraryWorld
    ) -> None:
        """A held-only reservation is refused before the load is aggregated.

        "An `IN_BRANCH` program skips that rule entirely and must instead have
        exactly one reservation of its own in `CONFIRMED` status; a program
        holding only a `HELD` reservation, or one whose reservation was released
        or superseded, is rejected with `ERR_NO_CONFIRMED_ROOM`."

        Design: Difficulty/priority_pair_validation_conflict/missing_confirmed_room_priority_26_outranks_branch_staffing_priority_28
        """
        scenario = _two_overlapping_programs_one_staffing_slot(world)

        response = world.api.confirm_program(
            scenario["second"]["id"], world.manager
        )
        body = validate_error(
            response,
            ERR_NO_CONFIRMED_ROOM,
            ERROR_HTTP_STATUS[ERR_NO_CONFIRMED_ROOM],
        )
        assert body["error_id"] != ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED, (
            "the staffing ceiling is priority 28 and must not mask priority 26"
        )

    def test_the_rejected_confirmation_changes_nothing_on_either_program(
        self, world: LibraryWorld
    ) -> None:
        """The refused candidate keeps its held room and its empty draw.

        "a cascade is **all or nothing with its trigger**: if the triggering
        operation is rejected by any validation, no cascade link is applied and no
        partial allocation is persisted".

        Design: Difficulty/priority_pair_validation_conflict/missing_confirmed_room_priority_26_outranks_branch_staffing_priority_28
        """
        scenario = _two_overlapping_programs_one_staffing_slot(world)
        world.api.confirm_program(scenario["second"]["id"], world.manager)

        second = world.read_program(scenario["second"]["id"])
        assert_program_status(second, operational_status="SCHEDULED")
        assert second["confirmed_room_capacity"] == 0
        assert second["supply_draw_lines"] == []
        assert second["materials_committed_cents"] == 0
        assert (
            world.read_reservation(scenario["second_reservation"]["id"])["status"]
            == "HELD"
        )

        first = world.read_program(scenario["first"]["id"])
        assert_program_status(first, operational_status="CONFIRMED")
        assert first["confirmed_room_capacity"] == 40

    def test_the_contract_ladder_is_irrelevant_to_this_confirmation(
        self, world: LibraryWorld
    ) -> None:
        """Neither program carries a contract, so no fee ever enters the picture.

        "A freshly drafted program reports `operational_status` of `DRAFT` and
        `compliance_status` of `UNVERIFIED`".

        Design: Difficulty/priority_pair_validation_conflict/missing_confirmed_room_priority_26_outranks_branch_staffing_priority_28
        """
        scenario = _two_overlapping_programs_one_staffing_slot(world)

        second = world.read_program(scenario["second"]["id"])
        assert_program_status(second, compliance_status="UNVERIFIED")
        assert second["presenter_fee_committed_cents"] == 0
