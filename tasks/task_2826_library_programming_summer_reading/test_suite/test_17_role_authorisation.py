"""Who may act: role denials, shared operations, ownership and segregation.

The authorisation surface has four distinct shapes and each is exercised here
against the state it must leave untouched.  A role that is not listed on an
endpoint is refused before its body is read; a reader is scoped to their own
participant record; two roles genuinely share the booking endpoints; and one
refusal turns on the acting user id rather than on the role at all.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_LOG_SOURCE_NOT_PERMITTED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import assert_program_status
from test_helpers.factories import (
    branch_payload,
    log_entry_payload,
    program_payload,
    reservation_payload,
    screening_request_payload,
)
from test_helpers.fixtures import LibraryWorld
from test_helpers.test_users import (
    COORDINATOR_USER_ID,
    MANAGER_USER_ID,
    NO_AUTH_HEADERS,
    SECOND_MANAGER_USER_ID,
    make_reader_headers,
)


class TestRolesRefusedOnEndpointsTheyDoNotOwn:
    """A role absent from an endpoint's list is turned away before its body is read."""

    def test_the_screening_officer_cannot_draft_a_program(
        self, world: LibraryWorld
    ) -> None:
        """Nothing is created, and the refusal does not depend on the payload.

        "outside of screening requests, screening results and adjudications this
        role may only read a presenter record, read a branch record and set the
        logical clock" and "If `X-User-Role` carries a value that is not one of the
        four recognised roles, or carries a recognised role that is not authorised
        for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` and HTTP 403."

        Design: Corner/rbac/screening_officer_cannot_create_a_program
        """
        branch = world.branch()

        refused = world.api.create_program(
            program_payload(branch["id"]), world.officer
        )
        validate_error(
            refused, ERR_UNAUTHORIZED, ERROR_HTTP_STATUS[ERR_UNAUTHORIZED]
        )

        _, meta = validate_paginated(world.api.list_programs(world.coordinator))
        assert meta["total_count"] == 0

    def test_the_coordinator_may_negotiate_but_neither_execute_nor_confirm(
        self, world: LibraryWorld
    ) -> None:
        """The same coordinator's offer stands while both commitments are refused.

        "they build the calendar, book and confirm rooms, take registrations,
        register presenters, draft contracts and negotiate fees, enrol readers and
        keep the reading log on readers' behalf — but they may never execute a
        contract and may never confirm, close out, weather-close or cancel a
        program."

        Design: Corner/rbac/coordinator_cannot_execute_a_contract_or_confirm_a_program
        """
        branch = world.branch()
        room = world.room(branch["id"])
        world.supply_lot(branch["id"])
        program = world.adult_program(branch["id"])
        reservation = world.hold(
            program["id"],
            room["id"],
            start_utc="2026-08-12T18:00:00.000Z",
            end_utc="2026-08-12T19:00:00.000Z",
        )
        world.confirm_reservation(reservation["id"])
        world.schedule(program["id"])
        presenter = world.presenter()
        contract = world.contract(presenter["id"], program["id"])
        offered = world.offer(contract["id"], 50000, headers=world.coordinator)
        assert offered["status"] == "OFFERED"
        assert offered["offered_by_user_id"] == COORDINATOR_USER_ID

        refused_execute = world.api.execute_contract(
            contract["id"], world.coordinator
        )
        validate_error(
            refused_execute, ERR_UNAUTHORIZED, ERROR_HTTP_STATUS[ERR_UNAUTHORIZED]
        )
        refused_confirm = world.api.confirm_program(program["id"], world.coordinator)
        validate_error(
            refused_confirm, ERR_UNAUTHORIZED, ERROR_HTTP_STATUS[ERR_UNAUTHORIZED]
        )

        untouched_contract = world.read_contract(contract["id"])
        assert untouched_contract["status"] == "OFFERED"
        assert untouched_contract["offered_by_user_id"] == COORDINATOR_USER_ID
        assert untouched_contract["total_fee_cents"] == 0

        untouched_program = world.read_program(program["id"])
        assert_program_status(untouched_program, operational_status="SCHEDULED")
        assert untouched_program["materials_committed_cents"] == 0


