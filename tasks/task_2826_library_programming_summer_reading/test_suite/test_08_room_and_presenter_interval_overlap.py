"""Two shared resources whose interval conventions give opposite answers.

The room's occupancy interval is half-open, so a booking beginning at the instant
the previous one ends is admitted and a single overlapping minute is refused.
The presenter's engagement window is closed at both ends and padded by 90
minutes, so two windows sharing only their boundary instant conflict.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_PRESENTER_DOUBLE_BOOKED,
    ERR_ROOM_DOUBLE_BOOKED,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_budget_variance_and_posture,
    assert_instant_equals,
    assert_program_status,
)
from test_helpers.factories import reservation_payload
from test_helpers.fixtures import LibraryWorld


# ==========================================================================
# The half-open room occupancy interval
# ==========================================================================
def _three_hourly_slots_in_one_room(world: LibraryWorld) -> Dict[str, Any]:
    """Three consecutive hourly programs in one room, the first already booked.

    Both buffers are pinned to 0 so the occupancy interval equals the booked
    window, which isolates the interval convention from the buffer arithmetic.
    """
    branch = world.branch(overlapping_program_capacity=3)
    room = world.room(
        branch["id"],
        room_name="Study Room",
        capacity_seats=30,
        min_setup_minutes=0,
        min_teardown_minutes=0,
    )
    slots = []
    for title, start_hour, end_hour in (
        ("Slot One", "14", "15"),
        ("Slot Two", "15", "16"),
        ("Slot Three", "16", "17"),
    ):
        slots.append(
            world.program(
                branch["id"],
                title=title,
                age_group="ADULT",
                delivery_mode="IN_BRANCH",
                registration_policy="REGISTRATION",
                start_utc=f"2026-08-12T{start_hour}:00:00.000Z",
                end_utc=f"2026-08-12T{end_hour}:00:00.000Z",
                attendance_target=20,
                attendance_cap=20,
                supply_sku="KIT-GEN",
                supply_units_per_attendee=0,
                materials_budget_cents=5000,
                presenter_fee_budget_cents=0,
            )
        )
    first_reservation = world.hold(
        slots[0]["id"],
        room["id"],
        start_utc="2026-08-12T14:00:00.000Z",
        end_utc="2026-08-12T15:00:00.000Z",
        setup_minutes=0,
        teardown_minutes=0,
    )
    return {
        "branch": branch,
        "room": room,
        "slots": slots,
        "first_reservation": first_reservation,
    }


class TestRoomHalfOpenOccupancy:
    """Adjacency at the boundary instant is legal; one minute of overlap is not."""

    def test_a_booking_starting_at_the_previous_end_instant_is_admitted(
        self, world: LibraryWorld
    ) -> None:
        """The interval excludes its end, so 15:00 belongs to the second booking only.

        "Because the interval is half-open, a reservation whose occupancy begins
        at exactly the instant another's occupancy ends is accepted; a reservation
        that begins one minute before that instant collides and is rejected with
        `ERR_ROOM_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/room_half_open_occupancy_admits_adjacency_and_rejects_one_minute_overlap
        """
        scenario = _three_hourly_slots_in_one_room(world)

        response = world.api.create_reservation(
            scenario["slots"][1]["id"],
            reservation_payload(
                scenario["room"]["id"],
                world.program_version(scenario["slots"][1]["id"]),
                start_utc="2026-08-12T15:00:00.000Z",
                end_utc="2026-08-12T16:00:00.000Z",
                setup_minutes=0,
                teardown_minutes=0,
            ),
            world.coordinator,
        )
        second = get_success_data(response, 201)
        assert second["status"] == "HELD"
        assert second["effective_capacity_seats"] == 30

    def test_the_stored_occupancy_bounds_are_the_booked_window_with_zero_buffers(
        self, world: LibraryWorld
    ) -> None:
        """With both buffers at 0 the occupancy interval equals the booked window.

        "`occupancy_start_utc` is `start_utc` moved earlier by `setup_minutes`,
        and `occupancy_end_utc` is `end_utc` moved later by `teardown_minutes` —
        the two buffers are independent and need not be symmetric."

        Design: Difficulty/resource_temporal_overlap/room_half_open_occupancy_admits_adjacency_and_rejects_one_minute_overlap
        """
        scenario = _three_hourly_slots_in_one_room(world)
        second = world.hold(
            scenario["slots"][1]["id"],
            scenario["room"]["id"],
            start_utc="2026-08-12T15:00:00.000Z",
            end_utc="2026-08-12T16:00:00.000Z",
            setup_minutes=0,
            teardown_minutes=0,
        )
        assert_instant_equals(
            second["occupancy_start_utc"],
            "2026-08-12T15:00:00.000Z",
            "occupancy_start_utc",
        )
        assert_instant_equals(
            second["occupancy_end_utc"],
            "2026-08-12T16:00:00.000Z",
            "occupancy_end_utc",
        )

        first = world.read_reservation(scenario["first_reservation"]["id"])
        assert_instant_equals(
            first["occupancy_start_utc"],
            "2026-08-12T14:00:00.000Z",
            "occupancy_start_utc",
        )
        assert_instant_equals(
            first["occupancy_end_utc"],
            "2026-08-12T15:00:00.000Z",
            "occupancy_end_utc",
        )

    def test_one_overlapping_minute_is_refused_and_not_persisted(
        self, world: LibraryWorld
    ) -> None:
        """A window reaching back one minute collides with the middle booking.

        "it is compared against the occupancy intervals of every other
        reservation of the *same* `room_id` whose status is `HELD` or
        `CONFIRMED`."

        Design: Difficulty/resource_temporal_overlap/room_half_open_occupancy_admits_adjacency_and_rejects_one_minute_overlap
        """
        scenario = _three_hourly_slots_in_one_room(world)
        world.hold(
            scenario["slots"][1]["id"],
            scenario["room"]["id"],
            start_utc="2026-08-12T15:00:00.000Z",
            end_utc="2026-08-12T16:00:00.000Z",
            setup_minutes=0,
            teardown_minutes=0,
        )

        third = scenario["slots"][2]
        response = world.api.create_reservation(
            third["id"],
            reservation_payload(
                scenario["room"]["id"],
                world.program_version(third["id"]),
                start_utc="2026-08-12T15:59:00.000Z",
                end_utc="2026-08-12T17:00:00.000Z",
                setup_minutes=0,
                teardown_minutes=0,
            ),
            world.coordinator,
        )
        validate_error(
            response,
            ERR_ROOM_DOUBLE_BOOKED,
            ERROR_HTTP_STATUS[ERR_ROOM_DOUBLE_BOOKED],
        )

        _, room_meta = validate_paginated(
            world.api.list_reservations(
                world.coordinator, room_id=scenario["room"]["id"]
            )
        )
        assert room_meta["total_count"] == 2, (
            "the rejected booking must not have been persisted"
        )
        _, program_meta = validate_paginated(
            world.api.list_reservations(world.coordinator, program_id=third["id"])
        )
        assert program_meta["total_count"] == 0
        assert_program_status(
            world.read_program(third["id"]), operational_status="DRAFT"
        )


# ==========================================================================
# The closed presenter engagement window
# ==========================================================================
def _one_presenter_three_evenly_spaced_talks(
    world: LibraryWorld,
) -> Dict[str, Any]:
    """One presenter, one executed afternoon talk and two standing evening offers.

    Every program is on a Wednesday, is adult-only and is 0 miles away from a
    presenter whose certificate is far outside the rider window, so each total is
    the agreed fee alone and only the windows are in question.
    """
    branch = world.branch(overlapping_program_capacity=3)
    programs = []
    for title, start_hour, end_hour in (
        ("Afternoon Talk", "14", "15"),
        ("Evening Talk", "18", "19"),
        ("Late Talk", "20", "21"),
    ):
        programs.append(
            world.program(
                branch["id"],
                title=title,
                age_group="ADULT",
                delivery_mode="IN_BRANCH",
                registration_policy="REGISTRATION",
                start_utc=f"2026-08-12T{start_hour}:00:00.000Z",
                end_utc=f"2026-08-12T{end_hour}:00:00.000Z",
                attendance_target=20,
                attendance_cap=20,
                supply_sku="KIT-GEN",
                supply_units_per_attendee=0,
                materials_budget_cents=5000,
                presenter_fee_budget_cents=60000,
            )
        )
    presenter = world.presenter(
        legal_name="Rosa Lindqvist",
        presenter_type="INDIVIDUAL",
        insurance_certificate_expires_on="2027-06-30",
        quoted_fee_cents=50000,
    )
    contracts = []
    for program in programs:
        contract = world.contract(presenter["id"], program["id"], 0)
        world.offer(contract["id"], 50000, world.coordinator)
        contracts.append(contract)
    world.execute(contracts[0]["id"], world.manager)
    return {
        "branch": branch,
        "programs": programs,
        "presenter": presenter,
        "contracts": contracts,
    }


class TestPresenterClosedEngagementWindow:
    """Windows that merely touch conflict, which is the room's answer inverted."""

    def test_a_window_touching_at_the_boundary_instant_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """Sixteen-thirty belongs to both buffered windows, so the second is refused.

        "Because the interval is closed, two engagement windows that share only
        their boundary instant conflict, and the execution is rejected with
        `ERR_PRESENTER_DOUBLE_BOOKED`. A presenter finishing at 15:00 with a
        90-minute buffer is therefore unavailable for anything whose own buffered
        window reaches back to 16:30 or earlier."

        Design: Difficulty/resource_temporal_overlap/presenter_closed_engagement_window_rejects_a_merely_touching_second_booking
        """
        scenario = _one_presenter_three_evenly_spaced_talks(world)

        response = world.api.execute_contract(
            scenario["contracts"][1]["id"], world.manager
        )
        validate_error(
            response,
            ERR_PRESENTER_DOUBLE_BOOKED,
            ERROR_HTTP_STATUS[ERR_PRESENTER_DOUBLE_BOOKED],
        )

        blocked = world.read_contract(scenario["contracts"][1]["id"])
        assert blocked["status"] == "OFFERED"
        assert blocked["total_fee_cents"] == 0
        assert blocked["agreed_fee_cents"] is None

        program = world.read_program(scenario["programs"][1]["id"])
        assert program["presenter_fee_committed_cents"] == 0
        assert_program_status(program, compliance_status="UNVERIFIED")

    def test_the_refused_contract_holds_no_window_of_its_own(
        self, world: LibraryWorld
    ) -> None:
        """The later talk executes, so the refused offer never occupied the presenter.

        "contracts in `DRAFT`, `OFFERED`, `COUNTERED`, `BLOCKED`,
        `CANCELLED_WEATHER` or `CANCELLED_LIBRARY` status hold no window and are
        ignored."

        Design: Difficulty/resource_temporal_overlap/presenter_closed_engagement_window_rejects_a_merely_touching_second_booking
        """
        scenario = _one_presenter_three_evenly_spaced_talks(world)
        world.api.execute_contract(scenario["contracts"][1]["id"], world.manager)

        late = world.execute(scenario["contracts"][2]["id"], world.manager)
        assert late["status"] == "EXECUTED"
        assert late["total_fee_cents"] == 50000

        program = world.read_program(scenario["programs"][2]["id"])
        assert program["presenter_fee_committed_cents"] == 50000
        assert_budget_variance_and_posture(program, 15000, "WITHIN_BUDGET")

    def test_only_the_two_executed_contracts_count_against_the_presenter(
        self, world: LibraryWorld
    ) -> None:
        """Two executions, one refusal, and a presenter counter that reads 2.

        "The candidate contract's window is compared against the engagement
        window of every other contract of the *same* presenter whose `status` is
        `EXECUTED` or `COMPLETED`".

        Design: Difficulty/resource_temporal_overlap/presenter_closed_engagement_window_rejects_a_merely_touching_second_booking
        """
        scenario = _one_presenter_three_evenly_spaced_talks(world)
        world.api.execute_contract(scenario["contracts"][1]["id"], world.manager)
        world.execute(scenario["contracts"][2]["id"], world.manager)

        first = world.read_contract(scenario["contracts"][0]["id"])
        assert first["status"] == "EXECUTED"
        assert first["total_fee_cents"] == 50000

        presenter = world.read_presenter(scenario["presenter"]["id"])
        assert presenter["executed_contract_count"] == 2
        assert presenter["engagement_status"] == "ACTIVE"
