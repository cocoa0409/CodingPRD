"""Insurance enrollment rules and the safety-vs-temporal priority pair (PRD §3.5, §2.10)."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    clear_application,
    commit_application,
    create_abroad_application,
    create_committed_application,
    create_travel_advisory,
    enroll_insurance,
    make_student_headers,
    set_logical_clock,
    validate_error,
    validate_success,
    api_client,
    COORD_A_HEADERS,
)


class TestCoverageWindow:
    def test_coverage_window_insufficient_alone(self, api):
        """PRD §3.5: "`coverage_start_date` must fall at or before the program's
        `start_date`, and `coverage_end_date` must fall at or after the program's `end_date`
        while remaining strictly after the coverage start. A window that fails to fully
        contain the program dates is rejected with `ERR_COVERAGE_WINDOW_INSUFFICIENT`."

        Design: Corner/validations/coverage_window_insufficient_alone
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Cover Student", "email": "cover@uni.edu"},
        )
        # coverage_end 2027-05-01 precedes the program end 2027-05-10.
        resp = api.create_insurance_enrollment(
            {
                "application_id": application["id"],
                "provider": "GlobalCare",
                "coverage_start_date": "2027-01-01T00:00:00Z",
                "coverage_end_date": "2027-05-01T00:00:00Z",
            },
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_INSUFFICIENT)

    def test_coverage_window_containing_program_accepted(self, api):
        """PRD §3.5: "The owning student creates an **insurance enrollment** for a
        `COMMITTED` application ... `coverage_start_date` must fall at or before the
        program's `start_date`, and `coverage_end_date` must fall at or after the program's
        `end_date` ... Enrollments are born `ACTIVE`."

        Design: Corner/validations/coverage_window_insufficient_alone
        """
        program, student, application = create_committed_application()
        enrollment = enroll_insurance(application, student)
        assert enrollment["status"] == "ACTIVE"


class TestDuplicateEnrollment:
    def test_duplicate_enrollment_blocked(self, api):
        """PRD §3.5: "At most one `ACTIVE` enrollment may exist per application
        (`ERR_DUPLICATE_ENROLLMENT`)."

        Design: Corner/validations/duplicate_enrollment_blocked
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Insured Student", "email": "insured@uni.edu"},
        )
        enroll_insurance(application, student)
        resp = api.create_insurance_enrollment(
            {
                "application_id": application["id"],
                "provider": "SafeTravel",
                "coverage_start_date": "2027-01-01T00:00:00Z",
                "coverage_end_date": "2027-05-31T00:00:00Z",
            },
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)


class TestCancelWhileAbroad:
    def test_cannot_cancel_insurance_while_abroad(self, api):
        """PRD §3.5: "The owning student or a `ProgramCoordinator` may cancel, but never
        while the linked application is `ABROAD` — the safety lock rejects that attempt with
        `ERR_CANNOT_CANCEL_WHILE_ABROAD`, since a student on site must not lose coverage
        mid-program."

        Design: Corner/validations/cannot_cancel_insurance_while_abroad
        """
        program, student, application = create_abroad_application(
            student_overrides={"full_name": "Abroad Cancel", "email": "abcancel@uni.edu"},
        )
        # The fixture created one ACTIVE enrollment before departure.
        from test_helpers import validate_paginated
        ins_resp = api.list_insurance_enrollments(
            COORD_A_HEADERS, params={"application_id": application["id"]},
        )
        ins_data, _m = validate_paginated(ins_resp)
        enrollment = ins_data[0]

        resp = api.cancel_insurance_enrollment(
            enrollment["id"], make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CANNOT_CANCEL_WHILE_ABROAD)
        reread = validate_success(
            api.get_insurance_enrollment(enrollment["id"], COORD_A_HEADERS)
        )
        assert reread["status"] == "ACTIVE"


class TestSafetyBeatsTemporal:
    def test_safety_beats_temporal_on_enrollment(self, api):
        """PRD §2.10: "Safety gates. The travel-warning gate on application approval and
        insurance enrollment creation, and the insurance-cancel safety lock — surfacing as
        `ERR_TRAVEL_ADVISORY_BLOCK` or `ERR_CANNOT_CANCEL_WHILE_ABROAD` respectively."
        (tier 7, evaluated before "Temporal rules. ... `ERR_COVERAGE_WINDOW_INSUFFICIENT`"
        at tier 8.)

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_enrollment
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Safety Student", "email": "safety@uni.edu"},
        )
        # Partial-overlap advisory in effect at the clock; program NOT suspended
        # (window does not fully contain the program dates).
        set_logical_clock("2027-05-05T00:00:00Z")
        create_travel_advisory(
            country_code="FR", level="DO_NOT_TRAVEL",
            effective_from="2027-05-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z",
        )

        # Coverage window is ALSO too short (2027-05-01 < program end 2027-05-10).
        resp = api.create_insurance_enrollment(
            {
                "application_id": application["id"],
                "provider": "GlobalCare",
                "coverage_start_date": "2027-01-01T00:00:00Z",
                "coverage_end_date": "2027-05-01T00:00:00Z",
            },
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRAVEL_ADVISORY_BLOCK)

        app_after = validate_success(api.get_application(application["id"], COORD_A_HEADERS))
        assert app_after["status"] == "COMMITTED", (
            "Partial overlap does not trigger the suspension cascade"
        )

    def test_travel_gate_alone_blocks_enrollment(self, api):
        """PRD §3.5: "Enrollment creation is also subject to the travel-warning gate of
        §3.6, rejecting with `ERR_TRAVEL_ADVISORY_BLOCK` when a blocking advisory is in
        force."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_enrollment
        """
        program, student, application = create_committed_application()
        set_logical_clock("2027-05-05T00:00:00Z")
        create_travel_advisory(
            country_code="FR", level="DO_NOT_TRAVEL",
            effective_from="2027-05-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z",
        )
        # This time the coverage window fully contains the program dates, so only the
        # travel gate can fire.
        resp = api.create_insurance_enrollment(
            {
                "application_id": application["id"],
                "provider": "GlobalCare",
                "coverage_start_date": "2027-01-01T00:00:00Z",
                "coverage_end_date": "2027-05-31T00:00:00Z",
            },
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRAVEL_ADVISORY_BLOCK)
