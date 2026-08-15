"""Application submission gates and filtering (PRD §3.2).

Corner instances translated from the entities / validations sections:
application list pagination/filter, reverse-FK isolation, conduct hold,
deadline passed, duplicate application, GPA boundary.
"""
from test_helpers import (
    ApiErrorId,
    create_partner_agreement,
    create_open_program,
    create_student,
    create_submitted_application,
    make_student_headers,
    set_logical_clock,
    setup_open_program_with_application,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    COORD_A_HEADERS,
)


class TestApplicationListing:
    def test_application_list_pagination_and_filter(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/application_list_pagination_and_filter
        """
        program, student_a, app_a = setup_open_program_with_application(
            student_overrides={"full_name": "Page A", "email": "pagea@uni.edu"},
        )
        student_b = create_student(full_name="Page B", email="pageb@uni.edu", gpa=3.10)
        app_b = create_submitted_application(student_b, program)

        page1 = api.list_applications(
            COORD_A_HEADERS, params={"program_id": program["id"], "limit": 1, "offset": 0},
        )
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 1, f"limit=1 must return exactly 1 row, got {len(data1)}"
        assert meta1["total_count"] == 2, (
            f"Two applications exist for the program; total_count must be 2, got {meta1['total_count']}"
        )
        assert meta1["has_more"] is True

        page2 = api.list_applications(
            COORD_A_HEADERS, params={"program_id": program["id"], "limit": 1, "offset": 1},
        )
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["has_more"] is False
        page_ids = {data1[0]["id"], data2[0]["id"]}
        assert page_ids == {app_a["id"], app_b["id"]}, (
            "The two pages must contain the two distinct applications"
        )

    def test_fk_reverse_filter_isolation(self, api):
        """PRD §4: "List applications with filters (`student_id` / `program_id` / `status`)
        and pagination".

        Design: Corner/entities/fk_reverse_filter_isolation
        """
        program, student_a, app_a = setup_open_program_with_application(
            student_overrides={"full_name": "Iso A", "email": "isoa@uni.edu"},
        )
        student_b = create_student(full_name="Iso B", email="isob@uni.edu", gpa=3.10)
        create_submitted_application(student_b, program)

        resp = api.list_applications(
            COORD_A_HEADERS, params={"student_id": student_a["id"]},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, (
            f"Filtering by student_id must return exactly that student's applications, got {len(data)}"
        )
        assert data[0]["id"] == app_a["id"]
        assert data[0]["student_id"] == student_a["id"]
        assert meta["total_count"] == 1


class TestAdmissionGates:
    def test_conduct_hold_blocks_submit(self, api):
        """PRD §3.2: "a `conduct_standing` of `CONDUCT_HOLD` is an absolute bar
        (`ERR_CONDUCT_HOLD`), though `CONDUCT_REVIEW` is not".

        Design: Corner/validations/conduct_hold_blocks_submit
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"])
        student = create_student(
            full_name="Hold Student", email="hold@uni.edu",
            gpa=3.50, conduct_standing="CONDUCT_HOLD",
        )
        resp = api.create_application(
            {"student_id": student["id"], "program_id": program["id"]},
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONDUCT_HOLD)

    def test_deadline_passed_blocks_submit(self, api):
        """PRD §3.2: "the logical clock must not have passed the program's
        `application_deadline` (`ERR_APPLICATION_DEADLINE_PASSED`)".

        Design: Corner/validations/deadline_passed_blocks_submit
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"])
        student = create_student(full_name="Late Student", email="late@uni.edu", gpa=3.50)
        set_logical_clock("2026-12-01T00:00:00Z")
        resp = api.create_application(
            {"student_id": student["id"], "program_id": program["id"]},
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_DEADLINE_PASSED)

    def test_duplicate_application_blocked(self, api):
        """PRD §3.2: "the student may hold at most one active application per program — an
        existing application for the same `(student_id, program_id)` pair in any of
        `SUBMITTED`, `RETURNED_FOR_REVISION`, `CLEARED`, `APPROVED`, `COMMITTED`, `ABROAD`,
        or `RETURNED_HOME` triggers `ERR_DUPLICATE_APPLICATION`."

        Design: Corner/validations/duplicate_application_blocked
        """
        program, student, _app = setup_open_program_with_application()
        resp = api.create_application(
            {"student_id": student["id"], "program_id": program["id"]},
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)


class TestGpaBoundary:
    def test_gpa_exactly_at_minimum_admitted(self, api):
        """PRD §3.2: "the student's `gpa` must be at least the program's `min_gpa`
        (`ERR_GPA_BELOW_MINIMUM`)".

        Design: Difficulty/boundary_precision_check/gpa_exactly_at_minimum
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"], min_gpa=2.75)
        student_in = create_student(full_name="Edge In", email="edgein@uni.edu", gpa=2.75)
        resp = api.create_application(
            {"student_id": student_in["id"], "program_id": program["id"]},
            make_student_headers(student_in["id"]),
        )
        app = validate_success(resp, expected_status=201)
        assert app["status"] == "SUBMITTED", (
            f"gpa == min_gpa (2.75) is inclusive and must be admitted, got {app['status']}"
        )

    def test_gpa_one_cent_below_minimum_rejected(self, api):
        """PRD §3.2: "the student's `gpa` must be at least the program's `min_gpa`
        (`ERR_GPA_BELOW_MINIMUM`)".

        Design: Difficulty/boundary_precision_check/gpa_exactly_at_minimum
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"], min_gpa=2.75)
        student_out = create_student(full_name="Edge Out", email="edgeout@uni.edu", gpa=2.74)
        resp = api.create_application(
            {"student_id": student_out["id"], "program_id": program["id"]},
            make_student_headers(student_out["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GPA_BELOW_MINIMUM)
