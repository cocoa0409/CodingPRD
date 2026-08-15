"""Clearance, revision loop, approval gates, and terminal lockdown (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    clear_application,
    create_approved_application,
    create_cleared_application,
    create_committed_application,
    create_containing_do_not_travel_advisory,
    create_partner_agreement,
    create_open_program,
    create_student,
    create_submitted_application,
    get_application_version,
    make_coordinator_headers,
    make_student_headers,
    setup_open_program_with_application,
    validate_error,
    validate_success,
    api_client,
    COORD_A_HEADERS,
    COORD_B_HEADERS,
)


class TestRevisionLoop:
    def test_returned_for_revision_then_resubmit_cycles_to_submitted(self, api):
        """PRD §3.2: "A `RETURNED_FOR_REVISION` application can be resubmitted by its owning
        student, looping back to `SUBMITTED`; resubmission resets `clearance_recorded_by` to
        null so that a fresh clearance review is required before any approval."

        Design: Difficulty/non_linear_state_machine/application_revision_loop
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Loop Student", "email": "loop@uni.edu"},
        )
        returned = validate_success(
            api.record_clearance(
                application["id"],
                {"decision": "RETURNED_FOR_REVISION", "notes": "essay incomplete"},
                COORD_A_HEADERS,
            )
        )
        assert returned["status"] == "RETURNED_FOR_REVISION"
        assert returned["clearance_recorded_by"] == "coord-a", (
            "Clearance stamps clearance_recorded_by with the caller's X-User-ID"
        )

        resubmitted = validate_success(
            api.resubmit_application(application["id"], make_student_headers(student["id"]))
        )
        assert resubmitted["status"] == "SUBMITTED", (
            f"Resubmit must loop back to SUBMITTED, got {resubmitted['status']}"
        )
        assert resubmitted["clearance_recorded_by"] is None, (
            f"Resubmit must reset clearance_recorded_by to null, got {resubmitted['clearance_recorded_by']}"
        )

        cleared = validate_success(
            api.record_clearance(
                application["id"], {"decision": "CLEARED"}, COORD_A_HEADERS,
            )
        )
        assert cleared["status"] == "CLEARED", (
            "The revision loop is reusable: a second clearance reaches CLEARED"
        )

    def test_resubmit_requires_returned_for_revision(self, api):
        """PRD §3.2: "A `RETURNED_FOR_REVISION` application can be resubmitted by its owning
        student, looping back to `SUBMITTED`; resubmission resets `clearance_recorded_by` to
        null so that a fresh clearance review is required before any approval."
        PRD §2.10: "The target resource must be in a valid from-state for the requested
        transition ... otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/application_revision_loop
        """
        program, student, application = setup_open_program_with_application()
        # Resubmit from SUBMITTED (not RETURNED_FOR_REVISION) is not a valid transition.
        resp = api.resubmit_application(
            application["id"], make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSegregationOfDuties:
    def test_clearance_recorder_cannot_approve(self, api):
        """PRD §3.2: "A `ProgramCoordinator` approves a `CLEARED` application only when the
        program is still `OPEN` (otherwise `ERR_INVALID_STATE`), when the caller's `X-User-ID`
        differs from the application's `clearance_recorded_by` — the segregation-of-duties
        rule, rejecting with `ERR_SEGREGATION_OF_DUTIES` — and when the travel-warning gate
        of §3.6 is clear (`ERR_TRAVEL_ADVISORY_BLOCK`)."

        Design: Corner/validations/segregation_of_duties_on_approve
        """
        program, student, application = create_cleared_application(
            student_overrides={"full_name": "Seg Student", "email": "seg@uni.edu"},
        )
        resp = api.approve_application(application["id"], COORD_A_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(
            api.approve_application(application["id"], COORD_B_HEADERS)
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "coord-b", (
            "A successful approval stamps approved_by with the approver's identity"
        )


class TestTerminalLockdown:
    def test_application_terminal_lockdown_after_rejection(self, api):
        """PRD §3.2: "`REJECTED` is terminal." and PRD §2.10: "The target resource must be
        in a valid from-state for the requested transition ... otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/application_terminal_lockdown_after_rejection
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Term Student", "email": "term@uni.edu"},
        )
        rejected = validate_success(
            api.record_clearance(
                application["id"], {"decision": "REJECTED", "notes": "conduct case"},
                COORD_A_HEADERS,
            )
        )
        assert rejected["status"] == "REJECTED"

        resp1 = api.withdraw_application(
            application["id"], make_student_headers(student["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        resp2 = api.approve_application(application["id"], COORD_B_HEADERS)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

        reread = validate_success(api.get_application(application["id"], COORD_A_HEADERS))
        assert reread["status"] == "REJECTED", (
            "Failed transitions on a terminal state must change nothing"
        )

    def test_approve_from_submitted_returns_invalid_state(self, api):
        """PRD §3.2: "A `ProgramCoordinator` approves a `CLEARED` application ..." and
        PRD §2.10: "The target resource must be in a valid from-state for the requested
        transition ... otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/approve_from_submitted_returns_invalid_state
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Skip Student", "email": "skip@uni.edu"},
        )
        resp = api.approve_application(application["id"], COORD_B_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_depart_from_approved_returns_invalid_state(self, api):
        """PRD §3.5: "Departure itself is recorded by a `ProgramCoordinator` through the
        application's lifecycle bookkeeping with `action` set to `DEPART`, moving a
        `COMMITTED` application to `ABROAD`." and PRD §2.10: "departure requires the
        application to be `COMMITTED` ... otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/depart_from_approved_returns_invalid_state
        """
        program, student, application = create_approved_application(
            student_overrides={"full_name": "Early Bird", "email": "early@uni.edu"},
        )
        resp = api.application_lifecycle(
            application["id"], {"action": "DEPART"}, COORD_A_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(api.get_application(application["id"], COORD_A_HEADERS))
        assert reread["status"] == "APPROVED"


class TestCrossEntityStateGate:
    def test_approve_blocked_when_program_suspended(self, api):
        """PRD §3.2: "A `ProgramCoordinator` approves a `CLEARED` application only when the
        program is still `OPEN` (otherwise `ERR_INVALID_STATE`) ..."
        PRD §3.6: "The cascade continues to the program's applications: every application in
        `APPROVED` or `COMMITTED` is withdrawn with `withdraw_reason` set to
        `SYSTEM_SUSPENSION`, while `CLEARED` applications are deliberately left untouched."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_program_open
        """
        program, student, application = create_cleared_application(
            student_overrides={"full_name": "Gate Student", "email": "gate@uni.edu"},
        )
        # Fully containing DO_NOT_TRAVEL advisory suspends the OPEN program.
        create_containing_do_not_travel_advisory(program)

        resp = api.approve_application(application["id"], COORD_B_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        program_after = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert program_after["status"] == "SUSPENDED", (
            "The containing advisory must suspend the OPEN program"
        )
        app_after = validate_success(api.get_application(application["id"], COORD_A_HEADERS))
        assert app_after["status"] == "CLEARED", (
            f"The cascade withdraws only APPROVED/COMMITTED; the CLEARED application survives, got {app_after['status']}"
        )

    def test_approve_allowed_when_program_open_and_no_advisory(self, api):
        """PRD §3.2: "A `ProgramCoordinator` approves a `CLEARED` application only when the
        program is still `OPEN` (otherwise `ERR_INVALID_STATE`) ..."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_program_open
        """
        program, student, application = create_cleared_application()
        approved = validate_success(
            api.approve_application(application["id"], COORD_B_HEADERS)
        )
        assert approved["status"] == "APPROVED"


class TestDepartInsuranceGate:
    def test_depart_without_covering_insurance_rejected(self, api):
        """PRD §3.5: "The gate is insurance: an `ACTIVE` enrollment for the application must
        exist whose coverage fully contains the program dates — `coverage_start_date` at or
        before `start_date` and `coverage_end_date` at or after `end_date` — otherwise the
        transition fails with `ERR_INSURANCE_COVERAGE_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/depart_requires_covering_insurance
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Uninsured Student", "email": "uninsured@uni.edu"},
        )
        resp = api.application_lifecycle(
            application["id"], {"action": "DEPART"}, COORD_A_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_COVERAGE_MISSING)
        reread = validate_success(api.get_application(application["id"], COORD_A_HEADERS))
        assert reread["status"] == "COMMITTED"

    def test_depart_with_covering_insurance_succeeds(self, api):
        """PRD §3.5: "Departure itself is recorded by a `ProgramCoordinator` through the
        application's lifecycle bookkeeping with `action` set to `DEPART`, moving a
        `COMMITTED` application to `ABROAD`."

        Design: Difficulty/cross_entity_state_dependency/depart_requires_covering_insurance
        """
        from test_helpers import create_abroad_application

        program, student, application = create_abroad_application()
        assert application["status"] == "ABROAD", (
            "A COMMITTED application with covering ACTIVE insurance departs to ABROAD"
        )