class TestReaderOwnershipScope:
    """A reader is confined to their own participant record and nothing else."""

    def test_a_reader_is_barred_from_the_collection_and_from_a_peer(
        self, world: LibraryWorld
    ) -> None:
        """Two different refusals, and the reader's own record still reads.

        "ownership checks compare the `{participant_id}` named in the request path
        against `X-User-Id`, and a mismatch is rejected with
        `ERR_NOT_RESOURCE_OWNER` and HTTP 403" and "a `Reader` may only read their
        own record".

        Design: Corner/rbac/reader_cannot_list_participants_or_read_another_participant
        """
        branch = world.branch()
        opened = world.opened_challenge()
        challenge_id = opened["challenge"]["id"]
        reader_a = world.participant(
            challenge_id, branch["id"], display_name="Ada L.", age_band="AGE_5_11"
        )
        reader_b = world.participant(
            challenge_id, branch["id"], display_name="Bo N.", age_band="AGE_12_17"
        )
        a_headers = make_reader_headers(reader_a["id"])

        validate_error(
            world.api.list_participants(a_headers),
            ERR_UNAUTHORIZED,
            ERROR_HTTP_STATUS[ERR_UNAUTHORIZED],
        )
        validate_error(
            world.api.get_participant(reader_b["id"], a_headers),
            ERR_NOT_RESOURCE_OWNER,
            ERROR_HTTP_STATUS[ERR_NOT_RESOURCE_OWNER],
        )

        own_record = get_success_data(
            world.api.get_participant(reader_a["id"], a_headers), 200
        )
        assert own_record["id"] == reader_a["id"]
        assert own_record["cumulative_units"] == 0

    def test_a_reader_logging_against_a_peer_is_refused_on_ownership_first(
        self, world: LibraryWorld
    ) -> None:
        """The provenance rule sits far below ownership, so ownership answers.

        "7. A `Reader`'s `X-User-Id` equals the `{participant_id}` in the path —
        `ERR_NOT_RESOURCE_OWNER`" and "35. The log entry's provenance is permitted
        for the acting role — `ERR_LOG_SOURCE_NOT_PERMITTED`".

        Design: Corner/rbac/reader_cannot_log_units_for_another_participant
        """
        branch = world.branch()
        opened = world.opened_challenge()
        challenge_id = opened["challenge"]["id"]
        reader_a = world.participant(
            challenge_id, branch["id"], display_name="Ada L.", age_band="AGE_5_11"
        )
        reader_b = world.participant(
            challenge_id, branch["id"], display_name="Bo N.", age_band="AGE_12_17"
        )

        refused = world.api.create_log_entry(
            reader_b["id"],
            log_entry_payload(30, "2026-08-01", "STAFF_DESK"),
            make_reader_headers(reader_a["id"]),
        )
        error = validate_error(
            refused,
            ERR_NOT_RESOURCE_OWNER,
            ERROR_HTTP_STATUS[ERR_NOT_RESOURCE_OWNER],
        )
        assert error["error_id"] != ERR_LOG_SOURCE_NOT_PERMITTED

        peer = world.read_participant(reader_b["id"])
        assert peer["cumulative_units"] == 0
        assert peer["entry_count"] == 0


