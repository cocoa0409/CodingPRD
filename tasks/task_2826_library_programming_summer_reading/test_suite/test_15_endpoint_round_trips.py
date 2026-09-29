"""Endpoint round trips: what a write stores is what the matching read returns.

These cases walk a resource from its create through its reads and its listing
filters, and walk the action endpoints through the state they publish onto their
neighbours.  The money cases pin both sides of a rate boundary so the endpoint's
arithmetic cannot be satisfied by a single constant.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_DROP_IN_NO_REGISTRATION,
    ERR_PROGRAM_NOT_FOUND,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_budget_variance_and_posture,
    assert_common_fields,
    assert_instant_equals,
    assert_lot_state,
    assert_materials_conservation,
    assert_program_status,
)
from test_helpers.factories import contract_payload, registration_payload
from test_helpers.fixtures import LibraryWorld


class TestBranchAndRoomRoundTrip:
    """A branch, its two rooms and the listing filter that separates them."""

    def test_the_created_rooms_read_back_and_the_status_filter_selects_one(
        self, world: LibraryWorld
    ) -> None:
        """Both rooms take their branch from the path; only one is available.

        "Rooms belong to a branch and are created inside it, so a room's
        `branch_id` is taken from the creation path and any `branch_id` in the body
        is ignored."

        Design: Corner/endpoints/branch_and_room_create_read_and_filtered_list_round_trip
        """
        branch = world.branch(name="Central Library", branch_code="CEN")
        available_room = world.room(
            branch["id"],
            room_name="Story Room",
            capacity_seats=60,
            accessibility_features=["WHEELCHAIR_ACCESSIBLE"],
        )
        closed_room = world.room(
            branch["id"], room_name="Annex Room", status="OUT_OF_SERVICE"
        )

        read_branch = world.read_branch(branch["id"])
        assert_common_fields(read_branch)
        assert read_branch["branch_code"] == "CEN"
        assert read_branch["overlapping_program_capacity"] == 2
        assert read_branch["programs_over_budget_count"] == 0

        read_room = world.read_room(available_room["id"])
        assert read_room["capacity_seats"] == 60
        assert read_room["accessibility_features"] == ["WHEELCHAIR_ACCESSIBLE"]
        assert read_room["status"] == "AVAILABLE"
        assert read_room["branch_id"] == branch["id"]
        assert world.read_room(closed_room["id"])["branch_id"] == branch["id"]

        rows, meta = validate_paginated(
            world.api.list_rooms(
                world.coordinator, branch_id=branch["id"], status="AVAILABLE"
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == available_room["id"]


class TestContractCreationLink:
    """Both foreign keys on a contract must resolve before anything is stored."""

    def test_a_fabricated_program_id_is_refused_and_the_real_pair_is_stored(
        self, world: LibraryWorld
    ) -> None:
        """The create is a link, so a dangling end is a not-found answer.

        "Either coordinating role may draft one by naming the `presenter_id`, the
        `program_id` being staffed, and the non-negative `round_trip_miles` that will
        be reimbursed."

        Design: Corner/endpoints/contract_creation_links_an_existing_presenter_to_an_existing_program
        """
        branch = world.branch()
        program = world.adult_program(branch["id"])
        presenter = world.presenter()

        validate_error(
            world.api.create_contract(
                contract_payload(presenter["id"], NON_EXISTENT_UUID),
                world.coordinator,
            ),
            ERR_PROGRAM_NOT_FOUND,
            ERROR_HTTP_STATUS[ERR_PROGRAM_NOT_FOUND],
        )

        contract = get_success_data(
            world.api.create_contract(
                contract_payload(presenter["id"], program["id"]), world.coordinator
            ),
            201,
        )
        assert contract["presenter_id"] == presenter["id"]
        assert contract["program_id"] == program["id"]
        assert contract["status"] == "DRAFT"
        assert contract["negotiation_round"] == 0
        assert contract["total_fee_cents"] == 0

        _, meta = validate_paginated(
            world.api.list_contracts(world.coordinator, presenter_id=presenter["id"])
        )
        assert meta["total_count"] == 1


class TestLibraryCancellationKillFee:
    """Ten days' notice costs everything; fourteen days' costs a quarter."""

    def test_the_kill_fee_rate_switches_at_exactly_fourteen_days_of_notice(
        self, world: LibraryWorld
    ) -> None:
        """The boundary day itself takes the lighter quarter rate.

        "When that notice is fewer than 14 days, the library owes the presenter the
        **entire** `total_fee_cents`; when it is 14 days or more, it owes one quarter
        of `total_fee_cents` rounded half up to whole cents."

        Design: Corner/endpoints/library_cancellation_kill_fee_switches_at_exactly_fourteen_days_notice
        """
        world.set_clock("2026-08-03T00:00:00.000Z")
        branch = world.branch()
        late_program = world.adult_program(
            branch["id"],
            title="Poetry Evening",
            start_utc="2026-08-13T18:00:00.000Z",
            end_utc="2026-08-13T19:00:00.000Z",
        )
        early_program = world.adult_program(
            branch["id"],
            title="History Evening",
            start_utc="2026-08-17T18:00:00.000Z",
            end_utc="2026-08-17T19:00:00.000Z",
        )
        presenter = world.presenter()
        late_contract = world.executed_contract(presenter["id"], late_program["id"])
        early_contract = world.executed_contract(presenter["id"], early_program["id"])
        assert late_contract["total_fee_cents"] == 50000
        assert early_contract["total_fee_cents"] == 50000

        cancelled_late = world.cancel(late_program["id"], "Presenter unavailable")
        cancelled_early = world.cancel(early_program["id"], "Presenter unavailable")

        assert cancelled_late["presenter_fee_committed_cents"] == 50000
        assert cancelled_early["presenter_fee_committed_cents"] == 12500

        late_after = world.read_contract(late_contract["id"])
        assert late_after["status"] == "CANCELLED_LIBRARY"
        assert late_after["kill_fee_cents"] == 50000
        assert late_after["total_fee_cents"] == 50000

        early_after = world.read_contract(early_contract["id"])
        assert early_after["status"] == "CANCELLED_LIBRARY"
        assert early_after["kill_fee_cents"] == 12500

        assert_budget_variance_and_posture(cancelled_late, 200000, "WITHIN_BUDGET")
        assert_budget_variance_and_posture(cancelled_early, 237500, "WITHIN_BUDGET")
        assert world.read_branch(branch["id"])["programs_over_budget_count"] == 0

        still_engaged = world.read_presenter(presenter["id"])
        assert still_engaged["executed_contract_count"] == 2
        assert still_engaged["engagement_status"] == "ACTIVE"


class TestProgramReadAcrossItsMoneyLifecycle:
    """Three reads of one program, each satisfying the materials identity."""

    def test_the_materials_identity_holds_before_confirm_after_confirm_and_after_close_out(
        self, world: LibraryWorld
    ) -> None:
        """Fifty thousand cents move from available to committed to spent.

        "Otherwise `materials_available_cents` is set to `materials_budget_cents`
        less `materials_committed_cents` less `materials_spent_cents`, which is the
        form the conservation invariant of section 2.8 takes for materials: the
        budget always equals available plus committed plus spent."

        Design: Corner/endpoints/program_read_keeps_the_materials_cents_identity_across_confirm_and_close_out
        """
        branch = world.branch()
        room = world.room(branch["id"])
        lot = world.supply_lot(
            branch["id"],
            sku="CRAFT-KIT",
            unit_cost_cents=250,
            quantity_procured=100,
            reuse_pool=False,
        )
        program = world.program(branch["id"])
        reservation = world.hold(program["id"], room["id"])
        world.confirm_reservation(reservation["id"])
        world.schedule(program["id"])
        world.register(program["id"], registrant_reference="card-0001", seats=1)

        before = world.read_program(program["id"])
        assert before["materials_committed_cents"] == 0
        assert before["materials_spent_cents"] == 0
        assert before["materials_available_cents"] == 50000
        assert_materials_conservation(before)

        world.confirm_program(program["id"])
        after_confirm = world.read_program(program["id"])
        assert after_confirm["materials_committed_cents"] == 2750
        assert after_confirm["materials_spent_cents"] == 0
        assert after_confirm["materials_available_cents"] == 47250
        assert_materials_conservation(after_confirm)

        world.set_clock("2026-08-12T16:00:00.000Z")
        world.close_out(program["id"], 1, 0, 1)
        after_close_out = world.read_program(program["id"])
        assert after_close_out["materials_committed_cents"] == 0
        assert after_close_out["materials_spent_cents"] == 2750
        assert after_close_out["materials_available_cents"] == 47250
        assert_materials_conservation(after_close_out)

        assert_lot_state(
            world.read_lot(lot["id"]), available=90, reserved=0, issued=10
        )


class TestRegistrationEndpointAvailability:
    """One endpoint, two policies, two answers in the same room."""

    def test_the_policy_alone_decides_whether_registrations_are_taken(
        self, world: LibraryWorld
    ) -> None:
        """A drop-in program counts heads at the door instead.

        "the program's `registration_policy` must be `REGISTRATION`; attempting to
        register against a `DROP_IN` program is rejected with
        `ERR_DROP_IN_NO_REGISTRATION`, because a drop-in program counts heads at the
        door instead."

        Design: Corner/endpoints/registration_endpoint_serves_registration_programs_and_refuses_drop_in_ones
        """
        branch = world.branch()
        room = world.room(branch["id"])
        registering = world.program(branch["id"], title="Craft Hour")
        walk_in = world.program(
            branch["id"],
            title="Drop In Story Time",
            registration_policy="DROP_IN",
            start_utc="2026-08-12T16:00:00.000Z",
            end_utc="2026-08-12T17:00:00.000Z",
        )
        world.hold(registering["id"], room["id"])
        world.schedule(registering["id"])
        world.hold(
            walk_in["id"],
            room["id"],
            start_utc="2026-08-12T16:00:00.000Z",
            end_utc="2026-08-12T17:00:00.000Z",
        )
        world.schedule(walk_in["id"])

        accepted = get_success_data(
            world.api.register(
                registering["id"],
                registration_payload("card-0001", seats=2),
                world.coordinator,
            ),
            200,
        )
        assert accepted["registered_count"] == 2
        assert accepted["registrant_references"] == ["card-0001"]

        validate_error(
            world.api.register(
                walk_in["id"], registration_payload("card-0001"), world.coordinator
            ),
            ERR_DROP_IN_NO_REGISTRATION,
            ERROR_HTTP_STATUS[ERR_DROP_IN_NO_REGISTRATION],
        )

        refused = world.read_program(walk_in["id"])
        assert refused["registered_count"] == 0
        assert refused["registrant_references"] == []


class TestReservationConfirmPublishesCapacity:
    """The confirm action is what moves the seat count onto the program."""

    def test_the_confirm_copies_the_effective_seats_onto_the_program(
        self, world: LibraryWorld
    ) -> None:
        """A held booking publishes nothing; a confirmed one publishes fifty-one.

        "Confirmation moves the reservation to `CONFIRMED`, copies its
        `effective_capacity_seats` onto the program as `confirmed_room_capacity`,
        increments the program's `version` by 1, and answers 200 OK."

        Design: Corner/endpoints/reservation_confirm_publishes_the_effective_capacity_onto_the_program
        """
        branch = world.branch()
        room = world.room(
            branch["id"],
            room_name="Accessible Hall",
            capacity_seats=61,
            accessibility_features=["WHEELCHAIR_ACCESSIBLE"],
        )
        program = world.program(
            branch["id"],
            title="Wheelchair Story Time",
            attendance_cap=80,
            accessibility_accommodations=["WHEELCHAIR_LAYOUT"],
        )
        reservation = world.hold(
            program["id"], room["id"], setup_minutes=30, teardown_minutes=15
        )
        assert reservation["status"] == "HELD"
        assert world.read_program(program["id"])["confirmed_room_capacity"] == 0

        confirmed = world.confirm_reservation(reservation["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["effective_capacity_seats"] == 51
        assert_instant_equals(
            confirmed["occupancy_start_utc"],
            "2026-08-12T13:30:00.000Z",
            "occupancy_start_utc",
        )
        assert_instant_equals(
            confirmed["occupancy_end_utc"],
            "2026-08-12T15:15:00.000Z",
            "occupancy_end_utc",
        )

        after = world.read_program(program["id"])
        assert after["confirmed_room_capacity"] == 51
        assert after["attendance_cap"] == 80
        assert_program_status(after, operational_status="DRAFT")
