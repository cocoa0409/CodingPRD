"""Rejections around rooms, drafted windows and registration intake.

Each case drives one gate of the validation ladder to its refusal and then reads
the persisted state back to prove the refusal was total: no reservation row, no
advanced status, no consumed seat.  Where a gate has an admissible neighbour the
neighbour is exercised in the same test, so the boundary is pinned from both
sides rather than merely asserted once.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_ACCESSIBILITY_UNSUPPORTED,
    ERR_BRANCH_CODE_DUPLICATE,
    ERR_DUPLICATE_REGISTRANT,
    ERR_INVALID_PROGRAM_WINDOW,
    ERR_PARTNER_FIELDS_REQUIRED,
    ERR_PARTNER_INSURANCE_LAPSED,
    ERR_PROGRAM_AT_CAPACITY,
    ERR_PROGRAM_COMPLIANCE_BLOCKED,
    ERR_PROGRAM_STATE_INVALID,
    ERR_REGISTRATION_WINDOW_CLOSED,
    ERR_RESERVATION_WINDOW_MISMATCH,
    ERR_ROOM_OUT_OF_SERVICE,
    ERR_SETUP_BUFFER_TOO_SHORT,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_program_status,
)
from test_helpers.factories import (
    branch_payload,
    program_payload,
    registration_payload,
    reservation_payload,
)
from test_helpers.fixtures import LibraryWorld


class TestRoomBookingRefusals:
    """Four reservation gates, each read back through the reservation listing."""

    def test_a_room_out_of_service_cannot_be_booked_at_all(
        self, world: LibraryWorld
    ) -> None:
        """The room's own status closes it before any occupancy arithmetic runs.

        "A room's `status` is either `AVAILABLE` or `OUT_OF_SERVICE` and defaults
        to `AVAILABLE` when the creating request omits it; a room that is
        `OUT_OF_SERVICE` cannot be booked, and an attempt to reserve it is rejected
        with `ERR_ROOM_OUT_OF_SERVICE`."

        Design: Corner/validations/reservation_on_an_out_of_service_room_rejected
        """
        branch = world.branch()
        room = world.room(branch["id"], status="OUT_OF_SERVICE")
        program = world.program(branch["id"])

        validate_error(
            world.api.create_reservation(
                program["id"],
                reservation_payload(room["id"], program["version"]),
                world.coordinator,
            ),
            ERR_ROOM_OUT_OF_SERVICE,
            ERROR_HTTP_STATUS[ERR_ROOM_OUT_OF_SERVICE],
        )

        _, meta = validate_paginated(
            world.api.list_reservations(world.coordinator, program_id=program["id"])
        )
        assert meta["total_count"] == 0
        assert_program_status(
            world.read_program(program["id"]), operational_status="DRAFT"
        )

    def test_a_wheelchair_promise_needs_a_wheelchair_accessible_room(
        self, world: LibraryWorld
    ) -> None:
        """A hearing loop is the wrong fitting for a wheelchair layout.

        "If the program's `accessibility_accommodations` contain
        `WHEELCHAIR_LAYOUT`, the room's `accessibility_features` must contain
        `WHEELCHAIR_ACCESSIBLE`."

        Design: Corner/validations/wheelchair_layout_in_a_room_without_wheelchair_access_rejected
        """
        branch = world.branch()
        room = world.room(
            branch["id"],
            room_name="Hearing Loop Room",
            accessibility_features=["HEARING_LOOP"],
        )
        program = world.program(
            branch["id"], accessibility_accommodations=["WHEELCHAIR_LAYOUT"]
        )

        validate_error(
            world.api.create_reservation(
                program["id"],
                reservation_payload(
                    room["id"], program["version"], setup_minutes=30
                ),
                world.coordinator,
            ),
            ERR_ACCESSIBILITY_UNSUPPORTED,
            ERROR_HTTP_STATUS[ERR_ACCESSIBILITY_UNSUPPORTED],
        )

        _, meta = validate_paginated(
            world.api.list_reservations(world.coordinator, room_id=room["id"])
        )
        assert meta["total_count"] == 0
        assert world.read_program(program["id"])[
            "accessibility_accommodations"
        ] == ["WHEELCHAIR_LAYOUT"]

    def test_any_accommodation_at_all_raises_the_setup_floor_to_thirty_minutes(
        self, world: LibraryWorld
    ) -> None:
        """Twenty minutes clears the room's fifteen and still falls short.

        "The claimed `setup_minutes` must be at least the greater of the room's
        own `min_setup_minutes` and — whenever the program's
        `accessibility_accommodations` array is non-empty, whatever it contains —
        an accessible-setup floor of 30 minutes".

        Design: Corner/validations/accessible_program_with_a_twenty_minute_setup_rejected
        """
        branch = world.branch()
        room = world.room(branch["id"], min_setup_minutes=15, min_teardown_minutes=15)
        program = world.program(
            branch["id"], accessibility_accommodations=["LARGE_PRINT_HANDOUTS"]
        )

        validate_error(
            world.api.create_reservation(
                program["id"],
                reservation_payload(
                    room["id"], program["version"], setup_minutes=20
                ),
                world.coordinator,
            ),
            ERR_SETUP_BUFFER_TOO_SHORT,
            ERROR_HTTP_STATUS[ERR_SETUP_BUFFER_TOO_SHORT],
        )
        _, meta = validate_paginated(
            world.api.list_reservations(world.coordinator, program_id=program["id"])
        )
        assert meta["total_count"] == 0

        accepted = get_success_data(
            world.api.create_reservation(
                program["id"],
                reservation_payload(
                    room["id"], program["version"], setup_minutes=30
                ),
                world.coordinator,
            ),
            201,
        )
        assert accepted["setup_minutes"] == 30
        assert accepted["status"] == "HELD"

    def test_a_booking_that_starts_late_fails_however_generous_its_buffers(
        self, world: LibraryWorld
    ) -> None:
        """The rule reads the reservation's own window, not its occupancy window.

        "the reservation's `start_utc` must be at or before the program's
        `start_utc` and its `end_utc` at or after the program's `end_utc`, since
        the room has to be the library's for the whole advertised event."

        Design: Corner/validations/reservation_that_starts_after_the_public_window_rejected
        """
        branch = world.branch()
        room = world.room(branch["id"])
        program = world.program(branch["id"])

        validate_error(
            world.api.create_reservation(
                program["id"],
                reservation_payload(
                    room["id"],
                    program["version"],
                    start_utc="2026-08-12T14:15:00.000Z",
                    end_utc="2026-08-12T15:15:00.000Z",
                    setup_minutes=30,
                    teardown_minutes=30,
                ),
                world.coordinator,
            ),
            ERR_RESERVATION_WINDOW_MISMATCH,
            ERROR_HTTP_STATUS[ERR_RESERVATION_WINDOW_MISMATCH],
        )

        _, meta = validate_paginated(
            world.api.list_reservations(world.coordinator, program_id=program["id"])
        )
        assert meta["total_count"] == 0
        program_after = world.read_program(program["id"])
        assert_instant_equals(
            program_after["start_utc"], "2026-08-12T14:00:00.000Z", "start_utc"
        )


class TestDraftTimeCoherenceRefusals:
    """Windows, partner trios and branch codes, all checked before persistence."""

    def test_a_window_that_ends_before_it_starts_is_refused_at_draft_time(
        self, world: LibraryWorld
    ) -> None:
        """Both instants parse cleanly, so the failure is the ordering rule.

        "Separately, the drafted window must satisfy `start_utc` strictly before
        `end_utc`, and both instants must lie at or after the logical clock at the
        time of drafting; a violation is `ERR_INVALID_PROGRAM_WINDOW`."

        Design: Corner/validations/program_created_with_end_before_start_rejected
        """
        branch = world.branch()

        validate_error(
            world.api.create_program(
                program_payload(
                    branch["id"],
                    start_utc="2026-08-12T15:00:00.000Z",
                    end_utc="2026-08-12T14:00:00.000Z",
                ),
                world.coordinator,
            ),
            ERR_INVALID_PROGRAM_WINDOW,
            ERROR_HTTP_STATUS[ERR_INVALID_PROGRAM_WINDOW],
        )

        _, meta = validate_paginated(world.api.list_programs(world.coordinator))
        assert meta["total_count"] == 0

    def test_the_partner_trio_rule_bites_in_both_directions(
        self, world: LibraryWorld
    ) -> None:
        """Supplying partner fields in branch is as wrong as omitting them offsite.

        "When `delivery_mode` is `IN_BRANCH` the mirror image is required:
        `partner_type` must be `NONE` (which is also its default) and both
        `partner_org_name` and `partner_insurance_expires_on` must be null. Either
        form of incoherence is rejected with `ERR_PARTNER_FIELDS_REQUIRED`."

        Design: Corner/validations/in_branch_program_carrying_partner_fields_rejected
        """
        branch = world.branch()

        validate_error(
            world.api.create_program(
                program_payload(
                    branch["id"],
                    delivery_mode="IN_BRANCH",
                    partner_type="SCHOOL",
                ),
                world.coordinator,
            ),
            ERR_PARTNER_FIELDS_REQUIRED,
            ERROR_HTTP_STATUS[ERR_PARTNER_FIELDS_REQUIRED],
        )
        validate_error(
            world.api.create_program(
                program_payload(branch["id"], delivery_mode="PARTNER_SITE"),
                world.coordinator,
            ),
            ERR_PARTNER_FIELDS_REQUIRED,
            ERROR_HTTP_STATUS[ERR_PARTNER_FIELDS_REQUIRED],
        )

        _, meta = validate_paginated(world.api.list_programs(world.coordinator))
        assert meta["total_count"] == 0

    def test_a_reschedule_past_the_partner_certificate_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The same certificate date passes at draft time and fails at publication.

        "a `PARTNER_SITE` program never holds a room reservation at all — its
        space gate is instead that `partner_insurance_expires_on` falls on or after
        the calendar date of `end_utc`, failing which the request is rejected with
        `ERR_PARTNER_INSURANCE_LAPSED`."

        Design: Corner/validations/rescheduling_a_partner_program_past_its_certificate_rejected
        """
        branch = world.branch()
        program = world.program(
            branch["id"],
            title="School Outreach Hour",
            delivery_mode="PARTNER_SITE",
            partner_type="SCHOOL",
            partner_org_name="Riverside Elementary",
            partner_insurance_expires_on="2026-08-20",
        )

        validate_error(
            world.api.schedule_program(
                program["id"],
                world.coordinator,
                {
                    "start_utc": "2026-08-25T14:00:00.000Z",
                    "end_utc": "2026-08-25T15:00:00.000Z",
                },
            ),
            ERR_PARTNER_INSURANCE_LAPSED,
            ERROR_HTTP_STATUS[ERR_PARTNER_INSURANCE_LAPSED],
        )

        after = world.read_program(program["id"])
        assert_instant_equals(
            after["start_utc"], "2026-08-12T14:00:00.000Z", "start_utc"
        )
        assert_instant_equals(after["end_utc"], "2026-08-12T15:00:00.000Z", "end_utc")
        assert_program_status(after, operational_status="DRAFT")

    def test_a_second_branch_may_not_reuse_a_branch_code(
        self, world: LibraryWorld
    ) -> None:
        """A different display name does not make the code free.

        "a `branch_code` — a short code of between 2 and 8 uppercase characters
        that must be unique across all branches; a collision is rejected with
        `ERR_BRANCH_CODE_DUPLICATE`."

        Design: Corner/validations/second_branch_reusing_a_branch_code_rejected
        """
        first = world.branch(name="Central Library", branch_code="CEN")

        validate_error(
            world.api.create_branch(
                branch_payload(name="North Library", branch_code="CEN"),
                world.manager,
            ),
            ERR_BRANCH_CODE_DUPLICATE,
            ERROR_HTTP_STATUS[ERR_BRANCH_CODE_DUPLICATE],
        )

        unchanged = world.read_branch(first["id"])
        assert unchanged["branch_code"] == "CEN"
        assert unchanged["name"] == "Central Library"