class TestSharedAndExclusiveOperations:
    """Some operations two roles genuinely share; others exactly one role owns."""

    def test_both_coordinating_roles_may_hold_a_room_for_the_same_program(
        self, world: LibraryWorld
    ) -> None:
        """Neither create is refused, and the second displaces the first.

        "Booking a room is a two-step affair — hold, then confirm — and both steps
        are open to a `ProgramCoordinator` or a `ProgramManager`." and "the program's
        prior `HELD` reservation moves to `SUPERSEDED` and the new one becomes the
        program's `HELD` reservation" and "Every accepted reservation create
        increments the program's `version` by 1, so a client that creates two
        reservations in a row must re-read the program between them."

        Design: Corner/rbac/manager_and_coordinator_share_reservation_creation
        """
        branch = world.branch()
        room = world.room(branch["id"])
        program = world.program(branch["id"])
        drafted_version = program["version"]

        managers_hold = get_success_data(
            world.api.create_reservation(
                program["id"],
                reservation_payload(room["id"], drafted_version),
                world.manager,
            ),
            201,
        )
        after_first = world.read_program(program["id"])
        assert after_first["version"] == drafted_version + 1

        coordinators_hold = get_success_data(
            world.api.create_reservation(
                program["id"],
                reservation_payload(room["id"], after_first["version"]),
                world.coordinator,
            ),
            201,
        )

        assert world.read_reservation(managers_hold["id"])["status"] == "SUPERSEDED"
        assert world.read_reservation(coordinators_hold["id"])["status"] == "HELD"
        assert world.read_program(program["id"])["version"] == drafted_version + 2

    def test_only_the_screening_officer_may_open_a_screening(
        self, world: LibraryWorld
    ) -> None:
        """The manager's identical request is refused; the screening dimension moves alone.

        "Background screening is the exclusive province of a `ScreeningOfficer`" and
        "The request sets `screening_decision` to `PENDING`, stores the supplied
        tier, clears `screening_decided_on` and `screening_valid_until` back to null,
        leaves `screening_status` at `PENDING`, increments the presenter's `version`
        by 1 and answers 200 OK with the presenter."

        Design: Corner/rbac/screening_officer_exclusively_owns_the_screening_request
        """
        presenter = world.presenter()
        assert presenter["screening_decision"] == "NONE"

        refused = world.api.request_screening(
            presenter["id"], screening_request_payload("FINGERPRINT"), world.manager
        )
        validate_error(
            refused, ERR_UNAUTHORIZED, ERROR_HTTP_STATUS[ERR_UNAUTHORIZED]
        )
        assert world.read_presenter(presenter["id"])["screening_decision"] == "NONE"

        accepted = get_success_data(
            world.api.request_screening(
                presenter["id"],
                screening_request_payload("FINGERPRINT"),
                world.officer,
            ),
            200,
        )
        assert accepted["screening_decision"] == "PENDING"
        assert accepted["screening_tier"] == "FINGERPRINT"
        assert accepted["screening_status"] == "PENDING"
        assert accepted["screening_valid_until"] is None
        assert accepted["screening_decided_on"] is None
        assert accepted["engagement_status"] == "PROSPECT"


class TestSegregationOfDutiesAndAuthentication:
    """One refusal turns on the user id; one outranks every other check."""

    def test_the_offering_manager_cannot_execute_but_a_second_manager_can(
        self, world: LibraryWorld
    ) -> None:
        """The identical request succeeds once a different user id makes it.

        "Segregation of duties is enforced on the user id, not on the role." and
        "that same `X-User-Id` may then not execute it. A second `ProgramManager`
        user id must perform the execution, and an attempt by the offering user is
        rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."

        Design: Corner/rbac/same_user_cannot_offer_and_then_execute_one_contract
        """
        branch = world.branch()
        program = world.adult_program(branch["id"])
        presenter = world.presenter()
        contract = world.contract(presenter["id"], program["id"])
        world.offer(contract["id"], 50000, headers=world.manager)

        refused = world.api.execute_contract(contract["id"], world.manager)
        validate_error(
            refused,
            ERR_SEGREGATION_OF_DUTIES,
            ERROR_HTTP_STATUS[ERR_SEGREGATION_OF_DUTIES],
        )
        assert world.read_contract(contract["id"])["status"] == "OFFERED"

        executed = get_success_data(
            world.api.execute_contract(contract["id"], world.second_manager), 200
        )
        assert executed["status"] == "EXECUTED"
        assert executed["total_fee_cents"] == 50000
        assert executed["executed_by_user_id"] == SECOND_MANAGER_USER_ID
        assert executed["offered_by_user_id"] == MANAGER_USER_ID

        staffed = world.read_program(program["id"])
        assert_program_status(staffed, compliance_status="CLEARED")
        assert staffed["presenter_fee_committed_cents"] == 50000

    def test_a_request_carrying_no_identity_headers_is_unauthenticated(
        self, world: LibraryWorld
    ) -> None:
        """A perfectly valid branch payload is still refused, and stores nothing.

        "If either header is absent or present but empty, the request is rejected
        with `ERR_UNAUTHENTICATED` and HTTP 401." and "1. Both authentication headers
        present and non-empty — `ERR_UNAUTHENTICATED` — every endpoint."

        Design: Corner/rbac/request_without_the_role_header_returns_401
        """
        world.pin_clock()

        refused = world.api.create_branch(branch_payload(), NO_AUTH_HEADERS)
        validate_error(
            refused, ERR_UNAUTHENTICATED, ERROR_HTTP_STATUS[ERR_UNAUTHENTICATED]
        )

        _, meta = validate_paginated(world.api.list_rooms(world.coordinator))
        assert meta["total_count"] == 0
