"""Enrollment creation gates and enrollment listing/pagination."""
from test_helpers import (
    ADMIN,
    MANAGER,
    ApiErrorId,
    api_client,
    assign_applicant,
    create_center,
    create_enrollment_payload,
    create_trade_program,
    enroll_applicant,
    get_applicant,
    make_eligible_applicant,
    validate_error,
    validate_paginated,
    validate_success,
)


def _assigned_applicant(center_id, program, full_name, barrier="FOSTER_CARE",
                        residential_track=False, desired_trade_code="WELDING",
                        home_region_code="R-NORTH"):
    applicant, _case = make_eligible_applicant(
        full_name=full_name, home_region_code=home_region_code,
        desired_trade_code=desired_trade_code, barrier_flags=[barrier],
    )
    assign_applicant(applicant, residential_track=residential_track)
    return get_applicant(applicant["id"])


class TestProgramStateGate:
    def test_enrollment_into_closed_program_rejected(self):
        """PRD section 3.3: "And the program's status must be OPEN — a FULL or
        CLOSED program rejects the create with ERR_PROGRAM_NOT_OPEN."

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_trade_program_open
        """
        center = create_center(name="Gate Center", total_beds=4)
        program = create_trade_program(center["id"], capacity=3)
        applicant = _assigned_applicant(center["id"], program, "Gate Stu")
        close_resp = api_client.patch_trade_program(
            program["id"], {"status": "CLOSED"}, ADMIN
        )
        validate_success(close_resp, 200)
        resp = api_client.create_enrollment(
            create_enrollment_payload(applicant["id"], program["id"]),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)

    def test_rejected_enrollment_leaves_applicant_assigned(self):
        """PRD section 3.3: "The applicant's assignment_status becomes
        ENROLLED" — only on a successful create; a rejected create must not
        move the applicant off ASSIGNED.

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_trade_program_open
        """
        center = create_center(name="Gate Center", total_beds=4)
        program = create_trade_program(center["id"], capacity=3)
        applicant = _assigned_applicant(center["id"], program, "Gate Stu")
        validate_success(
            api_client.patch_trade_program(program["id"], {"status": "CLOSED"},
                                           ADMIN),
            200,
        )
        resp = api_client.create_enrollment(
            create_enrollment_payload(applicant["id"], program["id"]),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)
        assert get_applicant(applicant["id"])["assignment_status"] == "ASSIGNED"
        rows = validate_success(
            api_client.list_enrollments(
                MANAGER, params={"applicant_id": applicant["id"]}
            )
        )
        assert rows == [], "a rejected enrollment create persists no row"


class TestFullProgramGate:
    def test_third_enrollment_into_full_program_rejected(self):
        """PRD section 3.3: "And the program's status must be OPEN — a FULL or
        CLOSED program rejects the create with ERR_PROGRAM_NOT_OPEN."
        PRD section 3.2: "it flips from OPEN to FULL when open_seats reaches 0".

        Design: Corner/state_machines/third_enrollment_into_full_program_rejected
        """
        center = create_center(name="Full Center", total_beds=6)
        program = create_trade_program(center["id"], capacity=2)
        a1 = _assigned_applicant(center["id"], program, "F1")
        a2 = _assigned_applicant(center["id"], program, "F2", barrier="HOMELESS")
        a3 = _assigned_applicant(center["id"], program, "F3", barrier="OFFENDER")
        enroll_applicant(a1["id"], program["id"])
        enroll_applicant(a2["id"], program["id"])
        resp = api_client.create_enrollment(
            create_enrollment_payload(a3["id"], program["id"]), MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)


class TestCenterMismatch:
    def test_enrollment_into_other_centers_program_rejected(self):
        """PRD section 3.3: "The chosen program's center must be the
        applicant's assigned_center_id, else ERR_CENTER_MISMATCH."

        Design: Corner/validations/enrollment_center_mismatch_rejected
        """
        center_a = create_center(name="Mismatch A", region_code="R-NORTH",
                                 total_beds=4)
        create_trade_program(center_a["id"], trade_code="WELDING", capacity=3)
        center_b = create_center(name="Mismatch B", region_code="R-SOUTH",
                                 total_beds=4)
        program_b = create_trade_program(center_b["id"], trade_code="CARPENTRY",
                                         capacity=3)
        applicant, _case = make_eligible_applicant(full_name="Mis Stu")
        result = assign_applicant(applicant)
        assert result["assigned_center_id"] == center_a["id"], (
            "only center A runs the desired trade"
        )
        resp = api_client.create_enrollment(
            create_enrollment_payload(applicant["id"], program_b["id"]),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CENTER_MISMATCH)


class TestAssignmentGate:
    def test_eligible_without_assignment_cannot_enroll(self):
        """PRD section 3.3: "The applicant must currently hold
        assignment_status equal to ASSIGNED, else ERR_APPLICANT_NOT_ELIGIBLE."

        Design: Corner/validations/enroll_without_assignment_rejected
        """
        center = create_center(name="NoAssign Center", total_beds=4)
        program = create_trade_program(center["id"], capacity=3)
        applicant, _case = make_eligible_applicant(full_name="NoAsg Stu")
        resp = api_client.create_enrollment(
            create_enrollment_payload(applicant["id"], program["id"]),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_ELIGIBLE)

    def test_operator_admin_cannot_enroll(self):
        """PRD section 2.1: "A request whose role is authenticated but is not
        listed among the roles authorized for the target endpoint is rejected
        with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/operator_admin_cannot_enroll
        """
        center = create_center(name="Rbac Center", total_beds=4)
        program = create_trade_program(center["id"], capacity=3)
        applicant = _assigned_applicant(center["id"], program, "Adm Stu")
        resp = api_client.create_enrollment(
            create_enrollment_payload(applicant["id"], program["id"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestEnrollmentListing:
    def test_pagination_and_applicant_filter(self):
        """PRD section 2.3: "List responses report limit, offset, total_count,
        and has_more inside the meta object, so a client can page
        deterministically through a collection."
        PRD section 3.3: "Enrollments can be listed with applicant_id,
        trade_program_id, center_id, and training_status filters".

        Design: Corner/endpoints/enrollments_list_pagination_and_filter
        """
        center = create_center(name="Page Center", total_beds=6)
        program = create_trade_program(center["id"], capacity=10)
        applicants = [
            _assigned_applicant(center["id"], program, f"Pg{i}",
                                barrier=b)
            for i, b in enumerate(["FOSTER_CARE", "HOMELESS", "OFFENDER"], 1)
        ]
        enrollments = [enroll_applicant(a["id"], program["id"])
                       for a in applicants]

        page1, meta1 = validate_paginated(
            api_client.list_enrollments(MANAGER, params={"limit": 2,
                                                         "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        body = api_client.list_enrollments(
            MANAGER, params={"limit": 2, "offset": 0}
        ).json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)

        page2, meta2 = validate_paginated(
            api_client.list_enrollments(MANAGER, params={"limit": 2,
                                                         "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

        filtered = validate_success(
            api_client.list_enrollments(
                MANAGER, params={"applicant_id": applicants[1]["id"]}
            )
        )
        assert [row["id"] for row in filtered] == [enrollments[1]["id"]]