def _scheduled_registration_program(
    world: LibraryWorld, **room_kwargs: Any
) -> Dict[str, Any]:
    """A published REGISTRATION program holding a room, ready to take names."""
    branch = world.branch()
    room = world.room(branch["id"], **room_kwargs)
    program = world.program(branch["id"])
    reservation = world.hold(program["id"], room["id"])
    return {
        "branch": branch,
        "room": room,
        "program": program,
        "reservation": reservation,
    }


class TestRegistrationIntakeRefusals:
    """The window, the duplicate rule and the tighter of two ceilings."""

    def test_registration_closes_the_moment_the_program_starts(
        self, world: LibraryWorld
    ) -> None:
        """Half past two is inside the session, and that is already too late.

        "Registration closes at the moment the program starts: the logical clock
        must be strictly before the program's `start_utc`, and a request at or after
        that instant is rejected with `ERR_REGISTRATION_WINDOW_CLOSED`."

        Design: Corner/validations/registration_after_the_program_has_started_rejected
        """
        scenario = _scheduled_registration_program(world)
        program_id = scenario["program"]["id"]
        world.schedule(program_id)
        world.set_clock("2026-08-12T14:30:00.000Z")

        validate_error(
            world.api.register(
                program_id, registration_payload("card-0001"), world.coordinator
            ),
            ERR_REGISTRATION_WINDOW_CLOSED,
            ERROR_HTTP_STATUS[ERR_REGISTRATION_WINDOW_CLOSED],
        )

        after = world.read_program(program_id)
        assert after["registered_count"] == 0
        assert after["registrant_references"] == []
        assert_program_status(after, operational_status="SCHEDULED")

    def test_the_same_party_may_not_take_a_second_place(
        self, world: LibraryWorld
    ) -> None:
        """The reference list behaves as a set, and the refusal costs no seat.

        "The same party may not register twice, so a `registrant_reference`
        already present in the program's `registrant_references` array is rejected
        with `ERR_DUPLICATE_REGISTRANT`."

        Design: Corner/validations/repeating_a_registrant_reference_rejected
        """
        scenario = _scheduled_registration_program(world)
        program_id = scenario["program"]["id"]
        world.schedule(program_id)
        world.register(program_id, registrant_reference="card-0001")

        validate_error(
            world.api.register(
                program_id, registration_payload("card-0001"), world.coordinator
            ),
            ERR_DUPLICATE_REGISTRANT,
            ERROR_HTTP_STATUS[ERR_DUPLICATE_REGISTRANT],
        )

        after = world.read_program(program_id)
        assert after["registered_count"] == 1
        assert after["registrant_references"] == ["card-0001"]

    def test_the_confirmed_room_binds_tighter_than_the_advertised_cap(
        self, world: LibraryWorld
    ) -> None:
        """Four seats beat a cap of twenty, and the refusal is on the running total.

        "When the program has a `CONFIRMED` room reservation — that is, when
        `confirmed_room_capacity` is greater than 0 — the ceiling is the smaller of
        `attendance_cap` and `confirmed_room_capacity`".

        Design: Corner/validations/registrations_exceeding_the_confirmed_room_ceiling_rejected
        """
        scenario = _scheduled_registration_program(world, capacity_seats=4)
        program_id = scenario["program"]["id"]
        world.confirm_reservation(scenario["reservation"]["id"])
        world.schedule(program_id)
        world.register(program_id, registrant_reference="card-0001", seats=3)

        validate_error(
            world.api.register(
                program_id,
                registration_payload("card-0002", seats=2),
                world.coordinator,
            ),
            ERR_PROGRAM_AT_CAPACITY,
            ERROR_HTTP_STATUS[ERR_PROGRAM_AT_CAPACITY],
        )

        refused = world.read_program(program_id)
        assert refused["registered_count"] == 3
        assert refused["registrant_references"] == ["card-0001"]
        assert refused["confirmed_room_capacity"] == 4
        assert refused["attendance_cap"] == 20

        accepted = world.register(
            program_id, registrant_reference="card-0003", seats=1
        )
        assert accepted["registered_count"] == 4

    def test_a_cancelled_drop_in_program_reports_its_state_not_its_policy(
        self, world: LibraryWorld
    ) -> None:
        """Two gates are breached at once and the earlier one answers.

        "The program must be in `SCHEDULED` or `CONFIRMED` status — a `DRAFT`
        program is not yet public and a closed or cancelled one is past registering
        — and anything else is `ERR_PROGRAM_STATE_INVALID`."

        Design: Corner/validations/registration_on_a_cancelled_drop_in_program_reports_the_state_error
        """
        branch = world.branch()
        program = world.program(
            branch["id"], title="Drop In Story Time", registration_policy="DROP_IN"
        )
        world.cancel(program["id"], "LOW_ENROLMENT")

        error = validate_error(
            world.api.register(
                program["id"], registration_payload("card-0001"), world.coordinator
            ),
            ERR_PROGRAM_STATE_INVALID,
            ERROR_HTTP_STATUS[ERR_PROGRAM_STATE_INVALID],
        )
        assert error["error_id"] == ERR_PROGRAM_STATE_INVALID

        after = world.read_program(program["id"])
        assert_program_status(after, operational_status="CANCELLED")
        assert after["registered_count"] == 0
        assert after["closure_reason"] == "LOW_ENROLMENT"

    def test_a_screening_in_flight_stops_confirmation_but_not_the_public(
        self, world: LibraryWorld
    ) -> None:
        """One compliance value, two endpoints, two different answers.

        "A program whose `compliance_status` is `BLOCKED` stops accepting
        registrations and reports `ERR_PROGRAM_COMPLIANCE_BLOCKED`; a program whose
        `compliance_status` is merely `PENDING_SCREENING` keeps accepting them, on
        the reasoning that a screening still in flight is not yet a reason to turn
        the public away."

        Design: Corner/validations/pending_screening_blocks_confirm_yet_registrations_continue
        """
        scenario = _scheduled_registration_program(world)
        program_id = scenario["program"]["id"]
        world.supply_lot(scenario["branch"]["id"])
        world.confirm_reservation(scenario["reservation"]["id"])
        world.schedule(program_id)
        presenter = world.presenter()
        contract = world.contract(presenter["id"], program_id)

        validate_error(
            world.api.confirm_program(program_id, world.manager),
            ERR_PROGRAM_COMPLIANCE_BLOCKED,
            ERROR_HTTP_STATUS[ERR_PROGRAM_COMPLIANCE_BLOCKED],
        )

        registered = world.register(
            program_id, registrant_reference="card-0001", seats=2
        )
        assert registered["registered_count"] == 2

        after = world.read_program(program_id)
        assert_program_status(
            after,
            operational_status="SCHEDULED",
            compliance_status="PENDING_SCREENING",
        )
        assert after["materials_committed_cents"] == 0
        assert world.read_contract(contract["id"])["status"] == "DRAFT"
